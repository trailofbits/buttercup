"""Software Engineer LLM agent, handling the creation of patches."""

import difflib
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from langgraph.types import Command
from langgraph.constants import END


from langchain_core.messages import BaseMessage
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import (
    ChatPromptTemplate,
)
from pydantic import BaseModel, Field
from langchain_core.runnables import (
    ConfigurableField,
    Runnable,
)
from buttercup.patcher.agents.common import (
    CONTEXT_CODE_SNIPPET_TMPL,
    CONTEXT_DIFF_TMPL,
    CONTEXT_PROJECT_TMPL,
    CONTEXT_ROOT_CAUSE_TMPL,
    ContextRetrieverState,
    PatcherAgentState,
    PatcherAgentName,
    PatcherAgentBase,
    CodeSnippetKey,
    CodeSnippetRequest,
)
from buttercup.common.llm import ButtercupLLM, create_default_llm
from buttercup.patcher.utils import decode_bytes, PatchOutput, get_diff_content

logger = logging.getLogger(__name__)

SYSTEM_MSG = (
    """You are a skilled software engineer tasked with generating a patch for a specific vulnerability in a project."""
)
USER_MSG = """Your primary goal is to fix only the described vulnerability.

First, review the following project information and vulnerability analysis:

Project Name:
<project_name>
{PROJECT_NAME}
</project_name>

Root Cause Analysis:
<root_cause_analysis>
{ROOT_CAUSE_ANALYSIS}
</root_cause_analysis>

Code Snippets that may need modification:
<code_snippets>
{CODE_SNIPPETS}
</code_snippets>
{PREVIOUS_PATCH_PROMPT}{REVIEW_PROMPT}{BUILD_ANALYSIS_PROMPT}{POV_FAILED_PROMPT}{TESTS_FAILED_PROMPT}

Instructions:

1. Review the provided information carefully.

2. Plan your patch approach. Wrap your analysis and solution planning inside <vulnerability_analysis_and_solution> tags. In this section:
   a) List all vulnerable parts of the code
   b) If available
   b.1) consider the Quality Engineer review comments and focus on addressing them
   b.2) consider the build failure analysis and focus on addressing it
   b.3) consider the POV failure analysis and focus on addressing it
   b.4) consider the tests failure analysis and focus on addressing it
   c) Propose multiple potential solutions for the vulnerability
   d) Evaluate each solution's pros and cons
   e) If you need additional context to patch the project, request it using <code_requests> tags. Be specific about what code you need and why. For example:
        <code_requests>
        <code_request>
        Full implementation of the function 'validate_input()' from the file 'input_validation.c', as it's referenced in the analysis but not fully visible.
        </code_request>
        <code_request>
        ...
        </code_request>
        </code_requests>
        If you make a code request, wait for a response before proceeding.
   f) Choose the best solution:
        Consider:
        - The specific part(s) of the code that need modification
        - Potential solutions and their pros/cons

3. Explain the changes you intend to make and how they fix the vulnerability. Use <explanation> tags for this section.
   - If you need other code snippets to fix the vulnerability, request them using <code_requests> tags.

4. Generate the patch based on your planning and explanation. Remember:
   - Only fix the described vulnerability
   - You can modify one or more code snippets
   - You don't have to modify all code snippets
   - You don't need to output snippets you haven't modified

5. Format your output as follows for each modified code snippet:

<patch>
<identifier>[Identifier of the code snippet]</identifier>
<file_path>[File path of the code snippet]</file_path>
<old_code>
[Include at least 5 lines before the modified part, if available]
[Old code that needs to be replaced]
[Include at least 5 lines after the modified part, if available]
</old_code>
<new_code>
[Include at least 5 lines before the modified part, if available]
[New code that fixes the vulnerability]
[Include at least 5 lines after the modified part, if available]
</new_code>
</patch>

Remember to focus solely on fixing the described vulnerability. Do not make any unrelated changes or improvements to the code.
Begin your vulnerability analysis and solution planning now. If you need to request additional code, do so before providing any patches.
"""

PROMPT = ChatPromptTemplate.from_messages(
    [
        ("system", SYSTEM_MSG),
        ("user", USER_MSG),
        ("ai", "<vulnerability_analysis_and_solution>"),
    ]
)

ADDRESS_REVIEW_PATCH_PROMPT = """
The last patch you have created does not pass the review process performed by the Quality Engineer. The Quality Engineer has provided the following review:

<quality_engineer_review>
{PATCH_REVIEW}
</quality_engineer_review>

Please generate a new patch that fixes the vulnerability and addresses the Quality Engineer review. Do not generate an already existing patch.
When considering possible patch solutions, consider the review comments.
"""

BUILD_ANALYSIS_PROMPT = """
The last patch you have created does not build correctly. Another \
software engineer has provided the following analysis about the build failures.
Build failure analysis:

<build_failure_analysis>
{build_failure_analysis}
</build_failure_analysis>

Please generate a patch that builds correctly and fixes the vulnerability. Do \
not generate an already existing patch.
"""

PATCH_PROMPT = """
You previously tried the following patch, but it was not good enough (it failed the review process, failed to build, failed to fix the vulnerability, failed the tests, etc.).

<previous_patch>
{PREVIOUS_PATCH}
</previous_patch>
"""

POV_FAILED_PROMPT = """
The last patch you have created does not fix the vulnerability \
correctly. Please generate a patch that fixes the vulnerability. Do not generate \
an already existing patch.
"""


TESTS_FAILED_PROMPT = """
The last patch you have created does not pass some tests.

Tests stdout:
<tests_stdout>
{tests_stdout}
</tests_stdout>

Tests stderr:
<tests_stderr>
{tests_stderr}
</tests_stderr>

Please generate a new patch that fixes the vulnerability but also makes the \
tests work. Do not generate an already existing patch.
"""


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
        return bool(self.key.file_path and self.key.identifier and self.old_code and self.code)


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
    max_patch_retries: int = 30

    MATCH_RATIO_THRESHOLD: float = 0.8

    def __post_init__(self) -> None:
        """Initialize a few fields"""
        default_llm = create_default_llm(model_name=ButtercupLLM.OPENAI_GPT_4O.value).configurable_fields(
            temperature=ConfigurableField(
                id="llm_temperature",
                name="LLM temperature",
                description="The temperature for the LLM model",
            ),
        )
        fallback_llms: list[Runnable] = []
        for fb_model in [
            ButtercupLLM.CLAUDE_3_5_SONNET,
        ]:
            fallback_llms.append(
                create_default_llm(model_name=fb_model.value).configurable_fields(
                    temperature=ConfigurableField(
                        id="llm_temperature",
                        name="LLM temperature",
                        description="The temperature for the LLM model",
                    ),
                )
            )
        self.llm = default_llm.with_fallbacks(fallback_llms)

        self.code_snippets_chain = PROMPT | self.llm | StrOutputParser()

    def parse_code_snippets(self, msg: str) -> CodeSnippetChanges:
        """Parse the code snippets from the string."""
        code_snippets_re = re.compile(
            r"<patch>.*?<identifier>(.*?)</identifier>.*?<file_path>(.*?)</file_path>.*?<old_code>(.*?)</old_code>.*?<new_code>(.*?)</new_code>.*?</patch>",
            re.DOTALL | re.IGNORECASE,
        )
        matches = code_snippets_re.findall(msg)
        items: list[CodeSnippetChange] = []
        for match in matches:
            identifier, file_path, old_code, code = match
            items.append(
                CodeSnippetChange(
                    key=CodeSnippetKey(file_path=file_path.strip(), identifier=identifier.strip()),
                    old_code=old_code.strip("\n"),
                    code=code.strip("\n"),
                )
            )

        logger.debug("Parsed %d code snippets", len(items))
        return CodeSnippetChanges(items=items)

    def _get_file_content(self, file_path: str) -> tuple[str, str] | None:
        """Get the content of a file, trying multiple search strategies. Returns
        the content of the file and the relative path of the file (from the
        source path)."""
        file_path = file_path.strip()
        file_path = self.rebase_src_path(file_path)

        search_paths = [
            # Strategy 1: Direct path from source
            lambda: [self.challenge.task_dir / file_path],
            # Strategy 2: Parent directory
            lambda: [self.challenge.task_dir.parent / file_path],
            # Strategy 3: Search recursively in source directory
            lambda: list(self.challenge.task_dir.rglob(file_path)),
            # Strategy 4: Search recursively in source directory for just the file name
            lambda: list(self.challenge.task_dir.rglob(file_path.name)),
        ]

        for path_fn in search_paths:
            try:
                paths = path_fn()
            except Exception as e:
                logger.debug("Error getting file content for %s: %s", file_path, e)
                continue

            for path in paths:
                if not path.exists() or not path.is_file():
                    logger.debug("File %s does not exist or is not a file", path)
                    continue

                if not path.is_relative_to(self.challenge.get_source_path()):
                    logger.debug("File %s is not relative to the source path", path)
                    continue

                try:
                    res = path.read_text()
                    if isinstance(res, str):
                        logger.debug("Got file content for %s", file_path)
                        return res, str(path.relative_to(self.challenge.get_source_path()))

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

        diff_content = get_diff_content(self.challenge)

        messages += [CONTEXT_DIFF_TMPL.format(diff_content=diff_content)]
        if state.root_cause:
            messages += [CONTEXT_ROOT_CAUSE_TMPL.format(root_cause=state.root_cause)]

        for code_snippet in state.relevant_code_snippets:
            messages += [
                CONTEXT_CODE_SNIPPET_TMPL.format(
                    file_path=code_snippet.key.file_path,
                    identifier=code_snippet.key.identifier,
                    code=code_snippet.code,
                    code_context=code_snippet.code_context,
                )
            ]

        return messages

    def _find_closest_match(
        self, orig_code_snippets: dict[CodeSnippetKey, str], target_key: CodeSnippetKey
    ) -> CodeSnippetKey | None:
        """Find the closest matching CodeSnippetKey in orig_code_snippets."""

        def sequence_ratio(x: CodeSnippetKey) -> float:
            return difflib.SequenceMatcher(None, str(target_key.file_path), str(x.file_path)).ratio()

        if not orig_code_snippets:
            return None

        # First try exact identifier match with fuzzy file path
        matches = [key for key in orig_code_snippets.keys() if key.identifier == target_key.identifier]
        if matches:
            # Find best file path match among matches
            best_match = max(matches, key=sequence_ratio)
            match_ratio = sequence_ratio(best_match)
            if match_ratio > self.MATCH_RATIO_THRESHOLD:
                return best_match

        # If no good match found with identifier, try best overall match
        best_match = max(orig_code_snippets.keys(), key=sequence_ratio)
        match_ratio = sequence_ratio(best_match)
        return best_match if match_ratio > self.MATCH_RATIO_THRESHOLD else None

    def _get_code_snippet_key(
        self, code_snippet: CodeSnippetChange, orig_code_snippets: dict[CodeSnippetKey, str]
    ) -> CodeSnippetKey | None:
        code_snippet_key = CodeSnippetKey(file_path=code_snippet.key.file_path, identifier=code_snippet.key.identifier)
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
                return None

        return code_snippet_key

    def _get_snippets_patches(
        self, code_snippets: CodeSnippetChanges, orig_code_snippets: dict[CodeSnippetKey, str]
    ) -> tuple[list[PatchOutput], list[CodeSnippetRequest]]:
        patches: list[PatchOutput] = []
        code_snippet_requests: list[CodeSnippetRequest] = []
        for code_snippet_idx, code_snippet in enumerate(code_snippets.items or []):
            if not code_snippet.is_valid():
                logger.warning("Invalid code snippet: %s (%d)", code_snippet.key, code_snippet_idx)
                continue

            code_snippet_key = self._get_code_snippet_key(code_snippet, orig_code_snippets)
            if not code_snippet_key:
                logger.warning(
                    "Could not find a valid code snippet key for %s (%d)", code_snippet.key, code_snippet_idx
                )
                code_snippet_requests.append(
                    CodeSnippetRequest(
                        request="Provide code snippet %s / %s"
                        % (code_snippet.key.file_path, code_snippet.key.identifier)
                    )
                )
                continue

            assert code_snippet_key.file_path, "Code snippet key file path is empty"
            if not code_snippet.old_code or not code_snippet.code:
                logger.warning(
                    "Code snippet %s (%d) has no old code or new code, skipping",
                    code_snippet_key,
                    code_snippet_idx,
                )
                continue

            get_file_content_result = self._get_file_content(code_snippet_key.file_path)
            if get_file_content_result is None:
                logger.warning("Could not read the file: %s", code_snippet_key.file_path)
                continue

            file_content, file_path = get_file_content_result

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
            patched_file = Path(file_path)

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
            patch_output = PatchOutput(
                task_id=self.input.task_id,
                vulnerability_id=self.input.vulnerability_id,
                patch=patch_str,
            )
            patches.append(patch_output)

        return patches, code_snippet_requests

    def create_upatch(self, inp: CreateUPatchInput | dict) -> PatchOutput | list[CodeSnippetRequest]:
        """Extract the patch the new vulnerable code."""
        inp = inp if isinstance(inp, CreateUPatchInput) else CreateUPatchInput(**inp)
        code_snippets, state = inp.code_snippets, inp.state

        orig_code_snippets = {
            CodeSnippetKey(file_path=cs.key.file_path, identifier=cs.key.identifier): cs.code
            for cs in state.relevant_code_snippets
            if cs.code and cs.key.identifier
        }

        logger.debug("Creating patches for %d code snippets", len(code_snippets.items or []))
        patches, code_snippet_requests = self._get_snippets_patches(code_snippets, orig_code_snippets)
        if not patches or code_snippet_requests:
            logger.warning("No valid patches generated")
            return code_snippet_requests

        # Concatenate all patches in one
        logger.debug("Concatenating %d patches", len(patches))
        patch_content = "\n".join(p.patch for p in patches)
        final_patch = PatchOutput(
            task_id=self.input.task_id,
            vulnerability_id=self.input.vulnerability_id,
            patch=patch_content,
        )
        return final_patch

    def create_patch_node(
        self, state: PatcherAgentState
    ) -> Command[  # type: ignore[name-defined]
        Literal[
            PatcherAgentName.REVIEW_PATCH.value,
            PatcherAgentName.ROOT_CAUSE_ANALYSIS.value,
            PatcherAgentName.CONTEXT_RETRIEVER.value,
            END,
        ]
    ]:
        """Node in the LangGraph that generates a patch (in diff format)"""
        if state.patch_tries >= self.max_patch_retries:
            logger.warning("Reached max patch tries, terminating the patching process")
            return Command(
                update=state,
                goto=END,
            )

        logger.info("Creating a patch for Challenge Task %s", self.challenge.name)
        self.challenge.restore()

        update_state = {
            "patch_review": None,
            "build_succeeded": None,
            "pov_fixed": None,
            "tests_passed": None,
        }

        previous_patch_prompt = ""
        review_prompt = ""
        build_analysis_prompt = ""
        pov_failed_prompt = ""
        tests_failed_prompt = ""

        last_patch = state.get_last_patch()
        if last_patch:
            previous_patch_prompt = PATCH_PROMPT.format(PREVIOUS_PATCH=last_patch.patch)

        if state.patch_review is not None:
            review_prompt = ADDRESS_REVIEW_PATCH_PROMPT.format(PATCH_REVIEW=state.patch_review)
        elif state.build_succeeded is False:
            build_analysis_prompt = BUILD_ANALYSIS_PROMPT.format(build_failure_analysis=state.build_analysis)
        elif state.pov_fixed is False:
            pov_failed_prompt = POV_FAILED_PROMPT.format()
        elif state.tests_passed is False:
            tests_failed_prompt = TESTS_FAILED_PROMPT.format(
                tests_stdout=decode_bytes(state.tests_stdout),
                tests_stderr=decode_bytes(state.tests_stderr),
            )

        patch_str: str = self.chain_call(
            lambda x, y: x + y,
            self.code_snippets_chain,
            {
                "PROJECT_NAME": self.challenge.name,
                "ROOT_CAUSE_ANALYSIS": state.root_cause,
                "CODE_SNIPPETS": "\n".join(map(str, state.relevant_code_snippets)),
                "PREVIOUS_PATCH_PROMPT": previous_patch_prompt,
                "REVIEW_PROMPT": review_prompt,
                "BUILD_ANALYSIS_PROMPT": build_analysis_prompt,
                "POV_FAILED_PROMPT": pov_failed_prompt,
                "TESTS_FAILED_PROMPT": tests_failed_prompt,
            },
            default="",  # type: ignore[call-arg]
        )
        goto, update_state = self.get_code_snippet_requests(
            patch_str,
            update_state,
            state.ctx_request_limit,
            current_node=PatcherAgentName.CREATE_PATCH.value,
            default_goto=PatcherAgentName.REVIEW_PATCH.value,
        )
        if goto == PatcherAgentName.CONTEXT_RETRIEVER.value:
            return Command(
                update=update_state,
                goto=goto,
            )

        create_upatch_input = CreateUPatchInput(
            code_snippets=self.parse_code_snippets(patch_str),
            state=state,
        )
        patch = self.create_upatch(create_upatch_input)
        if isinstance(patch, list):
            logger.info("Requesting new code snippets for patch generation")
            return Command(
                update=ContextRetrieverState(
                    code_snippet_requests=patch,
                    prev_node=PatcherAgentName.CREATE_PATCH.value,
                ),
                goto=PatcherAgentName.CONTEXT_RETRIEVER.value,
            )

        if not patch or not patch.patch:
            logger.error("Could not generate a patch")
            return Command(
                update=update_state,
                goto=PatcherAgentName.ROOT_CAUSE_ANALYSIS.value,
            )

        logger.info("Generated a patch for Challenge Task %s", self.challenge.name)
        logger.debug("Patch: %s", patch.patch)
        patch_tries = state.patch_tries + 1
        patches = state.patches + [patch]
        update_state.update(
            {
                "patches": patches,
                "patch_tries": patch_tries,
            }
        )
        if patch.patch in [p.patch for p in (state.patches)]:
            logger.warning("Generated patch already exists, going back to root cause analysis")
            return Command(
                update=update_state,
                goto=PatcherAgentName.ROOT_CAUSE_ANALYSIS.value,
            )

        return Command(
            update=update_state,
            goto=PatcherAgentName.REVIEW_PATCH.value,
        )
