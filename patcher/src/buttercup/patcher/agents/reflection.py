"""Reflection LLM agent, handling the reflection on the patch (e.g. why the
patch is not working, what can be done to fix it, etc.)"""

from __future__ import annotations

import logging
from itertools import groupby
from pydantic import BaseModel, Field
from langchain_core.output_parsers import StrOutputParser
from buttercup.patcher.utils import decode_bytes
from dataclasses import dataclass, field
from langgraph.constants import END
from langgraph.types import Command
from typing import Literal
from langchain_core.runnables import (
    Runnable,
    RunnableConfig,
)
from buttercup.patcher.agents.common import (
    PatcherAgentState,
    PatcherAgentName,
    PatcherAgentBase,
    PatchStatus,
    PatchAttempt,
    CodeSnippetRequest,
    PatchAnalysis,
)
from buttercup.patcher.agents.config import PatcherConfig
from buttercup.common.llm import ButtercupLLM, create_default_llm
from langchain_core.prompts import (
    ChatPromptTemplate,
)

logger = logging.getLogger(__name__)

SYSTEM_MSG = """You are the Reflection Engine in an autonomous vulnerability patching system."""

REFLECTION_PROMPT = """Your primary task is to analyze why a patch failed and determine the best next steps to unblock other agents in the system.

First, carefully review the following information about the failed patch attempt:

<root_cause_analysis>
{ROOT_CAUSE_ANALYSIS}
</root_cause_analysis>

<code_snippets>
{CODE_SNIPPETS}
</code_snippets>

<previous_attempts>
{PREVIOUS_ATTEMPTS}
</previous_attempts>

Now, analyze the specific failure information:

<last_patch_attempt>
{LAST_PATCH_ATTEMPT}
</last_patch_attempt>

<failure_analysis>
<failure_type>{FAILURE_TYPE}</failure_type>
<failure_data>
{FAILURE_DATA}
</failure_data>
</failure_analysis>

Additional context:
<extra_information>
{EXTRA_INFORMATION}
</extra_information>

Your task is to analyze the provided information and determine:
1. The specific reason the patch failed
2. Which category the failure falls into
3. What improvements could be made to the vulnerability fix
4. Whether the patch shows partial success
5. Any patterns identified across multiple failed attempts
6. What component should handle the next step and why

To ensure a thorough and transparent reflection process, work through your analysis in <analysis_breakdown> tags inside your thinking block. Follow these steps:

1. Summarize key points from each input section (last patch attempt, root cause analysis, code snippets, previous attempts, failure analysis, extra information).
2. Extract and quote relevant information from each input section for each point of analysis.
3. For the failure category, consider arguments for each possible category: incomplete_fix, wrong_approach, misunderstood_root_cause, missing_code_snippet, build_error, regression_issue
4. Rate the likelihood of each failure category on a scale of 1-5.
5. List at least 3 potential improvements for the vulnerability fix. Focus ONLY on security-related improvements, such as:
   - Adding missing security checks
   - Fixing incorrect security checks
   - Improving input validation
   - Fixing memory safety issues
   - Addressing race conditions
   - Fixing access control issues
6. Create a numbered list of patterns across multiple failed attempts. Look for similarities in code, error messages, and approach.
7. For the next component, consider pros and cons for each available component.
8. Rate each component's suitability on a scale of 1-5.
9. Carefully consider if the next component might need additional information, and if so list the information needed. In that case, the next component should be the context_retriever.
10. If multiple previous attempts were redirected to the same component (e.g., create_patch), consider to go back to an earlier component (e.g., root_cause_analysis) due to potential issues with the root cause analysis or patch strategy.

After your analysis, generate a structured reflection result using the following format:

<reflection_result>
<failure_reason>[Provide a detailed and specific reason for why the patch failed]</failure_reason>
<failure_category>[Choose one: incomplete_fix, wrong_approach, misunderstood_root_cause, missing_code_snippet, build_error, regression_issue]</failure_category>
<pattern_identified>[Describe any patterns seen across multiple failures, or state "No clear pattern identified" if none are apparent]</pattern_identified>
<next_component>[Select one of the available components listed below]</next_component>
<component_guidance>[Provide detailed, specific, actionable guidance for the selected component. This should be a concrete suggestion for the next step, detailed enough to unblock other agents in the system.]</component_guidance>
<partial_success>[True if the patch shows partial success, False if it is completely broken and should be discarded. If the next component guidance says to "improve the patch" or modify the patch in some way, then the patch is partially successful.]</partial_success>
</reflection_result>

The available components for the next step are:
<available_components>
{AVAILABLE_COMPONENTS}
</available_components>

Remember:
- Focus ONLY on fixing the security vulnerability
- Do NOT suggest adding tests, logging, or refactoring code
- Do NOT suggest improvements unrelated to the security vulnerability
- Your analysis and guidance should be thorough and specific enough to help unblock other agents in the autonomous patching system
- Try to provide first simpler guidance and only if those do not work, provide more complex guidance

Your final output should consist only of the structured reflection result and should not duplicate or rehash any of the work you did in the analysis breakdown.
"""

AVAILABLE_COMPONENT_TMPL = """- {name} - {description}"""

PATCH_ATTEMPT_TMPL = """<patch_attempt>
<id>{id}</id>
<description>{description}</description>
<patch>
{patch}
</patch>
<raw_patch_str>
{raw_patch_str}
</raw_patch_str>
<status>{status}</status>
</patch_attempt>
"""

PREVIOUS_PATCH_ATTEMPTS_TMPL = """<previous_patch_attempt>
<id>{id}</id>
<description>{description}</description>
<patch>{patch}</patch>
<status>{status}</status>
<partial_success>{partial_success}</partial_success>
<failure_analysis>{failure_analysis}</failure_analysis>
</previous_patch_attempt>
"""

PROMPT = ChatPromptTemplate.from_messages(
    [
        ("system", SYSTEM_MSG),
        ("user", REFLECTION_PROMPT),
        ("ai", "<analysis_breakdown>"),
    ]
)

CREATION_FAILED_FAILURE_DATA = """The patch generation component could not generate a \
patch. This means it produced a patch that could not be parsed, it provided an \
old_code snippet that does not match what was available, it \
tried to patch a snippet that was not found in the codebase, or \
similar."""

CREATION_FAILED_EXTRA_INFORMATION = """The last few patch attempts all failed \
because the patch generation component could not generate a patch. This means it \
produced a patch that could not be parsed, or it tried to patch a snippet that \
was not found in the codebase, or a similar error. Reflect on the patch from a \
broader perspective to understand what went wrong. Consider looking for new code \
snippets or re-evaluating the root cause analysis."""

DUPLICATED_FAILURE_DATA = """The patch is a duplicate of a previous patch \
attempt that was already tried, so it will not work either."""

DUPLICATED_EXTRA_INFORMATION = """The last few patch attempts all failed \
because the patch generation component produced a duplicate patch. This means \
it produced a patch that is identical to a previous patch attempt that was \
already tried. Reflect on the patch from a broader perspective to understand \
what went wrong. Consider looking for new code snippets or re-evaluating the \
root cause analysis."""

APPLY_FAILED_FAILURE_DATA = """The patch could not be applied to the codebase. \
This means that when doing `patch -p1 < patch.patch`, it returned an error."""

APPLY_FAILED_EXTRA_INFORMATION = """The last few patch attempts all failed \
because the patch could not be applied to the codebase. This means that when \
doing `patch -p1 < patch.patch`, it returned an error. Reflect on the patch from \
a broader perspective to understand what went wrong. Consider providing better \
information to the patch generation component."""

BUILD_FAILED_FAILURE_DATA = """The patch could not be applied to the codebase. \
This means it could not be parsed, or it tried to patch a snippet that was \
not found in the codebase, or similar.

Build failure stdout:
```
{build_stdout}
```

Build failure stderr:
```
{build_stderr}
```
"""

BUILD_FAILED_EXTRA_INFORMATION = """The last few patch attempts all failed \
because the patched code could not be compiled. Reflect on the patch from a \
broader perspective to understand what went wrong. Consider looking for new \
code snippets or providing better information to the patch generation component."""

POV_FAILED_FAILURE_DATA = """The patch did not fix the vulnerability.

POV stdout:
```
{pov_stdout}
```

POV stderr:
```
{pov_stderr}
```
"""

POV_FAILED_EXTRA_INFORMATION = """The last few patch attempts all failed \
because the patch did not fix the vulnerability. Reflect on the patch from a \
broader perspective to understand what went wrong. Consider looking for new code \
snippets that might be relevant for the vulnerability or re-evaluate the root \
cause analysis."""

TESTS_FAILED_FAILURE_DATA = """The patch did not pass the tests.

Tests stdout:
```
{tests_stdout}
```

Tests stderr:
```
{tests_stderr}
```
"""

TESTS_FAILED_EXTRA_INFORMATION = """The last few patch attempts all failed \
because the patch did not pass the tests. Reflect on the patch from a broader \
perspective to understand what went wrong. Consider providing better information \
to the patch generation component or re-evaluate the patch strategy used."""

CODE_SNIPPET_SUMMARY_TMPL = """<code_snippet>
<identifier>{identifier}</identifier>
<file_path>{file_path}</file_path>
<description>{description}</description>
<start_line>{start_line}</start_line>
<end_line>{end_line}</end_line>
</code_snippet>"""


class ReflectionResult(BaseModel):
    """Reflection result"""

    failure_reason: str | None = Field(description="Specific reason the patch failed")
    failure_category: (
        Literal[
            "incomplete_fix",
            "wrong_approach",
            "misunderstood_root_cause",
            "missing_code_snippet",
            "build_error",
            "regression_issue",
        ]
        | None
    ) = Field(
        description="One of [incomplete_fix, wrong_approach, misunderstood_root_cause, missing_code_snippet, build_error, regression_issue]",
        default=None,
    )
    pattern_identified: str | None = Field(description="Any pattern seen across multiple failures", default=None)
    next_component: PatcherAgentName = Field(
        description="One of available components", default=PatcherAgentName.ROOT_CAUSE_ANALYSIS
    )
    component_guidance: str | None = Field(
        description="Specific guidance for the selected component. This should be a concrete suggestion for the next step. Be specific and detailed.",
        default=None,
    )
    partial_success: bool | None = Field(
        description="Whether the patch shows partial success",
        default=None,
    )


@dataclass
class ReflectionAgent(PatcherAgentBase):
    """Reflection LLM agent, handling the reflection on the patch (e.g. why the
    patch is not working, what can be done to fix it, etc.)"""

    llm: Runnable = field(init=False)

    def __post_init__(self) -> None:
        """Initialize a few fields"""
        default_llm = create_default_llm(model_name=ButtercupLLM.OPENAI_GPT_4O.value)
        fallback_llms: list[Runnable] = []
        for fb_model in [
            ButtercupLLM.CLAUDE_3_7_SONNET,
        ]:
            fallback_llms.append(create_default_llm(model_name=fb_model.value))

        self.llm = default_llm.with_fallbacks(fallback_llms)
        self.reflection_chain = PROMPT | self.llm | StrOutputParser() | self._parse_reflection_result
        self.components = [
            (
                PatcherAgentName.CREATE_PATCH.value,
                "Given the root cause analysis, it defines a patching strategy and tries to create a patch for the available code snippets. Provide clear guidance on how to improve the patch creation.",
            ),
            (
                PatcherAgentName.ROOT_CAUSE_ANALYSIS.value,
                "Re-analyze the root cause of the vulnerability given the provided code snippets and the previous patch attempts. Provide clear guidance on how to improve the root cause analysis.",
            ),
            (
                PatcherAgentName.CONTEXT_RETRIEVER.value,
                "Retrieve additional code snippets that might be necessary to understand the root cause or to create a patch. Provide clear guidance on what exactly to retrieve.",
            ),
        ]

    def _parse_reflection_result(self, result: str) -> ReflectionResult:
        """Parse the reflection result"""
        # Extract content between reflection_result tags
        if "<reflection_result>" not in result:
            return ReflectionResult(failure_reason=result)

        if "</reflection_result>" not in result:
            result += "</reflection_result>"

        start = result.find("<reflection_result>") + len("<reflection_result>")
        end = result.find("</reflection_result>")
        result = result[start:end].strip()

        # Extract each field
        def extract_field(field: str) -> str | list[str] | None:
            start_tag = f"<{field}>"
            end_tag = f"</{field}>"
            start = result.find(start_tag) + len(start_tag)
            end = result.find(end_tag)
            if start == -1 or end == -1:
                return None
            content = result[start:end].strip()
            if not content:
                return None
            return content

        return ReflectionResult(
            failure_reason=extract_field("failure_reason"),
            failure_category=extract_field("failure_category"),
            pattern_identified=extract_field("pattern_identified"),
            partial_success=extract_field("partial_success"),
            next_component=extract_field("next_component"),
            component_guidance=extract_field("component_guidance"),
        )

    def _get_build_failure_data(self, patch_attempt: PatchAttempt) -> str:
        return BUILD_FAILED_FAILURE_DATA.format(
            build_stdout=decode_bytes(patch_attempt.build_stdout),
            build_stderr=decode_bytes(patch_attempt.build_stderr),
        )

    def _get_pov_failure_data(self, patch_attempt: PatchAttempt) -> str:
        return POV_FAILED_FAILURE_DATA.format(
            pov_stdout=decode_bytes(patch_attempt.pov_stdout),
            pov_stderr=decode_bytes(patch_attempt.pov_stderr),
        )

    def _get_tests_failure_data(self, patch_attempt: PatchAttempt) -> str:
        return TESTS_FAILED_FAILURE_DATA.format(
            tests_stdout=decode_bytes(patch_attempt.tests_stdout),
            tests_stderr=decode_bytes(patch_attempt.tests_stderr),
        )

    def _get_failure_data(self, state: PatcherAgentState, patch_attempt: PatchAttempt) -> str:
        if patch_attempt.status == PatchStatus.CREATION_FAILED:
            return CREATION_FAILED_FAILURE_DATA
        elif patch_attempt.status == PatchStatus.DUPLICATED:
            return DUPLICATED_FAILURE_DATA
        elif patch_attempt.status == PatchStatus.APPLY_FAILED:
            return APPLY_FAILED_FAILURE_DATA
        elif patch_attempt.status == PatchStatus.BUILD_FAILED:
            return self._get_build_failure_data(patch_attempt)
        elif patch_attempt.status == PatchStatus.POV_FAILED:
            return self._get_pov_failure_data(patch_attempt)
        elif patch_attempt.status == PatchStatus.TESTS_FAILED:
            return self._get_tests_failure_data(patch_attempt)
        else:
            logger.warning(
                "[%s / %s] Patch is pending, we should not be here, let's move back to root cause analysis",
                state.context.task_id,
                state.context.submission_index,
            )
            return "Unknown failure"

    def _get_extra_information(
        self, state: PatcherAgentState, configuration: PatcherConfig, last_group_status: tuple[PatchStatus, int] | None
    ) -> str:
        """Get extra information about the failure."""
        if last_group_status is None or last_group_status[1] < configuration.max_last_failure_retries:
            return ""

        match last_group_status[0]:
            case PatchStatus.CREATION_FAILED:
                return CREATION_FAILED_EXTRA_INFORMATION
            case PatchStatus.DUPLICATED:
                return DUPLICATED_EXTRA_INFORMATION
            case PatchStatus.APPLY_FAILED:
                return APPLY_FAILED_EXTRA_INFORMATION
            case PatchStatus.BUILD_FAILED:
                return BUILD_FAILED_EXTRA_INFORMATION
            case PatchStatus.POV_FAILED:
                return POV_FAILED_EXTRA_INFORMATION
            case PatchStatus.TESTS_FAILED:
                return TESTS_FAILED_EXTRA_INFORMATION
            case _:
                return ""

    def _analyze_failure(
        self, state: PatcherAgentState, configuration: PatcherConfig, patch_attempt: PatchAttempt
    ) -> Command:
        """Analyze the failure of the patch."""
        if patch_attempt.status == PatchStatus.SUCCESS:
            logger.info(
                "[%s / %s] Patch is working, terminating the patching process",
                state.context.task_id,
                state.context.submission_index,
            )
            return Command(goto=END)

        logger.info(
            "[%s / %s] Analyzing failure of patch %s",
            state.context.task_id,
            state.context.submission_index,
            patch_attempt.id,
        )

        extra_information = ""
        last_attempts_status = [attempt.status for attempt in state.patch_attempts]

        # Group consecutive statuses
        grouped_statuses = [(status, len(list(group))) for status, group in groupby(last_attempts_status)]
        last_group_status = grouped_statuses[-1] if grouped_statuses else None

        failure_data = self._get_failure_data(state, patch_attempt)
        extra_information = self._get_extra_information(state, configuration, last_group_status)

        try:
            result: ReflectionResult = self.reflection_chain.invoke(
                {
                    "LAST_PATCH_ATTEMPT": PATCH_ATTEMPT_TMPL.format(
                        id=patch_attempt.id,
                        description=patch_attempt.description,
                        patch=patch_attempt.patch.patch if patch_attempt.patch else "",
                        raw_patch_str=patch_attempt.patch_str
                        if not patch_attempt.patch or not patch_attempt.patch.patch
                        else "",
                        status=patch_attempt.status,
                    ),
                    "FAILURE_TYPE": patch_attempt.status,
                    "FAILURE_DATA": failure_data,
                    "ROOT_CAUSE_ANALYSIS": str(state.root_cause),
                    "CODE_SNIPPETS": "\n".join(
                        [
                            CODE_SNIPPET_SUMMARY_TMPL.format(
                                identifier=cs.key.identifier,
                                file_path=cs.key.file_path,
                                description=cs.description,
                                start_line=cs.start_line,
                                end_line=cs.end_line,
                            )
                            for cs in state.relevant_code_snippets
                        ]
                    ),
                    "PREVIOUS_ATTEMPTS": "\n".join(
                        [
                            PREVIOUS_PATCH_ATTEMPTS_TMPL.format(
                                id=attempt.id,
                                description=attempt.description,
                                patch=attempt.patch.patch if attempt.patch else "",
                                status=attempt.status,
                                failure_analysis=attempt.analysis.failure_analysis if attempt.analysis else None,
                                resolution_component=attempt.analysis.resolution_component
                                if attempt.analysis
                                else None,
                                partial_success=attempt.analysis.partial_success if attempt.analysis else None,
                            )
                            for attempt in state.patch_attempts[:-1]
                        ]
                    ),
                    "AVAILABLE_COMPONENTS": "\n".join(
                        [
                            AVAILABLE_COMPONENT_TMPL.format(name=component_name, description=component_description)
                            for component_name, component_description in self.components
                        ]
                    ),
                    "EXTRA_INFORMATION": extra_information,
                }
            )
        except Exception as e:
            logger.error(
                "[%s / %s] Error getting reflection result (or parsing it): %s",
                state.context.task_id,
                state.context.submission_index,
                e,
            )
            return Command(goto=PatcherAgentName.ROOT_CAUSE_ANALYSIS.value)

        if not patch_attempt.analysis:
            patch_attempt.analysis = PatchAnalysis()

        patch_attempt.analysis.failure_analysis = result.failure_reason
        patch_attempt.analysis.failure_category = result.failure_category
        patch_attempt.analysis.resolution_component = result.next_component
        patch_attempt.analysis.partial_success = result.partial_success
        execution_info = state.execution_info
        execution_info.reflection_decision = result.next_component
        execution_info.reflection_guidance = result.component_guidance
        execution_info.root_cause_analysis_tries = 0
        if result.next_component == PatcherAgentName.CONTEXT_RETRIEVER:
            return Command(
                update={
                    "execution_info": execution_info,
                    "prev_node": PatcherAgentName.CREATE_PATCH.value,
                    "relevant_code_snippets": state.relevant_code_snippets,
                    "code_snippet_requests": [
                        CodeSnippetRequest(
                            request=result.component_guidance,
                        )
                    ],
                },
                goto=PatcherAgentName.CONTEXT_RETRIEVER.value,
            )
        else:
            return Command(
                update={
                    "patch_attempts": patch_attempt,
                    "execution_info": execution_info,
                },
                goto=result.next_component.value,
            )

    def _root_cause_analysis_failed(self, state: PatcherAgentState, configuration: PatcherConfig) -> Command:
        """Root cause analysis failed, reflect on the failure."""
        logger.warning(
            "[%s / %s] Root cause analysis failed, reflecting on it",
            state.context.task_id,
            state.context.submission_index,
        )

        if state.execution_info.root_cause_analysis_tries >= configuration.max_root_cause_analysis_retries:
            logger.warning(
                "[%s / %s] Reached max root cause failures, just move forward with what we have",
                state.context.task_id,
                state.context.submission_index,
            )
            return Command(goto=PatcherAgentName.CREATE_PATCH.value)

        execution_info = state.execution_info
        execution_info.root_cause_analysis_tries += 1
        if not state.root_cause or not state.root_cause.code_snippet_requests:
            # This should not happen, but just in case
            # This can only happen if we don't have any patch attempt yet and
            # root cause is very broken
            return Command(
                update={
                    "execution_info": execution_info,
                },
                goto=PatcherAgentName.ROOT_CAUSE_ANALYSIS.value,
            )

        return Command(
            update={
                "code_snippet_requests": [
                    CodeSnippetRequest(
                        request=state.root_cause.code_snippet_requests,
                    )
                ],
                "prev_node": PatcherAgentName.ROOT_CAUSE_ANALYSIS.value,
                "execution_info": execution_info,
            },
            goto=PatcherAgentName.CONTEXT_RETRIEVER.value,
        )

    def reflect_on_patch(self, state: PatcherAgentState, config: RunnableConfig) -> Command:
        """Reflect on the patch."""
        configuration = PatcherConfig.from_configurable(config)
        self.challenge.restore()

        if len(state.patch_attempts) >= configuration.max_patch_retries:
            logger.warning(
                "[%s / %s] Reached max patch tries, terminating the patching process",
                state.context.task_id,
                state.context.submission_index,
            )
            return Command(
                goto=END,
            )

        current_patch_attempt = state.get_last_patch_attempt()
        if not current_patch_attempt or state.execution_info.prev_node == PatcherAgentName.ROOT_CAUSE_ANALYSIS:
            logger.warning(
                "[%s / %s] No patch attempt found, the root cause analysis is probably wrong",
                state.context.task_id,
                state.context.submission_index,
            )
            return self._root_cause_analysis_failed(state, configuration)

        return self._analyze_failure(state, configuration, current_patch_attempt)
