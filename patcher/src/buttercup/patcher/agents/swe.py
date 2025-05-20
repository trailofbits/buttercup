"""Software Engineer LLM agent, handling the creation of patches."""

from __future__ import annotations

import difflib
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from langgraph.types import Command

from langchain_openai.chat_models.base import BaseChatOpenAI
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import (
    ChatPromptTemplate,
)
from pydantic import BaseModel, Field
from langchain_core.runnables import (
    Runnable,
    RunnableConfig,
)
from buttercup.patcher.agents.common import (
    PatcherAgentState,
    PatcherAgentName,
    PatcherAgentBase,
    CodeSnippetKey,
    CodeSnippetRequest,
    PatchAttempt,
    PatchStatus,
    PatchStrategy,
)
from buttercup.common.llm import ButtercupLLM, create_default_llm_with_temperature
from buttercup.patcher.utils import PatchOutput, find_file_in_source_dir, pick_temperature

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
{ROOT_CAUSE_ANALYSIS}

Code Snippets that may need modification:
<code_snippets>
{CODE_SNIPPETS}
</code_snippets>

Patch strategy:
<patch_strategy>
{PATCH_STRATEGY}
</patch_strategy>

{PREVIOUS_PATCH_PROMPT}
{REFLECTION_GUIDANCE}

Instructions:

1. Review the provided information carefully.

2. Review the provided patch strategy and describe in more details the changes you intend to make to follow the strategy.

3. Generate the patch based on the strategy, your planning and explanation. Remember:
   - Only fix the described vulnerability
   - You can modify one or more code snippets
   - You don't have to modify all code snippets
   - You don't need to output snippets you haven't modified
   - Do not make up any code, only use code that you know is present in the codebase.
   - Do not put placeholders or TODOs in the code, if you suggest a change, you should know the exact code to put there.

5. Provide a description of the changes you intend to make. Use <description> tags for this section.

<description>
[Description of the changes you intend to make]
</description>

6. Format your output as follows for each modified code snippet:

<patch>
<file_path>[File path of the code snippet]</file_path>
<identifier>[Identifier of the code snippet]</identifier>
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

Remember to focus solely on fixing the described vulnerability.
Do not make any unrelated changes or improvements to the code.
Do not make up any code, only use code that you know is present in the codebase.
Begin your vulnerability analysis and solution planning now.
"""

PROMPT = ChatPromptTemplate.from_messages(
    [
        ("system", SYSTEM_MSG),
        ("user", USER_MSG),
        ("ai", "<vulnerability_analysis_and_solution>"),
    ]
)

PATCH_STRATEGY_SYSTEM_MSG = """You are an AI agent in a multi-agent LLM-based autonomous patching system."""
PATCH_STRATEGY_USER_MSG = """Your role is to develop a focused patch strategy for a specific vulnerability based on provided information and code snippets. Your task is to identify the exact changes needed to fix the vulnerability, nothing more.

Here is the information you need to analyze:

<project_name>
{PROJECT_NAME}
</project_name>

<root_cause_analysis>
{ROOT_CAUSE_ANALYSIS}
</root_cause_analysis>

<code_snippets>
{CODE_SNIPPETS}
</code_snippets>

{REFLECTION_GUIDANCE}

Your task is to develop a precise patch strategy that addresses ONLY the vulnerability. Follow these steps:

1. Analyze the provided information and code snippets.
2. Understand the intended behavior of the code.
3. Identify the exact lines of code that need to be modified to fix the vulnerability.
4. Determine the specific changes required to those lines.
5. Consider any dependencies or side effects that might affect the fix.
6. Ensure the fix directly addresses the root cause.

If you need additional information to develop your patch strategy, you can request new code snippets. For example, you might need:
- Code snippets defining functions referenced in the vulnerable code
- Type definitions used in the vulnerable code
- Context about how certain functions or variables are used

To request additional information, use the following format:
<request_information>
[Describe the specific code snippet or information you need and why it's necessary for developing the patch strategy]
</request_information>

Before providing your final patch strategy, wrap your reasoning process in <patch_development_process> tags. This should include:
- Relevant quotes from the root cause analysis and code snippets
- Your understanding of the code's intended behavior
- Analysis of the vulnerability, including potential vulnerability types
- Enumeration and evaluation of possible fix approaches
- Selection of the best approach with justification
- Reasoning about potential fixes and their implications

Once you have completed your analysis, provide your patch strategy in the following format:

<patch_strategy>
<full>
[Explain your proposed patch strategy in detail. It is ok for this section to be long. Include:
- The intended behavior of the code
- The exact lines of code that need to be modified
- The specific changes required to fix the vulnerability
- Any dependencies or side effects that need to be considered
- How these changes directly address the root cause]
</full>
<summary>[Short summary of the patch strategy, just one or two sentences, no more than 100 characters]</summary>
</patch_strategy>

Remember: Focus ONLY on fixing the specific vulnerability. Do not include:
- General security improvements
- Code style changes
- Test implementations
- Documentation updates
- Performance optimizations
- Any other changes not directly related to fixing the vulnerability
"""

PATCH_STRATEGY_PROMPT = ChatPromptTemplate.from_messages(
    [
        ("system", PATCH_STRATEGY_SYSTEM_MSG),
        ("user", PATCH_STRATEGY_USER_MSG),
        ("ai", "<patch_development_process>"),
    ]
)

REFLECTION_GUIDANCE_TMPL = """
You have received additional guidance on what to do next, you should follow it as much as possible.

<reflection_guidance>
{REFLECTION_GUIDANCE}
</reflection_guidance>
"""

PATCH_PROMPT = """
You previously tried the following patch, but it was not good enough.
When producing the patch, include these changes as well, because they are not applied.

<previous_patch>
<description>{description}</description>
<patch>{patch}</patch>
<status>{status}</status>
<failure_category>{failure_category}</failure_category>
<failure_analysis>{failure_analysis}</failure_analysis>
</previous_patch>
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

    @classmethod
    def parse(cls, msg: str) -> list[CodeSnippetChange]:
        # Extract file_path and identifier from the patch block
        file_path_match = re.search(r"<file_path>(.*?)</file_path>", msg, re.DOTALL | re.IGNORECASE)
        identifier_match = re.search(r"<identifier>(.*?)</identifier>", msg, re.DOTALL | re.IGNORECASE)

        if not identifier_match or not file_path_match:
            logger.warning("Missing identifier or file_path in patch block")
            return []

        identifier = identifier_match.group(1).strip()
        file_path = file_path_match.group(1).strip()

        # Find all old_code/new_code pairs in this patch block
        code_pairs_re = re.compile(
            r"<old_code>(.*?)</old_code>.*?<new_code>(.*?)</new_code>",
            re.DOTALL | re.IGNORECASE,
        )
        code_pairs = code_pairs_re.findall(msg)

        result: list[CodeSnippetChange] = []
        for old_code, new_code in code_pairs:
            result.append(
                cls(
                    key=CodeSnippetKey(file_path=file_path, identifier=identifier),
                    old_code=old_code.strip("\n"),
                    code=new_code.strip("\n"),
                )
            )

        return result


class CodeSnippetChanges(BaseModel):
    """Code snippet changes"""

    items: list[CodeSnippetChange] | None = Field(description="List of code snippet changes")

    @classmethod
    def parse(cls, msg: str) -> CodeSnippetChanges:
        """Parse the code snippet changes from the string."""
        # First, find all patch blocks
        patch_blocks_re = re.compile(
            r"<patch>(.*?)</patch>",
            re.DOTALL | re.IGNORECASE,
        )
        patch_blocks = patch_blocks_re.findall(msg)

        items: list[CodeSnippetChange] = []

        for patch_block in patch_blocks:
            items.extend(CodeSnippetChange.parse(patch_block))

        logger.debug("Parsed %d code snippets", len(items))
        return CodeSnippetChanges(items=items)


class CreateUPatchInput(BaseModel):
    """Input for the create_upatch function"""

    description: str | None = None
    code_snippets: CodeSnippetChanges
    state: PatcherAgentState


@dataclass
class SWEAgent(PatcherAgentBase):
    """Software Engineer LLM agent, handling the creation of patches."""

    default_llm: BaseChatOpenAI = field(init=False)
    llm: Runnable = field(init=False)
    create_patch_chain: Runnable = field(init=False)
    patch_strategy_chain: Runnable = field(init=False)

    MATCH_RATIO_THRESHOLD: float = 0.8

    def __post_init__(self) -> None:
        """Initialize a few fields"""
        self.default_llm = create_default_llm_with_temperature(model_name=ButtercupLLM.OPENAI_GPT_4O.value)
        fallback_llms: list[Runnable] = []
        for fb_model in [
            ButtercupLLM.CLAUDE_3_7_SONNET,
        ]:
            fallback_llms.append(create_default_llm_with_temperature(model_name=fb_model.value))
        self.llm = self.default_llm.with_fallbacks(fallback_llms)

        self.code_snippets_chain = PROMPT | self.llm | StrOutputParser()
        self.patch_strategy_chain = PATCH_STRATEGY_PROMPT | self.llm | StrOutputParser()

    def _parse_description(self, patch_str: str) -> str | None:
        """Parse the description from the patch string."""
        match = re.search(r"<description>(.*?)</description>", patch_str, re.DOTALL | re.IGNORECASE)
        if match is None:
            return None

        return match.group(1).strip()

    def _get_file_content(self, file_path: str) -> tuple[str, Path] | None:
        """Get the content of a file, trying multiple search strategies. Returns
        the content of the file and the relative path of the file (from the
        source path)."""
        file_path = file_path.strip()
        relative_file_path = find_file_in_source_dir(self.challenge, Path(file_path))
        if relative_file_path is None:
            return None

        try:
            file_content = self.challenge.get_source_path().joinpath(relative_file_path).read_text()
            return str(file_content), relative_file_path
        except FileNotFoundError:
            return None

    def _find_closest_match(
        self, orig_code_snippets: dict[CodeSnippetKey, str], target_key: CodeSnippetKey
    ) -> CodeSnippetKey | None:
        """Find the closest matching CodeSnippetKey in orig_code_snippets."""

        def sequence_ratio(x: CodeSnippetKey) -> float:
            return difflib.SequenceMatcher(None, str(target_key.file_path), str(x.file_path)).ratio()

        if not orig_code_snippets:
            return None

        # Try exact identifier match with fuzzy file path
        matches = [key for key in orig_code_snippets.keys() if key.identifier == target_key.identifier]
        if matches:
            # If there is only one match, just return it
            if len(matches) == 1:
                return matches[0]

            # Find best file path match among matches
            best_match = max(matches, key=sequence_ratio)
            match_ratio = sequence_ratio(best_match)
            if match_ratio > self.MATCH_RATIO_THRESHOLD:
                return best_match

        # If no good match found with identifier, just return so,
        # we'll ask for the code snippet
        return None

    def _get_code_snippet_key(
        self, code_snippet: CodeSnippetChange, orig_code_snippets: dict[CodeSnippetKey, str]
    ) -> CodeSnippetKey | None:
        code_snippet_key = code_snippet.key
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

    def _get_snippets_patch(
        self, code_snippet: CodeSnippetChange, idx: int, orig_code_snippets: dict[CodeSnippetKey, str]
    ) -> PatchOutput | None:
        if not code_snippet.is_valid():
            logger.warning("Invalid code snippet: %s (%d)", code_snippet.key, idx)
            return None

        code_snippet_key = self._get_code_snippet_key(code_snippet, orig_code_snippets)
        if not code_snippet_key:
            logger.warning("Could not find a valid code snippet key for %s (%d)", code_snippet.key, idx)
            return None

        assert code_snippet_key.file_path, "Code snippet key file path is empty"
        get_file_content_result = self._get_file_content(code_snippet_key.file_path)
        if get_file_content_result is None:
            logger.warning("Could not read the file: %s", code_snippet_key.file_path)
            return None

        file_content, file_path = get_file_content_result
        orig_file_content = file_content
        orig_code_snippet = orig_code_snippets[code_snippet_key]
        if orig_code_snippet not in file_content:
            logger.warning(
                "Could not generate a valid patch for %s (%d), original code snippet not found in the file",
                code_snippet_key,
                idx,
            )
            return None

        assert code_snippet.old_code, "The code snippet should be validated before, old_code should be present"
        assert code_snippet.code, "The code snippet should be validated before, code should be present"
        if code_snippet.old_code not in orig_code_snippet:
            # TODO: use some fuzzy matching to try to apply the patch anyway
            logger.warning(
                "Could not generate a valid patch for %s (%d), old code snippet change not found in the original code snippet",
                code_snippet_key,
                idx,
            )
            return None

        new_code_snippet = orig_code_snippet.replace(code_snippet.old_code, code_snippet.code)
        file_content = file_content.replace(orig_code_snippet, new_code_snippet)

        patch = difflib.unified_diff(
            orig_file_content.splitlines(),
            file_content.splitlines(),
            lineterm="",
            fromfile="a/" + str(file_path),
            tofile="b/" + str(file_path),
        )
        patch_str = "\n".join(patch) + "\n"
        if not patch_str.strip():
            logger.warning(
                "Could not generate a valid patch for %s (%d)",
                code_snippet_key,
                idx,
            )
            return None

        logger.debug("Generated patch for %s (%d)", code_snippet_key, idx)
        return PatchOutput(
            task_id=self.input.task_id,
            submission_index=self.input.submission_index,
            patch=patch_str,
        )

    def _get_snippets_patches(
        self, code_snippets: CodeSnippetChanges, orig_code_snippets: dict[CodeSnippetKey, str]
    ) -> list[PatchOutput]:
        patches: list[PatchOutput] = []
        for code_snippet_idx, code_snippet in enumerate(code_snippets.items or []):
            patch_output = self._get_snippets_patch(code_snippet, code_snippet_idx, orig_code_snippets)
            if not patch_output:
                continue

            patches.append(patch_output)

        return patches

    def create_upatch(self, state: PatcherAgentState, code_snippet_changes: CodeSnippetChanges) -> PatchOutput | None:
        """Extract the patch the new vulnerable code."""
        orig_code_snippets = {
            cs.key: cs.code for cs in state.relevant_code_snippets if cs.code and cs.key.file_path and cs.key.identifier
        }

        logger.debug("Creating patches for %d code snippets", len(code_snippet_changes.items or []))
        patches = self._get_snippets_patches(code_snippet_changes, orig_code_snippets)
        if not patches:
            logger.error("No valid patches generated")
            return None

        # Concatenate all patches in one
        logger.debug("Concatenating %d patches", len(patches))
        patch_content = "\n".join(p.patch for p in patches)
        final_patch = PatchOutput(
            task_id=self.input.task_id,
            submission_index=self.input.submission_index,
            patch=patch_content,
        )
        return final_patch

    def create_patch_node(
        self, state: PatcherAgentState, config: RunnableConfig
    ) -> Command[  # type: ignore[name-defined]
        Literal[
            PatcherAgentName.BUILD_PATCH.value,
            PatcherAgentName.REFLECTION.value,
        ]
    ]:
        """Node in the LangGraph that generates a patch (in diff format)"""
        logger.info(
            "[%s / %s] Creating a patch for Challenge Task %s",
            state.context.task_id,
            state.context.submission_index,
            self.challenge.name,
        )
        if not state.patch_strategy:
            raise ValueError("No patch strategy found, you should select a patch strategy first")

        execution_info = state.execution_info
        execution_info.prev_node = PatcherAgentName.CREATE_PATCH

        previous_patch_prompt = ""
        last_patch_attempt = state.get_last_patch_attempt()
        if last_patch_attempt and last_patch_attempt.analysis and last_patch_attempt.analysis.partial_success:
            previous_patch_prompt = PATCH_PROMPT.format(
                description=last_patch_attempt.description,
                patch=last_patch_attempt.patch.patch if last_patch_attempt.patch else "",
                status=last_patch_attempt.status,
                failure_category=last_patch_attempt.analysis.failure_category if last_patch_attempt.analysis else "",
                failure_analysis=last_patch_attempt.analysis.failure_analysis if last_patch_attempt.analysis else "",
            )

        patch_str: str = self.chain_call(
            lambda x, y: x + y,
            self.code_snippets_chain,
            {
                "PROJECT_NAME": self.challenge.name,
                "ROOT_CAUSE_ANALYSIS": str(state.root_cause),
                "CODE_SNIPPETS": "\n".join(map(str, state.relevant_code_snippets)),
                "PATCH_STRATEGY": state.patch_strategy.full,
                "PREVIOUS_PATCH_PROMPT": previous_patch_prompt,
                "REFLECTION_GUIDANCE": REFLECTION_GUIDANCE_TMPL.format(
                    REFLECTION_GUIDANCE=state.execution_info.reflection_guidance
                )
                if state.execution_info.reflection_decision == PatcherAgentName.CREATE_PATCH
                else "",
            },
            default="",  # type: ignore[call-arg]
            config=RunnableConfig(
                configurable={
                    "llm_temperature": pick_temperature(),
                },
            ),
        )
        code_snippet_changes = CodeSnippetChanges.parse(patch_str)
        new_patch_attempt = PatchAttempt(
            patch=self.create_upatch(state, code_snippet_changes),
            description=self._parse_description(patch_str),
            patch_str=patch_str,
            strategy=state.patch_strategy.summary,
        )
        if not new_patch_attempt.patch or not new_patch_attempt.patch.patch:
            logger.error("Could not generate a patch")
            new_patch_attempt.status = PatchStatus.CREATION_FAILED
            return Command(
                update={
                    "patch_attempts": new_patch_attempt,
                    "execution_info": execution_info,
                },
                goto=PatcherAgentName.REFLECTION.value,
            )

        logger.info(
            "[%s / %s] Generated a patch for Challenge Task %s",
            state.context.task_id,
            state.context.submission_index,
            self.challenge.name,
        )
        logger.debug("Patch attempt description: %s", new_patch_attempt.description)
        logger.debug("Patch attempt: %s", new_patch_attempt.patch.patch)
        if new_patch_attempt.patch.patch in [p.patch.patch for p in state.patch_attempts if p.patch]:
            logger.warning(
                "[%s / %s] Generated patch already exists", state.context.task_id, state.context.submission_index
            )
            new_patch_attempt.status = PatchStatus.DUPLICATED
            return Command(
                update={
                    "patch_attempts": new_patch_attempt,
                    "execution_info": execution_info,
                },
                goto=PatcherAgentName.REFLECTION.value,
            )

        return Command(
            update={
                "patch_attempts": new_patch_attempt,
            },
            goto=PatcherAgentName.BUILD_PATCH.value,
        )

    def _parse_code_snippet_requests(self, patch_strategy_str: str) -> list[CodeSnippetRequest]:
        """Parse the code snippet requests from the patch strategy string."""
        requests = []
        for request in re.findall(
            r"<request_information>(.*?)</request_information>", patch_strategy_str, re.DOTALL | re.IGNORECASE
        ):
            requests.append(CodeSnippetRequest(request=request))
        return requests

    def _parse_patch_strategy(self, patch_strategy_str: str) -> PatchStrategy:
        """Parse the patch strategy from the patch strategy string."""
        # Extract content between <patch_strategy> tags
        if "<patch_strategy>" not in patch_strategy_str:
            return PatchStrategy(full=patch_strategy_str)

        if "</patch_strategy>" not in patch_strategy_str:
            patch_strategy_str += "</patch_strategy>"

        start = patch_strategy_str.find("<patch_strategy>") + len("<patch_strategy>")
        end = patch_strategy_str.find("</patch_strategy>")
        strategy = patch_strategy_str[start:end].strip()

        # Extract each field
        def extract_field(field: str) -> str | list[str] | None:
            start_tag = f"<{field}>"
            end_tag = f"</{field}>"
            start = strategy.find(start_tag) + len(start_tag)
            end = strategy.find(end_tag)
            if start == -1 or end == -1:
                return None
            content = strategy[start:end].strip()
            if not content:
                return None
            return content

        return PatchStrategy(
            full=extract_field("full"),
            summary=extract_field("summary"),
        )

    def select_patch_strategy(
        self, state: PatcherAgentState, config: RunnableConfig
    ) -> Command[  # type: ignore[name-defined]
        Literal[
            PatcherAgentName.CREATE_PATCH.value,
            PatcherAgentName.REFLECTION.value,
        ]
    ]:
        logger.info(
            "[%s / %s] Selecting a patch strategy for Challenge Task %s",
            state.context.task_id,
            state.context.submission_index,
            self.challenge.name,
        )

        execution_info = state.execution_info
        execution_info.prev_node = PatcherAgentName.PATCH_STRATEGY

        patch_strategy_str = self.patch_strategy_chain.invoke(
            {
                "PROJECT_NAME": self.challenge.name,
                "ROOT_CAUSE_ANALYSIS": str(state.root_cause),
                "CODE_SNIPPETS": "\n".join(map(str, state.relevant_code_snippets)),
                "REFLECTION_GUIDANCE": REFLECTION_GUIDANCE_TMPL.format(
                    REFLECTION_GUIDANCE=state.execution_info.reflection_guidance
                )
                if state.execution_info.reflection_decision == PatcherAgentName.PATCH_STRATEGY
                else "",
            },
            default="",
            config=RunnableConfig(
                configurable={
                    "llm_temperature": pick_temperature(),
                },
            ),
        )
        if "<request_information>" in patch_strategy_str:
            new_code_snippet_requests = self._parse_code_snippet_requests(patch_strategy_str)
            logger.info(
                "[%s / %s] Requesting additional information", state.context.task_id, state.context.submission_index
            )
            return Command(
                update={
                    "execution_info": execution_info,
                    "code_snippet_requests": new_code_snippet_requests,
                },
                goto=PatcherAgentName.REFLECTION.value,
            )

        patch_strategy = self._parse_patch_strategy(patch_strategy_str)
        if not patch_strategy or not patch_strategy.full:
            logger.warning("No patch strategy found in response")
            return Command(
                update={
                    "execution_info": execution_info,
                },
                goto=PatcherAgentName.REFLECTION.value,
            )

        return Command(
            update={
                "patch_strategy": patch_strategy,
            },
            goto=PatcherAgentName.CREATE_PATCH.value,
        )
