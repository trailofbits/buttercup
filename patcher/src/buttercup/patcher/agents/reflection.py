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
    PatchStrategy,
)
from buttercup.patcher.agents.config import PatcherConfig
from buttercup.common.llm import ButtercupLLM, create_default_llm
from langchain_core.prompts import (
    ChatPromptTemplate,
)

logger = logging.getLogger(__name__)

SYSTEM_MSG = """You are an agent - please keep going until the user's query is completely resolved, before ending your turn and yielding back to the user. Only terminate your turn when you are sure that the problem is solved.
You MUST plan extensively before each function call, and reflect extensively on the outcomes of the previous function calls. DO NOT do this entire process by making function calls only, as this can impair your ability to solve the problem and think insightfully.

You are the Reflection Engine in an autonomous vulnerability patching system."""

REFLECTION_PROMPT = """You are a security-focused reflection engine in an autonomous vulnerability patching system. Your primary task is to analyze why a patch failed and determine the best next steps to unblock other agents in the system.

CRITICAL: Your role is to prevent infinite loops and ensure forward progress. If you see repeated failures of the same type, you MUST redirect to a different component rather than continuing the same approach.

Your thinking should be thorough and so it's fine if it's very long. You can think step by step before and after each action you decide to take.

First, carefully review the following information about the failed patch attempt:

Existing root cause analysis:
<root_cause_analysis>
{ROOT_CAUSE_ANALYSIS}
</root_cause_analysis>

Code snippets used until now:
<code_snippets>
{CODE_SNIPPETS}
</code_snippets>

Previous patch attempts, excluding the last one ({N_PREVIOUS_ATTEMPTS}):
<previous_attempts>
{PREVIOUS_ATTEMPTS}
</previous_attempts>

Now, analyze the specific failure information:

Last patch attempt:
<last_patch_attempt>
{LAST_PATCH_ATTEMPT}
</last_patch_attempt>

Failure analysis:
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

To ensure a thorough and transparent reflection process, work through your analysis *STEP BY STEP* in <analysis_breakdown> tags inside your thinking block.
Do not jump directly to conclusions, always follow the steps and provide a detailed analysis in the <analysis_breakdown> tags.
Follow these steps:

1. **Loop Detection Analysis**: FIRST, examine the previous attempts for patterns that indicate potential infinite loops:
   - Count how many times each component has been called recently
   - Identify if the same failure type is repeating (3+ times = loop risk)
   - Check if the same error messages or failure modes keep occurring
   - Look for oscillation between components without progress
   - If a loop is detected, you MUST break it by choosing a different component

2. **Failure Context Summary**: Summarize key points from each input section:
   - Last patch attempt: Focus on what was changed and why it failed
   - Root cause analysis: Identify the core vulnerability and its impact
   - Code snippets: Note relevant security-sensitive code sections
   - Previous attempts: Look for patterns in failed approaches
   - Failure analysis: Understand the specific failure mode
   - Extra information: Consider any additional context

3. **Evidence Extraction**: Extract and quote relevant information from each input section for each point of analysis. Focus on:
   - Security-critical code sections
   - Error messages and failure patterns
   - Previous patch attempts and their outcomes
   - Root cause analysis insights

4. **Failure Category Assessment**: For the failure category, consider arguments for each possible category:
   - incomplete_fix: The patch addresses part but not all of the vulnerability
   - wrong_approach: The patch strategy doesn't properly address the root cause
   - misunderstood_root_cause: The vulnerability analysis was incorrect
   - missing_code_snippet: Required code context is not available
   - build_error: Technical issues preventing patch application
   - regression_issue: The patch breaks existing functionality

5. **Failure Category Scoring**: Rate the likelihood of each failure category on a scale of 1-5, considering:
   - Security impact of each failure type
   - Evidence from error messages and code
   - Previous attempt patterns
   - Root cause analysis alignment

6. **Security Improvement Identification**: List at least 3 potential improvements for the vulnerability fix. Focus ONLY on security-related improvements:
   - Input validation and sanitization
   - Access control and authorization checks
   - Memory safety and bounds checking
   - Race condition prevention
   - Resource cleanup and error handling
   - Cryptographic implementation fixes
   - Secure communication protocols
   - Authentication mechanisms

7. **Pattern Analysis**: Create a numbered list of patterns across multiple failed attempts:
   - Similar error messages or failure modes
   - Repeated security check omissions
   - Common code paths or functions
   - Consistent failure categories
   - Related security mechanisms
   - Component call frequency and outcomes

8. **Component Selection Strategy**: For the next component, consider pros and cons for each available component based on:
   - Current failure mode and what type of intervention is needed
   - Available information and whether more context is required
   - Previous attempt history and which components have been tried recently
   - Security requirements and which component best addresses the vulnerability

9. **Component Suitability Scoring**: Rate each component's suitability on a scale of 1-5, considering:
   - Current failure mode
   - Available information
   - Previous attempt history
   - Security requirements
   - **CRITICAL**: Reduce score by 3 points if component was called in last 2 attempts with same failure type

10. **Information Gap Analysis**: Carefully consider if the next component might need additional information:
    - Required code snippets
    - Security context
    - Error details
    - Previous attempt data
    If critical information is missing, prioritize components that can gather this information.

11. **Loop Breaking Decision**: If you have identified a pattern across multiple failures:
    - If the same component failed 3+ times: MUST choose a different component
    - If recently called components haven't made progress: MUST try an alternative approach
    - If oscillating between components: MUST try a third option
    - Document the pattern and its implications for future attempts

12. **Progress Validation**: Before finalizing your decision:
    - Ensure the selected component can make meaningful progress
    - Verify you're not repeating a recently failed approach
    - Confirm the guidance addresses the core security vulnerability
    - Check that the path forward is different from recent attempts

After your analysis, generate a structured reflection result using the following format:

<reflection_result>
<failure_reason>[Provide a detailed and specific reason for why the patch failed, focusing on security implications]</failure_reason>
<failure_category>[Choose one: incomplete_fix, wrong_approach, misunderstood_root_cause, missing_code_snippet, build_error, regression_issue]</failure_category>
<pattern_identified>[Describe any patterns seen across multiple failures, including loop detection results, or state "No clear pattern identified" if none are apparent]</pattern_identified>
<next_component>[Select one of the available components, ensuring it breaks any detected loops]</next_component>
<component_guidance>[Provide detailed, specific, actionable guidance for the selected component. Focus on security requirements and concrete steps to address the vulnerability. If breaking a loop, explain why this approach is different. Also include an explanation of the patterns identified across multiple failures and how to fix them.]</component_guidance>
<partial_success>[True if the patch shows partial success, False if it is completely broken and should be discarded. If the next component guidance says to "improve the patch" or modify the patch in some way, then the patch is partially successful.]</partial_success>
</reflection_result>

The available components for the next step are:
<available_components>
{AVAILABLE_COMPONENTS}
</available_components>

Remember:
- **PRIORITY 1**: Prevent infinite loops - if same failure type occurs 3+ times, MUST change component
- **PRIORITY 2**: Focus ONLY on fixing the security vulnerability
- Do NOT suggest adding tests, logging, or refactoring code
- Do NOT suggest improvements unrelated to the security vulnerability
- Your analysis and guidance should be thorough and specific enough to help unblock other agents in the autonomous patching system
- Try to provide first simpler guidance and only if those do not work, provide more complex guidance
- Always prioritize security-critical fixes over other improvements
- Consider the full security context when analyzing failures
- Look for patterns that might indicate deeper security issues
- When breaking loops, clearly explain why the new approach is different and likely to succeed

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
<patch_strategy>{patch_strategy}</patch_strategy>
<status>{status}</status>
</patch_attempt>
"""

PREVIOUS_PATCH_ATTEMPTS_TMPL = """<previous_patch_attempt>
<id>{id}</id>
<description>{description}</description>
<patch>{patch}</patch>
<status>{status}</status>
<partial_success>{partial_success}</partial_success>
<patch_strategy>{patch_strategy}</patch_strategy>
<failure_analysis>{failure_analysis}</failure_analysis>
<resolution_component>{resolution_component}</resolution_component>
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

VALIDATION_FAILED_FAILURE_DATA = """The patch did not pass the validation. It \
means that it was patching tests/fuzz harnesses instead of the actual project's \
code that has the vulnerability or it is patching files that are not in the \
target project's language (C or Java). """

VALIDATION_FAILED_EXTRA_INFORMATION = """The last few patch attempts all failed \
because the patch did not pass the validation. It means the patches were patching \
tests/fuzz harnesses instead of the actual project's code that has the \
vulnerability or they were patching files that are not in the target project's \
language (C or Java). Reflect on the patch from a broader perspective to \
understand what went wrong. Consider looking for new code snippets or \
re-evaluating the root cause analysis/patch strategy."""

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
        default_llm = create_default_llm(model_name=ButtercupLLM.OPENAI_GPT_4_1.value)
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
                "Creates a patch based on the root cause analysis and available code snippets. "
                "This should be used when the patch attempts do not follow completely the patch strategy or the last patch was a duplicate or the last patch could not be generated/applied. "
                "When providing guidance: "
                "1) Specify exactly which code snippets to modify and how (e.g., 'Add validation for SQL input in function X') "
                "2) List any specific security checks that must be included (e.g., 'Add null pointer check before dereferencing variable Y') "
                "3) Mention any edge cases that must be handled (e.g., 'Handle empty input case for variable Y in function Z')",
            ),
            (
                PatcherAgentName.ROOT_CAUSE_ANALYSIS.value,
                "Re-analyzes the vulnerability's root cause using the existing code snippets and previous attempts. "
                "This should be used when the last few patch attempts fail even though they have different patch strategy and they implement the strategy correctly. "
                "When providing guidance: "
                "1) Identify specific code patterns that indicate the vulnerability (e.g., 'Missing bounds check in array access') "
                "2) Explain the security impact of the vulnerability (e.g., 'Buffer overflow allows arbitrary code execution') "
                "3) List all affected components and their relationships (e.g., 'Vulnerability spans functions X and Y') "
                "4) Specify which code paths need to be analyzed (e.g., 'Focus on error handling path in function Z')",
            ),
            (
                PatcherAgentName.CONTEXT_RETRIEVER.value,
                "Retrieves additional code snippets needed for analysis or patching. "
                "This should be used when previous attempts failed because of missing information that need to be retrieved. "
                "When providing guidance: "
                "1) Specify exact file paths or function names to search for (e.g., 'Find all usages of function X in directory Y') "
                "2) List specific code patterns to look for (e.g., 'Search for all array access operations in file Z') "
                "3) Define the scope of the search (e.g., 'Look for error handling code in related modules') "
                "4) Explain why each requested snippet is needed (e.g., 'Need to understand how function X handles its input')",
            ),
            (
                PatcherAgentName.PATCH_STRATEGY.value,
                "Develops a comprehensive approach to fix the vulnerability, given a root cause analysis and code snippets. "
                "This only describes at a high level what to do, it does not provide any specific code changes. The root cause is assumed to be correct. "
                "When providing guidance: "
                "1) List required security mechanisms (e.g., 'Add input sanitization and bounds checking') "
                "2) Define the scope of changes needed (e.g., 'Modify both the validation and error handling paths') "
                "3) Explain how to maintain security invariants (e.g., 'Ensure all error paths properly clean up resources')",
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
        elif patch_attempt.status == PatchStatus.VALIDATION_FAILED:
            return VALIDATION_FAILED_FAILURE_DATA
        else:
            logger.warning(
                "[%s / %s] Patch is pending, we should not be here, let's move back to root cause analysis",
                state.context.task_id,
                state.context.internal_patch_id,
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
            case PatchStatus.VALIDATION_FAILED:
                return VALIDATION_FAILED_EXTRA_INFORMATION
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
                state.context.internal_patch_id,
            )
            return Command(goto=END)

        logger.info(
            "[%s / %s] Analyzing failure of patch %s",
            state.context.task_id,
            state.context.internal_patch_id,
            patch_attempt.id,
        )

        execution_info = state.execution_info
        if execution_info.tests_tries >= configuration.max_tests_retries:
            logger.warning(
                "[%s / %s] Reached max tests tries, just accept the patch",
                state.context.task_id,
                state.context.internal_patch_id,
            )
            patch_attempt.status = PatchStatus.SUCCESS
            patch_attempt.tests_passed = True
            return Command(
                update={
                    "patch_attempts": patch_attempt,
                    "execution_info": execution_info,
                },
                goto=END,
            )

        extra_information = ""
        last_attempts_status = [attempt.status for attempt in state.patch_attempts]

        # Group consecutive statuses
        grouped_statuses = [(status, len(list(group))) for status, group in groupby(last_attempts_status)]
        last_group_status = grouped_statuses[-1] if grouped_statuses else None

        if patch_attempt.status == PatchStatus.TESTS_FAILED:
            execution_info.tests_tries += 1

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
                        patch_strategy=state.patch_strategy.full if state.patch_strategy else "",
                    ),
                    "FAILURE_TYPE": patch_attempt.status,
                    "FAILURE_DATA": failure_data,
                    "ROOT_CAUSE_ANALYSIS": str(state.root_cause),
                    "CODE_SNIPPETS": "\n".join(map(str, state.relevant_code_snippets)),
                    "N_PREVIOUS_ATTEMPTS": len(state.patch_attempts) - 1,
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
                                patch_strategy=attempt.strategy,
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
                state.context.internal_patch_id,
                e,
            )
            return Command(goto=PatcherAgentName.ROOT_CAUSE_ANALYSIS.value)

        if not patch_attempt.analysis:
            patch_attempt.analysis = PatchAnalysis()

        patch_attempt.analysis.failure_analysis = result.failure_reason
        patch_attempt.analysis.failure_category = result.failure_category
        patch_attempt.analysis.resolution_component = result.next_component
        patch_attempt.analysis.partial_success = result.partial_success
        execution_info.reflection_decision = result.next_component
        execution_info.reflection_guidance = result.component_guidance
        execution_info.root_cause_analysis_tries = 0
        if result.next_component == PatcherAgentName.CONTEXT_RETRIEVER:
            return Command(
                update={
                    "execution_info": execution_info,
                    "prev_node": PatcherAgentName.ROOT_CAUSE_ANALYSIS.value,
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
            state.context.internal_patch_id,
        )

        if state.execution_info.root_cause_analysis_tries >= configuration.max_root_cause_analysis_retries:
            logger.warning(
                "[%s / %s] Reached max root cause failures, just move forward with what we have",
                state.context.task_id,
                state.context.internal_patch_id,
            )
            root_cause = state.root_cause
            if root_cause is None:
                root_cause = "No root cause found, figure out a root cause"

            return Command(
                update={
                    "root_cause": root_cause,
                },
                goto=PatcherAgentName.PATCH_STRATEGY.value,
            )

        execution_info = state.execution_info
        execution_info.root_cause_analysis_tries += 1
        # This should not happen, but just in case
        # This can only happen if we don't have any patch attempt yet and
        # root cause is very broken
        return Command(
            update={
                "execution_info": execution_info,
            },
            goto=PatcherAgentName.ROOT_CAUSE_ANALYSIS.value,
        )

    def _patch_strategy_failed(self, state: PatcherAgentState, configuration: PatcherConfig) -> Command:
        """Patch strategy failed, reflect on the failure."""
        if state.execution_info.patch_strategy_tries >= configuration.max_patch_strategy_retries:
            logger.warning(
                "[%s / %s] Reached max patch strategy failures, just move forward with what we have",
                state.context.task_id,
                state.context.internal_patch_id,
            )
            strategy = state.patch_strategy
            if strategy is None:
                strategy = PatchStrategy(full="Figure out a patch strategy", summary="Figure out a patch strategy")

            return Command(
                update={
                    "patch_strategy": strategy,
                },
                goto=PatcherAgentName.CREATE_PATCH.value,
            )

        execution_info = state.execution_info
        execution_info.patch_strategy_tries += 1
        return Command(
            update={
                "execution_info": execution_info,
            },
            goto=PatcherAgentName.PATCH_STRATEGY.value,
        )

    def reflect_on_patch(self, state: PatcherAgentState, config: RunnableConfig) -> Command:
        """Reflect on the patch."""
        configuration = PatcherConfig.from_configurable(config)
        if state.execution_info.prev_node is None:
            logger.warning(
                "[%s / %s] Previous node is not set, this is a developer error, assuming root cause analysis.",
                state.context.task_id,
                state.context.internal_patch_id,
            )
            state.execution_info.prev_node = PatcherAgentName.ROOT_CAUSE_ANALYSIS

        if len(state.patch_attempts) >= configuration.max_patch_retries:
            logger.warning(
                "[%s / %s] Reached max patch tries, terminating the patching process",
                state.context.task_id,
                state.context.internal_patch_id,
            )
            return Command(
                goto=END,
            )

        # If a node has explicitly requested additional information, let's move
        # to the context retriever to get the information and then come back to
        # the same node
        if state.execution_info.code_snippet_requests:
            logger.info(
                "[%s / %s] Requesting additional information",
                state.context.task_id,
                state.context.internal_patch_id,
            )
            code_snippet_requests = state.execution_info.code_snippet_requests
            state.execution_info.code_snippet_requests = []
            return Command(
                update={
                    "code_snippet_requests": code_snippet_requests,
                    "prev_node": state.execution_info.prev_node.value,
                    "execution_info": state.execution_info,
                    "relevant_code_snippets": state.relevant_code_snippets,
                },
                goto=PatcherAgentName.CONTEXT_RETRIEVER.value,
            )

        if state.execution_info.prev_node == PatcherAgentName.ROOT_CAUSE_ANALYSIS:
            logger.warning(
                "[%s / %s] No patch attempt found, the root cause analysis is probably wrong",
                state.context.task_id,
                state.context.internal_patch_id,
            )
            return self._root_cause_analysis_failed(state, configuration)

        if state.execution_info.prev_node == PatcherAgentName.PATCH_STRATEGY:
            logger.warning(
                "[%s / %s] Patch strategy failed, reflecting on it",
                state.context.task_id,
                state.context.internal_patch_id,
            )
            return self._patch_strategy_failed(state, configuration)

        current_patch_attempt = state.get_last_patch_attempt()
        if not current_patch_attempt:
            logger.error(
                "[%s / %s] No patch attempt found, this should never happen, going back to input processing",
                state.context.task_id,
                state.context.internal_patch_id,
            )
            return Command(goto=PatcherAgentName.INPUT_PROCESSING.value)

        return self._analyze_failure(state, configuration, current_patch_attempt)
