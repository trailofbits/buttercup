"""Software Engineer LLM agent, analyzing the root cause of a vulnerability."""

import logging
from typing import Literal
from dataclasses import dataclass, field

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import (
    ChatPromptTemplate,
)
from langchain_core.messages import BaseMessage
from langchain_core.runnables import Runnable
from buttercup.patcher.agents.common import (
    PatcherAgentState,
    PatcherAgentName,
    PatcherAgentBase,
    CONTEXT_CODE_SNIPPET_TMPL,
    ContextCodeSnippet,
)
from buttercup.common.llm import ButtercupLLM, create_default_llm
from buttercup.patcher.utils import decode_bytes
from langgraph.types import Command

logger = logging.getLogger(__name__)

ROOT_CAUSE_SYSTEM_MSG = """You are an experienced security engineer tasked with determining the root cause of a specific vulnerability. Your analysis will be used to patch the vulnerability."""
ROOT_CAUSE_USER_MSG = """Your goal is to provide a highly technical, detailed, and focused analysis of the vulnerability, going to the root cause of the issue.

Here is the information you need to analyze:

1. Diff introducing the vulnerability (if available):
<diff>
{DIFF}
</diff>

2. Project Name:
<project_name>
{PROJECT_NAME}
</project_name>

3. Sanitizer used:
<sanitizer>
{SANITIZER}
</sanitizer>

4. Sanitizer output:
<sanitizer_output>
{SANITIZER_OUTPUT}
</sanitizer_output>

5. Code snippets from the project:
<code_snippets>
{CODE_SNIPPETS}
</code_snippets>{OLD_ROOT_CAUSE}

Instructions:

1. Review all the provided information carefully.

2. Conduct a thorough analysis of the vulnerability. Focus solely on the issue reported in the sanitizer output (and introduced by the diff if available).

3. Structure your response as follows:

   <vulnerability_analysis_process>
   [Break down your thought process using this structure:

   1. Diff Analysis:
      - Quote each specific change in the diff relevant to the vulnerability.
      - Explain what each of those changes does to the code.

   2. Sanitizer Output Analysis:
      - Quote each relevant part of the sanitizer output.
      - Interpret what each part means in terms of potential vulnerabilities.

   3. Code Snippet Analysis:
      - Quote the relevant parts of the provided code snippets.
      - Explain how these parts relate to the changes in the diff and the sanitizer output.

   4. Integrated Analysis:
      - Connect the findings from the diff, sanitizer output, and code snippets.
      - Explain how these components work together to introduce the vulnerability.
      - Use the reference numbers from previous steps to clearly link your observations.

   5. Previous Root Cause Analysis:
      - If a previous root cause analysis is available, try to critically analyze it and see if it's still valid, and provide your own extended/improved analysis.

   6. Vulnerability Identification:
      - Based on the integrated analysis, explain how the changes introduced the vulnerability.
      - Use technical details and security concepts to support your conclusion.

   7. Determine if additional code snippets need to be requested:
      - If you need additional context to understand the code, wrap your code request in <code_request> tags. Be specific about what code you need and why. If there is a previous root cause analysis, try to explore more parts of the code to better understand the vulnerability. Request example:
    <code_requests>
    <code_request>
    Full implementation of the function 'validate_input()' from the file 'input_validation.c', as it's referenced in the diff but not fully visible.
    </code_request>
    <code_request>
    ...
    </code_request>
    </code_requests>

   Ensure that you reference and analyze all components (code snippets, diff, and sanitizer output) before drawing any conclusions. Request additional code snippets if necessary for a complete understanding. Remember to quote relevant parts of the code, diff, and sanitizer output throughout your analysis.]
   </vulnerability_analysis_process>

   <analysis>
   [Provide a detailed, technical explanation of the vulnerability. Include:
   - The exact nature of the vulnerability
   - How it was introduced in the diff
   - Relevant technical details about how the vulnerability could be exploited

   Ground your explanation in the provided code snippets, diff, and sanitizer output.]
   </analysis>

   <summary>
   [Provide a clear, concise description of the vulnerability introduced by the diff. Highlight the most critical aspects of the security issue.]
   </summary>

4. In your analysis:
   - Provide a detailed, technical explanation of the vulnerability.
   - Describe a concrete and specific problem.
   - If there are multiple vulnerabilities in the diff, focus on the one which triggers the sanitizer.
   - Base your analysis on the provided code snippets, diff, and sanitizer output.
   - Request and analyze additional code snippets if necessary for a complete understanding.

5. Do NOT:
   - Provide generic recommendations.
   - Offer overly generic analyses.
   - Discuss possible issues that existed before the diff.
   - Suggest code fixes for the vulnerability.
   - Make up any information not present in the provided data.

Maintain a highly technical approach throughout your analysis, focusing solely on the vulnerability introduced by the diff and avoiding any generic advice or recommendations for fixing the code.
"""

ROOT_CAUSE_PROMPT = ChatPromptTemplate.from_messages(
    [
        ("system", ROOT_CAUSE_SYSTEM_MSG),
        ("user", ROOT_CAUSE_USER_MSG),
        ("ai", "<vulnerability_analysis_process>"),
    ]
)

OLD_ROOT_CAUSE_TMPL = """

6. Existing root cause analysis (potentially outdated, wrong, or incomplete):

<old_root_cause>
{root_cause}
</old_root_cause>"""

BUILD_FAILURE_SYSTEM_TMPL = """\
You are a software engineer helping fixing a bug in a \
software project. Another software engineer has tried to fix the bug, \
but the build failed. You need to analyze the build failure to \
understand the issue and provide suggestions to the other \
software engineer on how to write a better patch.

In any case, DO NOT write the patch. You can suggest what needs fixing, but \
you should not write the patch yourself. Do not make up code, contexts or \
information.

Ignore warnings or non-fatal errors, focus on the build failure itself.
"""

BUILD_FAILURE_PROMPT = ChatPromptTemplate.from_messages(
    [
        ("system", BUILD_FAILURE_SYSTEM_TMPL),
        ("placeholder", "{code_snippets}"),
        ("user", "Patch:\n```\n{patch}\n```"),
        ("user", "Build failure stdout:\n```\n{build_stdout}\n```"),
        ("user", "Build failure stderr:\n```\n{build_stderr}\n```"),
    ]
)


@dataclass
class RootCauseAgent(PatcherAgentBase):
    """Software Engineer LLM agent, triaging a vulnerability."""

    llm: Runnable = field(init=False)
    root_cause_chain: Runnable = field(init=False)
    build_failure_analysis_chain: Runnable = field(init=False)

    def __post_init__(self) -> None:
        """Initialize a few fields"""
        default_llm = create_default_llm(model_name=ButtercupLLM.OPENAI_GPT_4O.value)
        fallback_llms = [
            create_default_llm(model_name=ButtercupLLM.CLAUDE_3_5_SONNET.value),
        ]
        self.llm = default_llm.with_fallbacks(fallback_llms)

        self.root_cause_chain = ROOT_CAUSE_PROMPT | self.llm | StrOutputParser()
        self.build_failure_analysis_chain = BUILD_FAILURE_PROMPT | self.llm | StrOutputParser()

    def _get_relevant_code_snippets_msgs(
        self, relevant_code_snippets: set[ContextCodeSnippet]
    ) -> list[BaseMessage | str]:
        messages: list[BaseMessage | str] = []
        for code_snippet in relevant_code_snippets:
            messages += [
                CONTEXT_CODE_SNIPPET_TMPL.format(
                    file_path=code_snippet.key.file_path,
                    identifier=code_snippet.key.identifier,
                    code=code_snippet.code,
                    code_context=code_snippet.code_context,
                )
            ]

        return messages

    def analyze_vulnerability(
        self, state: PatcherAgentState
    ) -> Command[Literal[PatcherAgentName.CONTEXT_RETRIEVER.value, PatcherAgentName.CREATE_PATCH.value]]:  # type: ignore[name-defined]
        """Analyze the diff analysis and the code to understand the
        vulnerability in the current code."""
        logger.info("Analyzing the vulnerability in Challenge Task %s", self.challenge.name)

        diff_content = "\n".join(diff.read_text() for diff in self.challenge.get_diffs())
        root_cause = self.chain_call(
            lambda x, y: x + y,
            self.root_cause_chain,
            {
                "DIFF": diff_content,
                "PROJECT_NAME": self.challenge.project_name,
                "SANITIZER": state.context.sanitizer,
                "SANITIZER_OUTPUT": state.context.sanitizer_output,
                "CODE_SNIPPETS": "\n".join(map(str, state.relevant_code_snippets)),
                "OLD_ROOT_CAUSE": OLD_ROOT_CAUSE_TMPL.format(root_cause=state.root_cause) if state.root_cause else "",
            },
            default="",  # type: ignore[call-arg]
        )
        if not root_cause:
            logger.error("Could not find the root cause of the vulnerability")
            raise ValueError("Could not find the root cause of the vulnerability")

        update_state = {
            "root_cause": root_cause,
        }
        goto, update_state = self.get_code_snippet_requests(
            root_cause,
            update_state,
            state.ctx_request_limit,
            current_node=PatcherAgentName.ROOT_CAUSE_ANALYSIS.value,
            default_goto=PatcherAgentName.CREATE_PATCH.value,
        )
        return Command(
            update=update_state,
            goto=goto,
        )

    def analyze_build_failure(self, state: PatcherAgentState) -> Command[Literal[PatcherAgentName.CREATE_PATCH.value]]:  # type: ignore[name-defined]
        """Analyze the build failure to understand the issue and suggest a fix."""
        logger.info("Analyzing the build failure in Challenge Task %s", self.challenge.name)
        code_snippets = self._get_relevant_code_snippets_msgs(state.relevant_code_snippets)
        last_patch = state.get_last_patch()
        if not last_patch:
            logger.fatal("No patch to analyze build failure")
            raise RuntimeError("No patch to analyze build failure")

        build_analysis: str = self.chain_call(
            lambda x, y: x + y,
            self.build_failure_analysis_chain,
            {
                "code_snippets": code_snippets,
                "patch": last_patch.patch,
                "build_stdout": decode_bytes(state.build_stdout),
                "build_stderr": decode_bytes(state.build_stderr),
            },
            default="",  # type: ignore[call-arg]
        )

        return Command(
            update={
                "build_analysis": build_analysis,
            },
            goto=PatcherAgentName.CREATE_PATCH.value,
        )
