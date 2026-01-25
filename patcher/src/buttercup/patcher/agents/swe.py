"""Software Engineer LLM agent, handling the creation of patches."""

from __future__ import annotations

import difflib
import logging
import re
import subprocess
import tempfile
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated, Literal

import langgraph.errors
from langchain_core.messages import BaseMessage
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import (
    ChatPromptTemplate,
    MessagesPlaceholder,
)
from langchain_core.runnables import (
    Runnable,
    RunnableConfig,
)
from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState, create_react_agent
from langgraph.types import Command
from pydantic import BaseModel, Field, ValidationError

from buttercup.common.llm import ButtercupLLM, create_default_llm_with_temperature
from buttercup.patcher.agents.common import (
    CodeSnippetKey,
    CodeSnippetRequest,
    PatchAttempt,
    PatcherAgentBase,
    PatcherAgentName,
    PatcherAgentState,
    PatchStatus,
    PatchStrategy,
)
from buttercup.patcher.utils import PatchOutput, find_file_in_source_dir, pick_temperature

# ruff: noqa: E501

logger = logging.getLogger(__name__)

SYSTEM_MSG = (
    """You are a skilled software engineer tasked with generating a patch for a specific vulnerability in a project."""
)
USER_MSG = """Your goal is to fix only the described vulnerability without making any unrelated changes or improvements to the code.

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

Patch strategy:
<patch_strategy>
{PATCH_STRATEGY}
</patch_strategy>

{PREVIOUS_PATCH_PROMPT}
{REFLECTION_GUIDANCE}

Instructions:

1. Analyze the vulnerability and plan your approach:
   Wrap your patch planning inside <patch_planning> tags. Focus on implementing the provided patch strategy rather than performing a deep analysis. Include the following steps:
   a. List the vulnerable code parts identified in the root cause analysis.
   b. Map each vulnerable part to the corresponding code snippet, including specific line numbers where possible.
   c. Outline the specific changes needed for each vulnerable part, based on the patch strategy.
   d. Develop a step-by-step approach for implementing the patch.

2. Describe the changes:
   Provide a clear explanation of the changes you intend to make and why. Use <description> tags for this section.

3. Generate the patch:
   Based on your analysis, create the necessary code changes. Remember:
   - Only fix the described vulnerability.
   - Modify one or more code snippets as needed.
   - You don't have to modify all code snippets.
   - Only output snippets you have modified.
   - Use only code that you know is present in the codebase.
   - Modify only code snippets that have <can_patch>true</can_patch>.
   - Do not include placeholders or TODOs; suggest only exact code changes.

4. Format your output as follows for each modified code snippet:

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

Remember to focus solely on fixing the described vulnerability. Do not make any unrelated changes or improvements to the code. Begin your patch planning and solution development now.
"""

PROMPT = ChatPromptTemplate.from_messages(
    [
        ("system", SYSTEM_MSG),
        ("user", USER_MSG),
        ("ai", "<patch_planning>"),
    ],
)

PATCH_STRATEGY_SYSTEM_MSG = """You are PatchGen-LLM, an autonomous component in an end-to-end security-patching pipeline.
Goal: design a precise, minimal patch strategy that eliminates ONLY the vulnerabilities described in the Root-Cause-Analysis (RCA).
The strategy you output will be consumed by a downstream code-generation agent, so factual and structural accuracy are critical."""

PATCH_STRATEGY_USER_MSG = """INPUT SECTIONS:
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

---

TOOLS:
• understand_code_snippet
  Use this tool whenever you need clarification about how a given snippet works.

OUTPUT FORMAT (MANDATORY)
<patch_development_process>
   a. List 2-4 alternative mitigation ideas, each with pros/cons.
   b. Identify your selected approach and justify why it is the best trade-off. \
Prefer the simplest (but sound) approaches first, if not instructed \
otherwise. For example, you could try reverting the patch that introduced the \
issue, if available, or validate the inputs before using them.
   c. Reference line numbers / function names from <code_snippets> as needed.
</patch_development_process>
<full_description>
   A thourough, detailed and complete description of the chosen patch strategy written for another LLM that will implement it.
</full_description>

REQUESTING MORE INFORMATION
If you need additional code or context, request it ONLY in this form:

```xml
<request_information>
[Describe exactly what you need and why.]
</request_information>
```

POLICIES (hard constraints)

1. Scope:
   - Fix the vulnerabilities in the RCA only—nothing else
   - No stylistic, performance, refactor, or documentation changes
   - Do not propose test cases or broad hardening.
   - Only code snippets with <can_patch>true</can_patch> can be modified
   - Fix the actual project code, not the testing/fuzzing code.
2. Content:
   - Do NOT output code diffs or concrete code; output strategy only.
3. Structure:
   - Use the exact tags and ordering shown in “OUTPUT FORMAT”.

Begin when ready.
"""

PATCH_STRATEGY_PROMPT = ChatPromptTemplate.from_messages(
    [
        ("system", PATCH_STRATEGY_SYSTEM_MSG),
        ("user", PATCH_STRATEGY_USER_MSG),
        MessagesPlaceholder(variable_name="messages"),
        ("ai", "<patch_development_process>"),
    ],
)

REFLECTION_GUIDANCE_TMPL = """
You have received additional guidance on what to do next, you should follow it as much as possible.

<reflection_guidance>
{REFLECTION_GUIDANCE}
</reflection_guidance>
"""

PATCH_PROMPT = """
You previously tried the following patch, but it was not good enough.
Please incorporate these changes into your new patch proposal, as they still need to be implemented.
Do not just copy the previous patch, but use the previous patch as a reference to generate a new patch.

<previous_patch>
<description>{description}</description>
<patch>
{patch}
</patch>
<status>{status}</status>
<failure_category>{failure_category}</failure_category>
<failure_analysis>{failure_analysis}</failure_analysis>
</previous_patch>
"""

SUMMARIZE_PATCH_STRATEGY_PROMPT = ChatPromptTemplate.from_messages(
    [
        ("system", "You are a helpful assistant that summarizes a patch strategy."),
        (
            "user",
            """Summarize the following patch strategy in 1-2 sentences at most. Produce only the summary, no other text:
<patch_strategy>
{patch_strategy}
</patch_strategy>
""",
        ),
    ],
)


class CodeSnippetChange(BaseModel):
    """Code snippet change"""

    key: CodeSnippetKey = Field(description="The key of the code snippet")
    old_code: str | None = Field(
        None,
        description="The old piece of code, as-is, with spaces, trailing/leading whitespaces, etc.",
    )
    code: str | None = Field(
        None,
        description="The fixed piece of code snippet, as-is, with spaces, trailing/leading whitespaces, etc.",
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
                ),
            )

        return result


class CodeSnippetChanges(BaseModel):
    """Code snippet changes"""

    items: list[CodeSnippetChange] | None = Field(None, description="List of code snippet changes")

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

    default_llm: Runnable = field(init=False)
    llm: Runnable = field(init=False)
    create_patch_chain: Runnable = field(init=False)
    patch_strategy_chain: Runnable = field(init=False)

    MATCH_RATIO_THRESHOLD: float = 0.8

    def __post_init__(self) -> None:
        """Initialize a few fields"""

        @tool(description=self._understand_code_snippet.__doc__)
        def understand_code_snippet(
            code_snippet_id: str,
            focus_area: str,
            *,
            state: Annotated[BaseModel, InjectedState],
        ) -> str:
            assert isinstance(state, PatcherAgentState)
            return self._understand_code_snippet(state, code_snippet_id, focus_area)

        kwargs = {
            "temperature": 1,
            "max_tokens": 20000,
        }
        self.default_llm = create_default_llm_with_temperature(
            model_name=ButtercupLLM.OPENAI_GPT_4_1.value,
            **kwargs,
        )
        fallback_llms: list[Runnable] = []
        for fb_model in [
            ButtercupLLM.CLAUDE_3_7_SONNET,
            ButtercupLLM.GEMINI_PRO,
        ]:
            fallback_llms.append(create_default_llm_with_temperature(model_name=fb_model.value, **kwargs))
        self.llm = self.default_llm.with_fallbacks(fallback_llms)

        self.code_snippets_chain = PROMPT | self.llm | StrOutputParser()

        tools = [
            understand_code_snippet,
        ]
        default_strategy_agent = create_react_agent(
            model=self.default_llm,
            state_schema=PatcherAgentState,
            tools=tools,
            prompt=self._patch_strategy_prompt,
        )
        fallback_strategy_agents = [
            create_react_agent(
                model=llm,
                state_schema=PatcherAgentState,
                tools=tools,
                prompt=self._patch_strategy_prompt,
            )
            for llm in fallback_llms
        ]
        self.patch_strategy_chain = default_strategy_agent.with_fallbacks(fallback_strategy_agents)
        self.patch_strategy_summary_chain = SUMMARIZE_PATCH_STRATEGY_PROMPT | self.llm | StrOutputParser()

    def _patch_strategy_prompt(self, state: PatcherAgentState) -> list[BaseMessage]:
        return PATCH_STRATEGY_PROMPT.format_messages(
            PROJECT_NAME=self.challenge.name,
            ROOT_CAUSE_ANALYSIS=str(state.root_cause),
            CODE_SNIPPETS="\n".join(map(str, state.relevant_code_snippets)),
            REFLECTION_GUIDANCE=REFLECTION_GUIDANCE_TMPL.format(
                REFLECTION_GUIDANCE=state.execution_info.reflection_guidance,
            )
            if state.execution_info.reflection_decision == PatcherAgentName.PATCH_STRATEGY
            else "",
            messages=state.messages,
        )

    def _parse_description(self, patch_str: str) -> str | None:
        """Parse the description from the patch string."""
        match = re.search(r"<description>(.*?)</description>", patch_str, re.DOTALL | re.IGNORECASE)
        if match is None:
            return None

        return match.group(1).strip()

    def _get_file_content(self, file_path: str) -> tuple[str, Path] | None:
        """Get the content of a file, trying multiple search strategies. Returns
        the content of the file and the relative path of the file (from the
        source path).
        """
        file_path = file_path.strip()
        relative_file_path = find_file_in_source_dir(self.challenge, Path(file_path))
        if relative_file_path is None:
            return None

        try:
            file_content = self.challenge.get_source_path().joinpath(relative_file_path).read_text()
            return str(file_content), relative_file_path
        except FileNotFoundError:
            logger.warning("_get_file_content: File %s(%s) not found", file_path, relative_file_path)
            return None
        except Exception:
            logger.exception("_get_file_content: Error reading file %s(%s)", file_path, relative_file_path)
            return None

    def _find_closest_match(
        self,
        orig_code_snippets: dict[CodeSnippetKey, str],
        target_key: CodeSnippetKey,
    ) -> CodeSnippetKey | None:
        """Find the closest matching CodeSnippetKey in orig_code_snippets."""

        def sequence_ratio(x: CodeSnippetKey) -> float:
            return difflib.SequenceMatcher(None, str(target_key.file_path), str(x.file_path)).ratio()

        if not orig_code_snippets:
            return None

        # Try exact identifier match with fuzzy file path
        matches = [key for key in orig_code_snippets if key.identifier == target_key.identifier]
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
        self,
        code_snippet: CodeSnippetChange,
        orig_code_snippets: dict[CodeSnippetKey, str],
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
        self,
        code_snippet: CodeSnippetChange,
        idx: int,
        orig_code_snippets: dict[CodeSnippetKey, str],
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

        # Use git diff to generate the patch properly
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_dir_path = Path(temp_dir)

            # Create temporary files for comparison
            orig_file = temp_dir_path / "orig"
            new_file = temp_dir_path / "new"
            orig_file.write_text(orig_file_content)
            new_file.write_text(file_content)

            # Run git diff to generate the patch
            try:
                result = subprocess.run(
                    ["git", "diff", "--no-index", "--binary", str(orig_file.name), str(new_file.name)],
                    check=False,
                    capture_output=True,
                    text=True,
                    cwd=temp_dir_path,
                    timeout=30,
                )

                patch_str = result.stdout
                patch_str = patch_str.replace(f"a/{orig_file.name}", f"a/{file_path}")
                patch_str = patch_str.replace(f"b/{new_file.name}", f"b/{file_path}")
            except (subprocess.TimeoutExpired, subprocess.CalledProcessError, FileNotFoundError) as e:
                logger.warning("git diff failed: %s", e)
                return None

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
            internal_patch_id=self.input.internal_patch_id,
            patch=patch_str,
        )

    def _get_snippets_patches(
        self,
        code_snippets: CodeSnippetChanges,
        orig_code_snippets: dict[CodeSnippetKey, str],
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
            internal_patch_id=self.input.internal_patch_id,
            patch=patch_content,
        )
        return final_patch

    def create_patch_node(
        self,
        state: PatcherAgentState,
        config: RunnableConfig,
    ) -> Command[Literal["reflection", "build_patch"]]:
        """Node in the LangGraph that generates a patch (in diff format)"""
        logger.info(
            "[%s / %s] Creating a patch for Challenge Task %s",
            state.context.task_id,
            state.context.internal_patch_id,
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

        patch_str: str = self.chain_call(  # type: ignore[missing-argument,unknown-argument]
            lambda x, y: x + y,
            self.code_snippets_chain,
            {
                "PROJECT_NAME": self.challenge.name,
                "ROOT_CAUSE_ANALYSIS": str(state.root_cause),
                "CODE_SNIPPETS": "\n".join(map(str, state.relevant_code_snippets)),
                "PATCH_STRATEGY": state.patch_strategy.full,
                "PREVIOUS_PATCH_PROMPT": previous_patch_prompt,
                "REFLECTION_GUIDANCE": REFLECTION_GUIDANCE_TMPL.format(
                    REFLECTION_GUIDANCE=state.execution_info.reflection_guidance,
                )
                if state.execution_info.reflection_decision == PatcherAgentName.CREATE_PATCH
                else "",
            },
            default="",  # type: ignore[unknown-argument]
            config=RunnableConfig(  # type: ignore[unknown-argument]
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
            state.context.internal_patch_id,
            self.challenge.name,
        )
        logger.debug("Patch attempt description: %s", new_patch_attempt.description)
        logger.debug("Patch attempt: %s", new_patch_attempt.patch.patch)
        if new_patch_attempt.patch.patch in [p.patch.patch for p in state.patch_attempts if p.patch]:
            logger.warning(
                "[%s / %s] Generated patch already exists",
                state.context.task_id,
                state.context.internal_patch_id,
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
            r"<request_information>(.*?)</request_information>",
            patch_strategy_str,
            re.DOTALL | re.IGNORECASE,
        ):
            requests.append(CodeSnippetRequest(request=request))
        return requests

    def _parse_patch_strategy(self, patch_strategy_str: str) -> PatchStrategy:
        """Parse the patch strategy from the patch strategy string."""
        strategy = patch_strategy_str

        # Extract each field
        def extract_field(field: str) -> str | None:
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

        res = PatchStrategy(
            full=extract_field("full_description"),
            summary=extract_field("summary"),
        )
        if res.full is None:
            res.full = strategy
        if res.summary is None:
            res.summary = res.full

        return res

    def select_patch_strategy(
        self,
        state: PatcherAgentState,
        config: RunnableConfig,
    ) -> Command[Literal["create_patch", "reflection"]]:
        logger.info(
            "[%s / %s] Selecting a patch strategy for Challenge Task %s",
            state.context.task_id,
            state.context.internal_patch_id,
            self.challenge.name,
        )

        execution_info = state.execution_info
        execution_info.prev_node = PatcherAgentName.PATCH_STRATEGY

        configurable = {
            "thread_id": str(uuid.uuid4()),
        }
        try:
            strategy_state_dict = self.patch_strategy_chain.invoke(
                state,
                config=RunnableConfig(
                    configurable=configurable,
                ),
            )
        except langgraph.errors.GraphRecursionError:
            logger.error(
                "Reached recursion limit for patch strategy in Challenge Task %s/%s",
                state.context.task_id,
                self.challenge.name,
            )
            return Command(
                update={
                    "execution_info": execution_info,
                },
                goto=PatcherAgentName.REFLECTION.value,
            )

        try:
            strategy_state = PatcherAgentState.model_validate(strategy_state_dict)
        except ValidationError as e:
            logger.error("Invalid state dict for patch strategy: %s", e)
            return Command(
                update={
                    "execution_info": execution_info,
                },
                goto=PatcherAgentName.REFLECTION.value,
            )

        if not strategy_state or not strategy_state.messages:
            logger.error("No messages returned from the patch strategy chain")
            return Command(
                update={
                    "execution_info": execution_info,
                },
                goto=PatcherAgentName.REFLECTION.value,
            )

        patch_strategy_str = str(strategy_state.messages[-1].content)
        if "<request_information>" in patch_strategy_str:
            new_code_snippet_requests = self._parse_code_snippet_requests(patch_strategy_str)
            execution_info.code_snippet_requests = new_code_snippet_requests
            logger.info(
                "[%s / %s] Requesting additional information",
                state.context.task_id,
                state.context.internal_patch_id,
            )
            return Command(
                update={
                    "execution_info": execution_info,
                },
                goto=PatcherAgentName.REFLECTION.value,
            )

        patch_strategy = self._parse_patch_strategy(patch_strategy_str)
        try:
            new_summary = self.patch_strategy_summary_chain.invoke(
                {
                    "patch_strategy": patch_strategy.full,
                },
            )
            if new_summary:
                patch_strategy.summary = new_summary
        except Exception as e:
            logger.error("Error parsing patch strategy summary: %s", e)
            patch_strategy.summary = patch_strategy.full

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
