"""Software Engineer LLM agent, analyzing the root cause of a vulnerability."""

import logging
import re
from typing import Literal
from dataclasses import dataclass, field
from operator import itemgetter

import tiktoken
from langchain_core.messages import BaseMessage
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import (
    ChatPromptTemplate,
    MessagesPlaceholder,
)
from langchain_core.runnables import Runnable, RunnableBranch
from buttercup.patcher.agents.common import (
    CONTEXT_CODE_SNIPPET_TMPL,
    CONTEXT_DIFF_ANALYSIS_TMPL,
    CONTEXT_DIFF_TMPL,
    CONTEXT_PROJECT_TMPL,
    CONTEXT_SANITIZER_TMPL,
    PatcherAgentState,
    PatcherAgentName,
    PatcherAgentBase,
    ContextCodeSnippet,
    get_code_snippet_request_tmpl,
)
from buttercup.common.llm import ButtercupLLM, create_default_llm
from buttercup.patcher.utils import decode_bytes, get_diff_content
from langgraph.types import Command

logger = logging.getLogger(__name__)

ROOT_CAUSE_SYSTEM_TMPL = """You are a security engineer. Your job is to analyze the \
current project's code, a vulnerability description, and determine its root \
cause. The vulnerability is introduced/enabled in the specified diff and it was not \
present before that. Read the project's code and understand the issue.

You must NOT:
- provide generic recommendations
- provide overly generic root causes
- talk about possible issues that existed before the diff.
- provide code suggestions on how to fix the vulnerability
- make up code, contexts or information

You MUST:
- provide a detailed root cause analysis of the vulnerability, referencing actual code snippets
- describe a concrete and specific root cause
- focus ONLY on the issue introduced in the diff and ONLY on the issue \
reported in the sanitizer output. If there are multiple vulnerabilities in the \
diff, focus on the one which triggers the sanitizer
- look at the actual code snippets and the code context to understand the root cause, \
do not make up code, contexts or information and do not assume anything

If you need more context to understand the code, ask for more code snippets. Try \
to fully understand the issue by asking for more code snippets instead of \
rushing through an answer. For example, before looking at the code, review the \
fuzzer harness code to understand how the project's code is being used.

You can request multiple code snippets at once. Request code snippets in the
following way:

{code_snippet_request_tmpl}

You must use the above format to request code snippets.
"""
ROOT_CAUSE_SYSTEM_TMPL = ROOT_CAUSE_SYSTEM_TMPL.format(
    code_snippet_request_tmpl=get_code_snippet_request_tmpl(2),
)

DIFF_ANALYSIS_SYSTEM_TMPL = """You are a security engineer. Your job is to \
analyze a diff of a project and determine the vulnerability it introduces. The \
vulnerability is introduced in the specified diff and it was not present \
before that.

You MUST:
- provide a detailed analysis of the vulnerability introduced in the diff
- describe a concrete and specific problem
- focus ONLY on the issue introduced in the diff and ONLY on the issue \
reported in the sanitizer output. If there are multiple vulnerabilities in the \
diff, focus on the one which triggers the sanitizer

You must NOT:
- provide generic recommendations
- provide overly generic analyses
- talk about possible issues that existed before the diff.
- provide code suggestions on how to fix the vulnerability

If you need more context to understand the code, you can ask for more code
snippets. Try to fully understand the issue by asking for more code snippets
instead of rushing through an answer.

You can request multiple code snippets at once. Request code snippets in the
following way:

{code_snippet_request_tmpl}
"""
DIFF_ANALYSIS_SYSTEM_TMPL = DIFF_ANALYSIS_SYSTEM_TMPL.format(
    code_snippet_request_tmpl=get_code_snippet_request_tmpl(2),
)

ROOT_CAUSE_PROMPT = ChatPromptTemplate.from_messages(
    [
        ("system", ROOT_CAUSE_SYSTEM_TMPL),
        MessagesPlaceholder(variable_name="context"),
        MessagesPlaceholder(variable_name="messages", optional=True),
        ("user", "Provide a detailed and complete analysis"),
    ]
)

DIFF_ANALYSIS_PROMPT = ChatPromptTemplate.from_messages(
    [
        ("system", DIFF_ANALYSIS_SYSTEM_TMPL),
        MessagesPlaceholder(variable_name="context"),
        MessagesPlaceholder(variable_name="messages", optional=True),
        ("user", "Provide a detailed and complete analysis"),
    ]
)

OLD_DIFF_ANALYSIS_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "ai",
            """Diff analysis:
```
{diff_analysis}
```""",
        ),
        (
            "user",
            "I tried to fix the vulnerability according to the diff analysis you \
provided, but the Proof of Vulnerability (PoV) was still triggered. Please \
review your previous analysis and provide a new or an improved analysis to \
help me correctly fix the vulnerability.",
        ),
    ]
)

OLD_ROOT_CAUSE_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "ai",
            """Root cause analysis:
```
{root_cause}
```""",
        ),
        (
            "user",
            "I tried to fix the vulnerability according to the root cause you \
provided, but the Proof of Vulnerability (PoV) was still triggered. Please \
review your previous analysis and provide a new or an improved analysis to \
help me correctly fix the vulnerability.",
        ),
    ]
)

REDUCE_ANALYSES = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            "Please reduce the analyses to a single, detailed and \
complete, analysis that can be easily understood by another software \
engineer without other context.",
        ),
        ("user", "Previous analysis:\n```\n{previous_analysis}\n```"),
        ("user", "New analysis:\n```\n{new_analysis}\n```"),
    ]
)

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
    diff_analysis_chain: Runnable = field(init=False)
    diff_analysis_one_chain: Runnable = field(init=False)
    build_failure_analysis_chain: Runnable = field(init=False)
    encoding: tiktoken.Encoding = field(init=False)

    def __post_init__(self) -> None:
        """Initialize a few fields"""
        default_llm = create_default_llm(model_name=ButtercupLLM.OPENAI_GPT_4O.value)
        fallback_llms = [
            create_default_llm(model_name=ButtercupLLM.CLAUDE_3_5_SONNET.value),
        ]
        self.llm = default_llm.with_fallbacks(fallback_llms)

        self.root_cause_chain = ROOT_CAUSE_PROMPT | self.llm | StrOutputParser()
        self.diff_analysis_chain = DIFF_ANALYSIS_PROMPT | self.llm | StrOutputParser()
        self.diff_analysis_one_chain = RunnableBranch(
            (
                lambda x: x["diff_analysis"],
                {
                    "previous_analysis": itemgetter("diff_analysis"),
                    "new_analysis": self.diff_analysis_chain,
                }
                | REDUCE_ANALYSES
                | self.llm
                | StrOutputParser(),
            ),
            self.diff_analysis_chain,
        )
        self.build_failure_analysis_chain = BUILD_FAILURE_PROMPT | self.llm | StrOutputParser()

        self.encoding = tiktoken.encoding_for_model("gpt-4o")

    def get_diff_analysis_context(self, state: PatcherAgentState) -> list[BaseMessage | str]:
        """Get the messages for the diff analysis context."""

        messages: list[BaseMessage | str] = []
        messages += [CONTEXT_PROJECT_TMPL.format(project_name=self.challenge.name)]

        diff_content = get_diff_content(self.challenge)
        messages += [CONTEXT_DIFF_TMPL.format(diff_content=diff_content)]
        if state.context.sanitizer and state.context.sanitizer_output:
            messages += [
                CONTEXT_SANITIZER_TMPL.format(
                    sanitizer=state.context.sanitizer,
                    sanitizer_output=state.context.sanitizer_output,
                )
            ]

        return messages

    def get_root_cause_context(self, state: PatcherAgentState) -> list[BaseMessage | str]:
        """Get the messages for the root cause analysis context."""

        messages: list[BaseMessage | str] = []
        messages += [CONTEXT_PROJECT_TMPL.format(project_name=self.challenge.name)]

        if state.diff_analysis:
            messages += [CONTEXT_DIFF_ANALYSIS_TMPL.format(diff_analysis=state.diff_analysis)]

        if state.context.sanitizer and state.context.sanitizer_output:
            messages += [
                CONTEXT_SANITIZER_TMPL.format(
                    sanitizer=state.context.sanitizer,
                    sanitizer_output=state.context.sanitizer_output,
                )
            ]

        messages += self._get_relevant_code_snippets_msgs(state.relevant_code_snippets)
        return messages

    def diff_analysis(
        self, state: PatcherAgentState
    ) -> Command[Literal[PatcherAgentName.ROOT_CAUSE_ANALYSIS.value, PatcherAgentName.CONTEXT_RETRIEVER.value]]:
        """Analyze the diff to understand the vulnerability."""
        logger.info("Analyzing the diff in Challenge Task %s", self.challenge.name)
        messages = []
        if state.diff_analysis:
            messages += OLD_DIFF_ANALYSIS_PROMPT.format_messages(diff_analysis=state.diff_analysis)

        diff_analysis = self.chain_call(
            lambda x, y: x + y,
            self.diff_analysis_one_chain,
            {
                "context": self.get_diff_analysis_context(state),
                "messages": messages,
                "diff_analysis": state.diff_analysis,
            },
            default="",
        )
        if not diff_analysis:
            logger.error("Could not analyze the diff")
            raise ValueError("Could not analyze the diff")

        update_state = {
            "diff_analysis": diff_analysis,
            "root_cause": None,
        }
        goto, update_state = self.get_code_snippet_requests(
            diff_analysis,
            update_state,
            current_node=PatcherAgentName.DIFF_ANALYSIS.value,
            default_goto=PatcherAgentName.ROOT_CAUSE_ANALYSIS.value,
        )
        return Command(
            update=update_state,
            goto=goto,
        )

    def _parse_code_snippet_msg(self, msg: str) -> tuple[str, str, str]:
        """Parse the code snippet message."""
        # Extract code part from the message using regex
        code_pattern = re.compile(r"File path:.*?\nIdentifier:.*?\nCode:\n(.*?)$", re.DOTALL)
        code_match = code_pattern.search(msg)
        if code_match:
            code_block_pattern = re.compile(r"```(?:[a-z]+)?\s*(.*?)\s*```", re.DOTALL)
            code_block_match = code_block_pattern.search(code_match.group(1))
            if code_block_match:
                # Remove the code block markers
                msg = code_block_match.group(1).strip()
            else:
                # If we can't find the code block, just return the whole part after "Code:"
                msg = code_match.group(1).strip()

        return msg

    def _get_relevant_code_snippets_msgs(
        self, relevant_code_snippets: list[ContextCodeSnippet]
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

    def analyze_vulnerability(self, state: PatcherAgentState) -> Command[Literal[PatcherAgentName.CREATE_PATCH.value]]:
        """Analyze the diff analysis and the code to understand the
        vulnerability in the current code."""
        logger.info("Analyzing the vulnerability in Challenge Task %s", self.challenge.name)
        messages = []
        if state.root_cause:
            messages += OLD_ROOT_CAUSE_PROMPT.format_messages(root_cause=state.root_cause)

        root_cause = self.chain_call(
            lambda x, y: x + y,
            self.root_cause_chain,
            {
                "context": self.get_root_cause_context(state),
                "messages": messages,
            },
            default="",
        )
        if not root_cause:
            logger.error("Could not find the root cause of the vulnerability")
            raise ValueError("Could not find the root cause of the vulnerability")

        update_state = {
            "root_cause": root_cause,
            "patches": [],
            "build_succeeded": None,
            "pov_fixed": None,
            "tests_passed": None,
        }
        goto, update_state = self.get_code_snippet_requests(
            root_cause,
            update_state,
            current_node=PatcherAgentName.ROOT_CAUSE_ANALYSIS.value,
            default_goto=PatcherAgentName.CREATE_PATCH.value,
        )
        return Command(
            update=update_state,
            goto=goto,
        )

    def analyze_build_failure(self, state: PatcherAgentState) -> Command[Literal[PatcherAgentName.CREATE_PATCH.value]]:
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
            default="",
        )

        return Command(
            update={
                "build_analysis": build_analysis,
            },
            goto=PatcherAgentName.CREATE_PATCH.value,
        )
