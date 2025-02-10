"""Software Engineer LLM agent, handling the creation of patches."""

import difflib
import functools
import logging
import re
from dataclasses import dataclass, field
from operator import itemgetter
from pathlib import Path
from typing import TypedDict, Iterator

from buttercup.common.challenge_task import ChallengeTask
# from buttercup.common.challenge_task.snapshot import SnapshotChallenge, SnapshotError
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
    CONTEXT_COMMIT_TMPL,
    CONTEXT_PROJECT_TMPL,
    CONTEXT_ROOT_CAUSE_TMPL,
    PatcherAgentState,
    PatchOutput,
)
from buttercup.common.llm import ButtercupLLM, create_default_llm, create_llm
from buttercup.patcher.utils import decode_bytes, PatchInput

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

    file_path: str | None = Field(description="The file path of the code snippet")
    function_name: str | None = Field(description="The function name of the code snippet")
    old_code: str | None = Field(
        description="The old piece of code, as-is, with spaces, trailing/leading whitespaces, etc."
    )
    code: str | None = Field(
        description="The fixed piece of code snippet, as-is, with spaces, trailing/leading whitespaces, etc."  # noqa: E501
    )


class CodeSnippetChanges(BaseModel):
    """Code snippet changes"""

    items: list[CodeSnippetChange] | None = Field(description="List of code snippet changes")


class CreateUPatchInput(TypedDict):
    """Input for the create_upatch function"""

    code_snippets: CodeSnippetChanges
    state: PatcherAgentState


@dataclass
class SWEAgent:
    """Software Engineer LLM agent, handling the creation of patches."""

    challenge: ChallengeTask
    input: PatchInput
    # snapshot_challenge: SnapshotChallenge

    llm: Runnable = field(init=False)
    create_patch_chain: Runnable = field(init=False)

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
            ButtercupLLM.AZURE_GPT_4O_MINI,
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

        code_snippets_chain = (
            CREATE_PATCH_STR_PROMPT | self.llm | StrOutputParser() | self.parse_code_snippets
        )
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
                    file_path=file_path, function_name=function_name, old_code=old_code, code=code
                )
            )

        return CodeSnippetChanges(items=items)

    def _get_vulnerable_file_content(self, vulnerable_file: str) -> str | None:
        try:
            vulnerable_path = self.challenge.get_source_path() / vulnerable_file.strip()
            if not vulnerable_path.exists() or not vulnerable_path.is_file():
                logger.error("Could not find file '%s' specified in the context", vulnerable_path)
                # TODO: try to find the file in a smarter way
                logger.warning("Trying to find the file in the task directory")
                vulnerable_path = self.challenge.get_source_path().parent / vulnerable_file.strip()

            if not vulnerable_path.exists() or not vulnerable_path.is_file():
                logger.error("Could not find file '%s' specified in the context", vulnerable_path)
                return None

            res = vulnerable_path.read_text()
            if not isinstance(res, str):
                logger.error("read_text for %s did not return a string", vulnerable_path)
                return None

            return res
        except FileNotFoundError:
            logger.error("Could not read file '%s' specified in the context", vulnerable_file.strip())
            return None

    def get_context(self, state: PatcherAgentState) -> list[BaseMessage | str]:
        """Get the messages for the context."""

        messages: list[BaseMessage | str] = []
        messages += [CONTEXT_PROJECT_TMPL.format(project_name=self.challenge.name)]

        # TODO: add support for multiple diffs if necessary
        diff_content = next(iter(self.challenge.get_diffs())).read_text()

        messages += [CONTEXT_COMMIT_TMPL.format(commit_content=diff_content)]
        if state.get("root_cause"):
            messages += [CONTEXT_ROOT_CAUSE_TMPL.format(root_cause=state["root_cause"])]

        for code_snippet in state.get("relevant_code_snippets") or []:
            messages += [
                CONTEXT_CODE_SNIPPET_TMPL.format(
                    file_path=code_snippet["file_path"],
                    function_name=code_snippet.get("function_name", ""),
                    code=code_snippet.get("code", ""),
                    code_context=code_snippet.get("code_context", ""),
                )
            ]

        return messages

    def create_upatch(self, inp: CreateUPatchInput) -> PatchOutput:
        """Extract the patch the new vulnerable code."""
        code_snippets, state = inp["code_snippets"], inp["state"]

        orig_code_snippets = {
            (cs["file_path"], cs["function_name"]): cs["code"]
            for cs in state["relevant_code_snippets"]
            if cs.get("code") and cs.get("function_name")
        }

        patches: list[PatchOutput] = []
        for code_snippet in code_snippets.items or []:
            if (
                not code_snippet.file_path
                or not code_snippet.old_code
                or not code_snippet.code
                or not code_snippet.function_name
            ):
                continue

            code_snippet_key = (code_snippet.file_path, code_snippet.function_name)
            if code_snippet_key not in orig_code_snippets:
                logger.warning(
                    "Code snippet not found in the original context, trying to continue anyway: %s | %s",  # noqa: E501
                    code_snippet.file_path,
                    code_snippet.function_name,
                )

            file_content = self._get_vulnerable_file_content(code_snippet.file_path)
            if file_content is None:
                logger.warning("Could not read the file: %s", code_snippet.file_path)
                continue

            orig_file_content = file_content
            if code_snippet_key in orig_code_snippets:
                orig_code_snippet = orig_code_snippets[code_snippet_key]
                new_code_snippet = orig_code_snippet.replace(
                    code_snippet.old_code, code_snippet.code
                )
                new_code_snippet = new_code_snippet + (
                    "\n" if orig_code_snippet.endswith("\n") else ""
                )
            else:
                orig_code_snippet = code_snippet.old_code
                new_code_snippet = code_snippet.code

            if orig_code_snippet not in file_content:
                logger.error(
                    "Could not generate a valid patch for %s | %s, original code "
                    "snippet not found in the file",
                    code_snippet.file_path,
                    code_snippet.function_name,
                )
                continue

            file_content = file_content.replace(orig_code_snippet, new_code_snippet)
            # target = Path()
            patched_file = Path(code_snippet.file_path)
            # TODO: check if this is still necessary
            # for cp_source_name in self.challenge.source_names:
            #     if Path(cp_source_name) in patched_file.parents:
            #         target = cp_source_name
            #         patched_file = patched_file.relative_to(target)
            #         break

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
                    "Could not generate a valid patch for %s | %s",
                    code_snippet.file_path,
                    code_snippet.function_name,
                )
                continue

            patch = PatchOutput(
                task_id=self.input.task_id,
                vulnerability_id=self.input.vulnerability_id,
                patch=patch_str,
            )
            patches.append(patch)

        if not patches:
            logger.warning("No valid patches generated")
            return PatchOutput(task_id="", vulnerability_id="", patch="")

        # # Check all patches are about the same target
        # if len(set(p.target for p in patches)) != 1:
        #     logger.warning("All patches must be about the same target")
        #     return None

        # Concatenate all patches in one
        patch_content = "\n".join(p.patch for p in patches)
        final_patch = PatchOutput(
            task_id=self.input.task_id,
            vulnerability_id=self.input.vulnerability_id,
            patch=patch_content,
        )
        return final_patch

    def create_patch_node(self, state: PatcherAgentState) -> dict:
        """Node in the LangGraph that generates a patch (in diff format)"""
        # try:
        #     self.snapshot_challenge.restore()
        # except SnapshotError:
        #     logger.error("Cannot get snapshot for Challenge Task %s", self.challenge.name)
        #     return {
        #         "build_succeeded": False,
        #         "build_stdout": None,
        #         "build_stderr": None,
        #     }

        messages = []
        if state.get("patches"):
            old_patches = FewShotChatMessagePromptTemplate(
                input_variables=[],
                examples=[{"patch": p.patch} for p in state["patches"][-1:]],
                example_prompt=PATCH_PROMPT,
            )
            messages += old_patches.format_messages()

        if state.get("patch_review") is not None:
            messages += ADDRESS_REVIEW_PATCH_PROMPT.format_messages(
                review=state.get("patch_review")
            )
        elif state.get("build_succeeded") is False:
            messages += BUILD_ANALYSIS_PROMPT.format_messages(
                build_failure_analysis=state.get("build_analysis"),
            )
        elif state.get("pov_fixed") is False:
            messages += POV_FAILED_PROMPT.format_messages()
        elif state.get("tests_passed") is False:
            messages += TESTS_FAILED_PROMPT.format_messages(
                tests_stdout=decode_bytes(state.get("tests_stdout")),
                tests_stderr=decode_bytes(state.get("tests_stderr")),
            )

        temperature = 0.0
        is_patch_generated = False

        for _ in range(3):
            patch: PatchOutput = functools.reduce(
                lambda _, y: y,
                self.create_patch_chain.stream(
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
                ),
                PatchOutput(task_id="", vulnerability_id="", patch=""),
            )
            if not patch or not patch.patch:
                logger.error("Could not generate a patch")
                temperature += 0.1
                continue

            if patch.patch in [p.patch for p in (state.get("patches") or [])]:
                logger.error("Generated patch already exists, try again with higher temperature...")
                temperature += 0.2
                continue

            is_patch_generated = True
            break

        if not is_patch_generated:
            raise ValueError("Could not generate a new different patch")

        logger.info("Generated a patch for Challenge Task %s", self.challenge.name)
        logger.debug("Patch: %s", patch.patch)
        patch_tries = (state.get("patch_tries") or 0) + 1
        patches = (state.get("patches") or []) + [patch]
        return {
            "patches": patches,
            "patch_tries": patch_tries,
            "patch_review": None,
            "build_succeeded": None,
            "pov_fixed": None,
            "tests_passed": None,
        }
