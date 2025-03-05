"""Software Engineer LLM agent, handling the creation of patches."""

import difflib
import logging
import re
from dataclasses import dataclass, field
from operator import itemgetter
from pathlib import Path
from typing import Literal

from langgraph.types import Command


from langchain_core.messages import BaseMessage
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import (
    ChatPromptTemplate,
    FewShotChatMessagePromptTemplate,
    MessagesPlaceholder,
)
from pydantic import BaseModel, Field
from langchain_core.runnables import (
    ConfigurableField,
    Runnable,
    RunnableConfig,
    RunnableLambda,
)
from buttercup.patcher.agents.common import (
    CONTEXT_CODE_SNIPPET_TMPL,
    CONTEXT_DIFF_TMPL,
    CONTEXT_PROJECT_TMPL,
    CONTEXT_ROOT_CAUSE_TMPL,
    PatcherAgentState,
    PatcherAgentName,
    PatcherAgentBase,
    CodeSnippetKey,
)
from buttercup.common.llm import ButtercupLLM, create_default_llm, create_llm
from buttercup.patcher.utils import decode_bytes, PatchOutput

logger = logging.getLogger(__name__)


SYSTEM_TMPL = """You are a security engineer tasked with fixing a bug in a \
software project. Fix the bug. Modify only the "Code" section(s) and perform as \
less changes as possible to *only* fix the bug explained in the root cause \
analysis (not other bugs).

You can modify one or more code snippets.
You don't have to modify all the code snippets.
You don't have to output a code snippet if you don't modify it.
If you modify a code snippet, you must provide the "File path" and the "Function
name", together with the old and new code parts. You don't need to rewrite the
whole code snippet, but make sure to write both the old part and the new part.
Moreover, if you don't modify the whole code snippet, include AT LEAST 5 lines
before and after the old part.

Always follow the scheme:

File path: <path-to-file>
Function name: <function-name>
Old code:
```<language>
<old-code>
```
Code:
```<language>
<new-code>
```

For example, the output should look like this:

File path: path/to/file.c
Function name: my_function
Old code:
```c
int my_function(int a) {{
    return a;
}}
```
Code:
```c
int my_function(int a) {{
    return a + 1;
}}
```

File path: path/to/file2.c
Function name: my_function2
Old code:
```c
    
    buf2 = get_buf_from_input();
    printf(buf2);
    // Existing comment
    // Another existing comment
    printf("Hello, World!");
```
Code:
```c
    buf2 = get_buf_from_input();
    printf("%%s", buf2);
    // Existing comment
    // Another existing comment
    printf("Hello, World!");
```
"""  # noqa: W293

CODE_SNIPPET_REGEX = re.compile(
    r"""File path: (.*?)
Function name: (.*?)
Old code:
```.*?
(.*?)
```
Code:
```.*?
(.*?)
```""",
    re.DOTALL | re.IGNORECASE,
)

CREATE_PATCH_STR_PROMPT = ChatPromptTemplate.from_messages(
    [
        ("system", SYSTEM_TMPL),
        MessagesPlaceholder(variable_name="context"),
        MessagesPlaceholder(variable_name="messages", optional=True),
        (
            "user",
            "As output, write the modified code snippets, as instructed, but "
            "with the bug fixed. Leave the extra context intact and do not "
            "output it. Do not output a code snippet that does not require a change.",
        ),
    ]
)

ADDRESS_REVIEW_PATCH_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "human",
            """The last patch you have created does not follow the quality \
assurance guidelines.

The Quality Engineer review:
```
{review}
```

Please generate a patch that fixes the vulnerability and addresses the Quality \
Engineer review. Do not generate an already existing patch.
""",
        ),
    ]
)

FIX_BUILD_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "human",
            """The last patch you have created does not build correctly.

Build stdout:
```
{build_stdout}
```

Build stderr:
```
{build_stderr}
```

Please generate a patch that builds correctly and fixes the vulnerability. Do \
not generate an already existing patch.""",
        ),
    ]
)
BUILD_ANALYSIS_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "human",
            """The last patch you have created does not build correctly. Another \
software engineer has provided the following analysis about the build failures.
Build failure analysis:
```
{build_failure_analysis}
```
Please generate a patch that builds correctly and fixes the vulnerability. Do \
not generate an already existing patch.""",
        )
    ]
)

PATCH_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "ai",
            """Patch:
```
{patch}
```""",
        ),
        ("user", "This patch does not work (build, fix vulnerability, tests, etc.)."),
    ]
)

POV_FAILED_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "human",
            "The last patch you have created does not fix the vulnerability \
correctly. Please generate a patch that fixes the vulnerability. Do not generate \
an already existing patch.",
        ),
    ]
)

TESTS_FAILED_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "human",
            """The last patch you have created does not pass some tests.

Tests stdout:
```
{tests_stdout}
```

Tests stderr:
```
{tests_stderr}
```

Please generate a new patch that fixes the vulnerability but also makes the \
tests work. Do not generate an already existing patch.""",
        ),
    ]
)


class CodeSnippetChange(BaseModel):
    """Code snippet change"""

    key: CodeSnippetKey = Field(description="The key of the code snippet")
    old_code: str | None = Field(
        description="The old piece of code, as-is, with spaces, trailing/leading whitespaces, etc."
    )
    code: str | None = Field(
        description="The fixed piece of code snippet, as-is, with spaces, trailing/leading whitespaces, etc."  # noqa: E501
    )

    def is_valid(self) -> bool:
        """Check if the code snippet change is valid"""
        return self.key.file_path and self.key.function_name and self.old_code and self.code


class CodeSnippetChanges(BaseModel):
    """Code snippet changes"""

    items: list[CodeSnippetChange] | None = Field(description="List of code snippet changes")


class CreateUPatchInput(BaseModel):
    """Input for the create_upatch function"""

    code_snippets: CodeSnippetChanges
    state: PatcherAgentState


@dataclass
class SWEAgent(PatcherAgentBase):
    """Software Engineer LLM agent, handling the creation of patches."""

    llm: Runnable = field(init=False)
    create_patch_chain: Runnable = field(init=False)

    MATCH_RATIO_THRESHOLD: float = 0.8

    def __post_init__(self) -> None:
        """Initialize a few fields"""
        default_llm = create_default_llm(temperature=0.1).configurable_fields(
            temperature=ConfigurableField(
                id="llm_temperature",
                name="LLM temperature",
                description="The temperature for the LLM model",
            ),
        )
        fallback_llms: list[Runnable] = []
        for fb_model in [
            ButtercupLLM.OPENAI_GPT_4O_MINI,
        ]:
            fallback_llms.append(
                create_llm(model_name=fb_model.value, temperature=0.1).configurable_fields(
                    temperature=ConfigurableField(
                        id="llm_temperature",
                        name="LLM temperature",
                        description="The temperature for the LLM model",
                    ),
                )
            )
        self.llm = default_llm.with_fallbacks(fallback_llms)

        code_snippets_chain = CREATE_PATCH_STR_PROMPT | self.llm | StrOutputParser() | self.parse_code_snippets
        self.create_patch_chain = {
            "code_snippets": code_snippets_chain,
            "state": itemgetter("state"),
        } | RunnableLambda(self.create_upatch)

    def parse_code_snippets(self, msg: str) -> CodeSnippetChanges:
        """Parse the code snippets from the string."""
        matches = CODE_SNIPPET_REGEX.findall(msg)
        items: list[CodeSnippetChange] = []
        for match in matches:
            file_path, function_name, old_code, code = match
            items.append(
                CodeSnippetChange(
                    key=CodeSnippetKey(file_path=file_path.strip(), function_name=function_name.strip()),
                    old_code=old_code,
                    code=code,
                )
            )

        return CodeSnippetChanges(items=items)

    def _get_file_content(self, file_path: str) -> str | None:
        """Get the content of a file, trying multiple search strategies."""
        file_path = file_path.strip()
        file_path = self.rebase_src_path(file_path)

        search_paths = [
            # Strategy 1: Direct path from source
            lambda: [self.challenge.get_source_path() / file_path],
            # Strategy 2: Parent directory
            lambda: [self.challenge.get_source_path().parent / file_path],
            # Strategy 3: Search recursively in source directory
            lambda: list(self.challenge.get_source_path().rglob(Path(file_path))),
            # Strategy 4: Search recursively in source directory for just the file name
            lambda: list(self.challenge.get_source_path().rglob(Path(file_path).name)),
        ]

        for path_fn in search_paths:
            try:
                paths = path_fn()
            except Exception as e:
                logger.debug("Error getting file content for %s: %s", file_path, e)
                continue

            for path in paths:
                if path.exists() and path.is_file():
                    try:
                        res = path.read_text()
                        if isinstance(res, str):
                            logger.debug("Got file content for %s", file_path)
                            return res

                        logger.error("read_text for %s did not return a string", path)
                    except OSError as e:
                        logger.debug("Could not read file %s: %s", path, e)
                        continue

        logger.error("Could not find file '%s' after trying multiple locations", file_path)
        return None

    def get_context(self, state: PatcherAgentState) -> list[BaseMessage | str]:
        """Get the messages for the context."""

        messages: list[BaseMessage | str] = []
        messages += [CONTEXT_PROJECT_TMPL.format(project_name=self.challenge.name)]

        # TODO: add support for multiple diffs if necessary
        diff_content = next(iter(self.challenge.get_diffs())).read_text()

        messages += [CONTEXT_DIFF_TMPL.format(diff_content=diff_content)]
        if state.root_cause:
            messages += [CONTEXT_ROOT_CAUSE_TMPL.format(root_cause=state.root_cause)]

        for code_snippet in state.relevant_code_snippets:
            messages += [
                CONTEXT_CODE_SNIPPET_TMPL.format(
                    file_path=code_snippet.file_path,
                    function_name=code_snippet.function_name,
                    code=code_snippet.code,
                    code_context=code_snippet.code_context,
                )
            ]

        return messages

    def _find_closest_match(
        self, orig_code_snippets: dict[CodeSnippetKey, str], target_key: CodeSnippetKey
    ) -> CodeSnippetKey | None:
        """Find the closest matching file path and function name in orig_code_snippets."""
        if not orig_code_snippets:
            return None

        # First try exact function name match with fuzzy file path
        func_matches = [key for key in orig_code_snippets.keys() if key.function_name == target_key.function_name]
        if func_matches:
            # Find best file path match among function matches
            best_match = max(
                func_matches, key=lambda x: difflib.SequenceMatcher(None, target_key.file_path, x.file_path).ratio()
            )
            match_ratio = difflib.SequenceMatcher(None, target_key.file_path, best_match.file_path).ratio()
            if match_ratio > self.MATCH_RATIO_THRESHOLD:
                return best_match

        # If no good match found with function name, try best overall match
        best_match = max(
            orig_code_snippets.keys(),
            key=lambda x: difflib.SequenceMatcher(None, target_key.file_path, x.file_path).ratio(),
        )
        match_ratio = difflib.SequenceMatcher(None, target_key.file_path, best_match.file_path).ratio()
        return best_match if match_ratio > self.MATCH_RATIO_THRESHOLD else None

    def _get_code_snippet_key(
        self, code_snippet: CodeSnippetChange, orig_code_snippets: dict[CodeSnippetKey, str]
    ) -> CodeSnippetKey | None:
        code_snippet_key = CodeSnippetKey(
            file_path=code_snippet.key.file_path, function_name=code_snippet.key.function_name
        )
        if code_snippet_key not in orig_code_snippets:
            closest_match = self._find_closest_match(orig_code_snippets, code_snippet_key)
            if closest_match:
                logger.info(
                    "Found similar file match: '%s' -> '%s'",
                    code_snippet_key,
                    closest_match,
                )
                code_snippet_key = closest_match
            else:
                logger.warning(
                    "Code snippet not found in the original context, trying to continue anyway: %s",
                    code_snippet_key,
                )

        return code_snippet_key

    def _get_snippets_patches(
        self, code_snippets: CodeSnippetChanges, orig_code_snippets: dict[CodeSnippetKey, str]
    ) -> list[PatchOutput]:
        patches: list[PatchOutput] = []
        for code_snippet_idx, code_snippet in enumerate(code_snippets.items or []):
            if not code_snippet.is_valid():
                logger.warning("Invalid code snippet: %s (%d)", code_snippet.key, code_snippet_idx)
                continue

            code_snippet_key = self._get_code_snippet_key(code_snippet, orig_code_snippets)
            if not code_snippet_key:
                logger.warning(
                    "Could not find a valid code snippet key for %s (%d)", code_snippet.key, code_snippet_idx
                )
                code_snippet_key = CodeSnippetKey(
                    file_path=code_snippet.key.file_path, function_name=code_snippet.key.function_name
                )

            file_content = self._get_file_content(code_snippet_key.file_path)
            if file_content is None:
                logger.warning("Could not read the file: %s", code_snippet_key.file_path)
                continue

            orig_file_content = file_content
            if code_snippet_key in orig_code_snippets:
                logger.debug("Found code snippet in orig_code_snippets: %s (%d)", code_snippet_key, code_snippet_idx)
                orig_code_snippet = orig_code_snippets[code_snippet_key]
                new_code_snippet = orig_code_snippet.replace(code_snippet.old_code, code_snippet.code)
            else:
                logger.debug(
                    "Code snippet not found in orig_code_snippets: %s (%d)", code_snippet_key, code_snippet_idx
                )
                orig_code_snippet = code_snippet.old_code
                new_code_snippet = code_snippet.code

            if orig_code_snippet not in file_content:
                logger.error(
                    "Could not generate a valid patch for %s (%d), original code snippet not found in the file",
                    code_snippet_key,
                    code_snippet_idx,
                )
                continue

            file_content = file_content.replace(orig_code_snippet, new_code_snippet)
            patched_file = Path(code_snippet_key.file_path)

            patch = difflib.unified_diff(
                orig_file_content.splitlines(),
                file_content.splitlines(),
                lineterm="",
                fromfile="a/" + str(patched_file),
                tofile="b/" + str(patched_file),
            )
            patch_str = "\n".join(patch) + "\n"
            if not patch_str.strip():
                logger.warning(
                    "Could not generate a valid patch for %s (%d)",
                    code_snippet_key,
                    code_snippet_idx,
                )
                continue

            logger.debug("Generated patch for %s (%d)", code_snippet_key, code_snippet_idx)
            patch = PatchOutput(
                task_id=self.input.task_id,
                vulnerability_id=self.input.vulnerability_id,
                patch=patch_str,
            )
            patches.append(patch)

        return patches

    def create_upatch(self, inp: CreateUPatchInput | dict) -> PatchOutput:
        """Extract the patch the new vulnerable code."""
        inp = inp if isinstance(inp, CreateUPatchInput) else CreateUPatchInput(**inp)
        code_snippets, state = inp.code_snippets, inp.state

        orig_code_snippets = {
            CodeSnippetKey(file_path=cs.file_path, function_name=cs.function_name): cs.code
            for cs in (state.relevant_code_snippets)
            if cs.code and cs.function_name
        }

        logger.debug("Creating patches for %d code snippets", len(code_snippets.items or []))
        patches: list[PatchOutput] = self._get_snippets_patches(code_snippets, orig_code_snippets)
        if not patches:
            logger.warning("No valid patches generated")
            return PatchOutput(task_id="", vulnerability_id="", patch="")

        # Concatenate all patches in one
        logger.debug("Concatenating %d patches", len(patches))
        patch_content = "\n".join(p.patch for p in patches)
        final_patch = PatchOutput(
            task_id=self.input.task_id,
            vulnerability_id=self.input.vulnerability_id,
            patch=patch_content,
        )
        return final_patch

    def create_patch_node(self, state: PatcherAgentState) -> Command[Literal[PatcherAgentName.REVIEW_PATCH.value]]:
        """Node in the LangGraph that generates a patch (in diff format)"""
        logger.info("Creating a patch for Challenge Task %s", self.challenge.name)
        self.challenge.restore()

        messages = []
        last_patch = state.get_last_patch()
        if last_patch:
            old_patches = FewShotChatMessagePromptTemplate(
                input_variables=[],
                examples=[{"patch": last_patch.patch}],
                example_prompt=PATCH_PROMPT,
            )
            messages += old_patches.format_messages()

        if state.patch_review is not None:
            messages += ADDRESS_REVIEW_PATCH_PROMPT.format_messages(review=state.patch_review)
        elif state.build_succeeded is False:
            messages += BUILD_ANALYSIS_PROMPT.format_messages(
                build_failure_analysis=state.build_analysis,
            )
        elif state.pov_fixed is False:
            messages += POV_FAILED_PROMPT.format_messages()
        elif state.tests_passed is False:
            messages += TESTS_FAILED_PROMPT.format_messages(
                tests_stdout=decode_bytes(state.tests_stdout),
                tests_stderr=decode_bytes(state.tests_stderr),
            )

        temperature = 0.0
        is_patch_generated = False

        for _ in range(3):
            patch: PatchOutput = self.chain_call(
                lambda _, y: y,
                self.create_patch_chain,
                {
                    "context": self.get_context(state),
                    "state": state,
                    "messages": messages,
                },
                config=RunnableConfig(
                    configurable={
                        "llm_temperature": temperature,
                    },
                ),
                default=PatchOutput(task_id="", vulnerability_id="", patch=""),
            )
            if not patch or not patch.patch:
                logger.error("Could not generate a patch")
                temperature += 0.1
                continue

            if patch.patch in [p.patch for p in (state.patches)]:
                logger.error("Generated patch already exists, try again with higher temperature...")
                temperature += 0.2
                continue

            is_patch_generated = True
            break

        if not is_patch_generated:
            raise ValueError("Could not generate a new different patch")

        logger.info("Generated a patch for Challenge Task %s", self.challenge.name)
        logger.debug("Patch: %s", patch.patch)
        patch_tries = state.patch_tries + 1
        patches = state.patches + [patch]
        return Command(
            update={
                "patches": patches,
                "patch_tries": patch_tries,
                "patch_review": None,
                "build_succeeded": False,
                "pov_fixed": False,
                "tests_passed": False,
            },
            goto=PatcherAgentName.REVIEW_PATCH.value,
        )
