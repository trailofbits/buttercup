"""Software Engineer LLM agent, analyzing the root cause of a vulnerability."""

import functools
import logging
from dataclasses import dataclass, field
from operator import itemgetter

import tiktoken
from buttercup.common.challenge_task import ChallengeTask
from buttercup.patcher.context import ContextCodeSnippet
from langchain.output_parsers import BooleanOutputParser
from langchain_core.messages import BaseMessage
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import (
    ChatPromptTemplate,
    MessagesPlaceholder,
)
from langchain_core.runnables import Runnable, RunnableBranch
from buttercup.patcher.agents.common import (
    CONTEXT_CODE_SNIPPET_TMPL,
    CONTEXT_COMMIT_ANALYSIS_TMPL,
    CONTEXT_COMMIT_TMPL,
    CONTEXT_EXTRA_CODE_TMPL,
    CONTEXT_PROJECT_TMPL,
    CONTEXT_SANITIZER_TMPL,
    FilterSnippetState,
    PatcherAgentState,
)
from buttercup.common.llm import ButtercupLLM, create_default_llm, create_llm
from buttercup.patcher.utils import VALID_PATCH_EXTENSIONS, decode_bytes

logger = logging.getLogger(__name__)

ROOT_CAUSE_SYSTEM_TMPL = """You are a security engineer. Your job is to analyze the \
vulnerability and determine its root cause. The vulnerability is introduced in \
the specified commit and it was not present before that.

You MUST:
- provide a detailed root cause analysis of the vulnerability
- describe a concrete and specific root cause
- focus ONLY on the issue introduced in the commit and ONLY on the issue \
reported in the sanitizer output. If there are multiple vulnerabilities in the \
commit, focus on the one which triggers the sanitizer
- assume the "Vulnerable Code" and "Extra Context" sections have more up to date \
content than the commit

You must NOT:
- provide generic recommendations
- provide overly generic root causes
- talk about possible issues that existed before the commit.
- provide code suggestions on how to fix the vulnerability
"""

COMMIT_ANALYSIS_SYSTEM_TMPL = """You are a security engineer. Your job is to \
analyze a commit of a project and determine the vulnerability it introduces. The \
vulnerability is introduced in the specified commit and it was not present \
before that.

You MUST:
- provide a detailed analysis of the vulnerability introduced in the commit
- describe a concrete and specific problem
- focus ONLY on the issue introduced in the commit and ONLY on the issue \
reported in the sanitizer output. If there are multiple vulnerabilities in the \
commit, focus on the one which triggers the sanitizer

You must NOT:
- provide generic recommendations
- provide overly generic analyses
- talk about possible issues that existed before the commit.
- provide code suggestions on how to fix the vulnerability
"""

FILTER_CODE_SNIPPET_SYSTEM_TMPL = """You are a Software Security Engineer. Your \
job is to help fix a vulnerability in a project, by deciding whether a snippet \
of code likely needs to be fixed or not. You should help another Software \
Engineer by reducing the scope of changes she needs to analyze and understand.

You are given the details about the code snippet and the vulnerability/commit analysis. \
You should consider the code snippet in the context of the vulnerability and \
consider it in-scope only if it's useful to fix the vulnerability. \
If not sure about a code snippet, lean towards considering it for a possible fix. \
Provide a thorough explanation of your reasoning.
"""

FILTER_CODE_SNIPPET_BOOL_SYSTEM_TMPL = """You are a Software Security Engineer. \
You are given a detailed reasoning of whether a code snippet should be \
considered fox fixing or not.

Answer YES if the code snippet should be considered for fixing, NO otherwise. \
Answer only with YES/NO.
"""

ROOT_CAUSE_PROMPT = ChatPromptTemplate.from_messages(
    [
        ("system", ROOT_CAUSE_SYSTEM_TMPL),
        MessagesPlaceholder(variable_name="context"),
        MessagesPlaceholder(variable_name="messages", optional=True),
        ("user", "Provide a detailed and complete analysis"),
    ]
)

COMMIT_ANALYSIS_PROMPT = ChatPromptTemplate.from_messages(
    [
        ("system", COMMIT_ANALYSIS_SYSTEM_TMPL),
        MessagesPlaceholder(variable_name="context"),
        MessagesPlaceholder(variable_name="messages", optional=True),
        ("user", "Provide a detailed and complete analysis"),
    ]
)

FILTER_CODE_SNIPPET_PROMPT = ChatPromptTemplate.from_messages(
    [
        ("system", FILTER_CODE_SNIPPET_SYSTEM_TMPL),
        MessagesPlaceholder(variable_name="context"),
        ("user", CONTEXT_CODE_SNIPPET_TMPL),
    ]
)

FILTER_CODE_SNIPPET_BOOL_PROMPT = ChatPromptTemplate.from_messages(
    [
        ("system", FILTER_CODE_SNIPPET_BOOL_SYSTEM_TMPL),
        ("user", "Analysis:\n```\n{analysis}\n```\n"),
    ]
)


OLD_COMMIT_ANALYSIS_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "ai",
            """Commit analysis:
```
{commit_analysis}
```""",
        ),
        (
            "user",
            "I tried to fix the vulnerability according to the commit analysis you \
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
class RootCauseAgent:
    """Software Engineer LLM agent, handling the creation of patches."""

    challenge: ChallengeTask
    llm: Runnable = field(init=False)
    root_cause_chain: Runnable = field(init=False)
    commit_analysis_chain: Runnable = field(init=False)
    commit_analysis_one_chain: Runnable = field(init=False)
    filter_code_snippet_chain: Runnable = field(init=False)
    filter_code_snippet_bool_chain: Runnable = field(init=False)
    build_failure_analysis_chain: Runnable = field(init=False)
    encoding: tiktoken.Encoding = field(init=False)

    def __post_init__(self) -> None:
        """Initialize a few fields"""
        default_llm = create_default_llm()
        fallback_llms = [
            create_llm(model_name=ButtercupLLM.AZURE_GPT_4O_MINI.value),
        ]
        self.llm = default_llm.with_fallbacks(fallback_llms)

        self.root_cause_chain = ROOT_CAUSE_PROMPT | self.llm | StrOutputParser()
        self.commit_analysis_chain = COMMIT_ANALYSIS_PROMPT | self.llm | StrOutputParser()
        self.commit_analysis_one_chain = RunnableBranch(
            (
                lambda x: x["commit_analysis"],
                {
                    "previous_analysis": itemgetter("commit_analysis"),
                    "new_analysis": self.commit_analysis_chain,
                }
                | REDUCE_ANALYSES
                | self.llm
                | StrOutputParser(),
            ),
            self.commit_analysis_chain,
        )
        self.filter_code_snippet_chain = FILTER_CODE_SNIPPET_PROMPT | self.llm | StrOutputParser()
        self.filter_code_snippet_bool_chain = (
            {"analysis": self.filter_code_snippet_chain}
            | FILTER_CODE_SNIPPET_BOOL_PROMPT
            | self.llm
            | BooleanOutputParser()
        )
        self.build_failure_analysis_chain = BUILD_FAILURE_PROMPT | self.llm | StrOutputParser()

        self.encoding = tiktoken.encoding_for_model("gpt-4o")

    def get_commit_analysis_context(self, state: PatcherAgentState) -> list[BaseMessage | str]:
        """Get the messages for the commit analysis context."""

        messages: list[BaseMessage | str] = []
        messages += [CONTEXT_PROJECT_TMPL.format(project_name=self.challenge.name)]

        # TODO: add API to get list of diffs
        diff_content = next(self.challenge.get_diff_path().rglob("*.diff")).read_text()
        messages += [CONTEXT_COMMIT_TMPL.format(commit_content=diff_content)]
        if state["context"].get("sanitizer") and state["context"].get("sanitizer_output"):
            messages += [
                CONTEXT_SANITIZER_TMPL.format(
                    sanitizer=state["context"]["sanitizer"],
                    sanitizer_output=state["context"]["sanitizer_output"].decode(
                        "utf-8", errors="ignore"
                    ),
                )
            ]
        if state["context"].get("vulnerable_functions"):
            for code_snippet in state["context"]["vulnerable_functions"]:
                code_context = code_snippet.get("code_context", "")
                if code_context.strip():
                    n_tokens_extra = len(self.encoding.encode(code_context))
                    if n_tokens_extra > 5000:
                        logger.warning(
                            "Code snippet %s | %s context is too large (%d tokens), truncating it",
                            code_snippet["file_path"],
                            code_snippet["function_name"],
                            n_tokens_extra,
                        )
                        code_context = (
                            self.encoding.decode(self.encoding.encode(code_context)[:1000])
                            + "\n\n[...]\n\n"
                            + self.encoding.decode(self.encoding.encode(code_context)[-1000:])
                        )

                    messages += [CONTEXT_EXTRA_CODE_TMPL.format(code_context=code_context)]

        return messages

    def get_filter_snippet_context(self, state: FilterSnippetState) -> list[BaseMessage | str]:
        """Get the messages for the root cause analysis context."""

        messages: list[BaseMessage | str] = []
        messages += [CONTEXT_PROJECT_TMPL.format(project_name=self.challenge.name)]

        if state.get("commit_analysis"):
            messages += [
                CONTEXT_COMMIT_ANALYSIS_TMPL.format(commit_analysis=state["commit_analysis"])
            ]

        if state["context"].get("sanitizer") and state["context"].get("sanitizer_output"):
            messages += [
                CONTEXT_SANITIZER_TMPL.format(
                    sanitizer=state["context"]["sanitizer"],
                    sanitizer_output=state["context"]["sanitizer_output"].decode(
                        "utf-8", errors="ignore"
                    ),
                )
            ]

        return messages

    def get_root_cause_context(self, state: PatcherAgentState) -> list[BaseMessage | str]:
        """Get the messages for the root cause analysis context."""

        messages: list[BaseMessage | str] = []
        messages += [CONTEXT_PROJECT_TMPL.format(project_name=self.challenge.name)]

        if state.get("commit_analysis"):
            messages += [
                CONTEXT_COMMIT_ANALYSIS_TMPL.format(commit_analysis=state["commit_analysis"])
            ]

        if state["context"].get("sanitizer") and state["context"].get("sanitizer_output"):
            messages += [
                CONTEXT_SANITIZER_TMPL.format(
                    sanitizer=state["context"]["sanitizer"],
                    sanitizer_output=state["context"]["sanitizer_output"].decode(
                        "utf-8", errors="ignore"
                    ),
                )
            ]

        messages += self._get_relevant_code_snippets_msgs(state["relevant_code_snippets"] or [])
        return messages

    def commit_analysis(self, state: PatcherAgentState) -> dict:
        """Analyze the commit diff to understand the vulnerability."""
        logger.info("Analyzing the commit diff in Challenge Task %s", self.challenge.name)
        messages = []
        if state.get("commit_analysis"):
            messages += OLD_COMMIT_ANALYSIS_PROMPT.format_messages(
                commit_analysis=state["commit_analysis"]
            )

        # We use the stream API to avoid hitting the LLM limits for large
        # messages which may require a while to generate.
        commit_analysis = functools.reduce(
            lambda x, y: x + y,
            self.commit_analysis_one_chain.stream(
                {
                    "context": self.get_commit_analysis_context(state),
                    "messages": messages,
                    "commit_analysis": state.get("commit_analysis"),
                }
            ),
            "",
        )
        if not commit_analysis:
            logger.error("Could not analyze the commit diff")
            raise ValueError("Could not analyze the commit diff")

        return {
            "commit_analysis": commit_analysis,
            "root_cause": None,
        }

    def _get_relevant_code_snippets_msgs(
        self, relevant_code_snippets: list[ContextCodeSnippet]
    ) -> list[BaseMessage | str]:
        messages: list[BaseMessage | str] = []
        for code_snippet in relevant_code_snippets:
            messages += [
                CONTEXT_CODE_SNIPPET_TMPL.format(
                    file_path=code_snippet["file_path"],
                    code=code_snippet.get("code", ""),
                    function_name=code_snippet.get("function_name", ""),
                    code_context=code_snippet.get("code_context", ""),
                )
            ]

        return messages

    def analyze_vulnerability(self, state: PatcherAgentState) -> dict:
        """Analyze the commit analysis and the code to understand the
        vulnerability in the current code."""
        logger.info("Analyzing the vulnerability in Challenge Task %s", self.challenge.name)
        messages = []
        if state.get("root_cause"):
            messages += OLD_ROOT_CAUSE_PROMPT.format_messages(root_cause=state["root_cause"])

        # We use the stream API to avoid hitting the LLM limits for large
        # messages which may require a while to generate.
        root_cause = functools.reduce(
            lambda x, y: x + y,
            self.root_cause_chain.stream(
                {
                    "context": self.get_root_cause_context(state),
                    "messages": messages,
                }
            ),
            "",
        )
        if not root_cause:
            logger.error("Could not find the root cause of the vulnerability")
            raise ValueError("Could not find the root cause of the vulnerability")

        return {
            "root_cause": root_cause,
            "patches": None,
            "build_succeeded": None,
            "pov_fixed": None,
            "tests_passed": None,
        }

    def _do_filter_code_snippet(self, state: FilterSnippetState, vc: ContextCodeSnippet) -> bool:
        try:
            include_code_snippet = functools.reduce(
                lambda _, y: y,
                self.filter_code_snippet_bool_chain.stream(
                    {
                        "context": self.get_filter_snippet_context(state),
                        "code": vc["code"],
                        "code_context": vc["code_context"],
                        "function_name": vc["function_name"],
                        "file_path": vc["file_path"],
                    }
                ),
                True,
            )
        except Exception:
            logger.warning("Error while filtering code snippet")
            if logger.getEffectiveLevel() == logging.DEBUG:
                logger.exception("Error while filtering code snippet")

            include_code_snippet = False

        return include_code_snippet

    def filter_code_snippet_node(self, state: FilterSnippetState) -> dict:
        """Filter a code snippet to decide if it needs to be fixed."""
        vc = state["code_snippet"]
        if vc.get("function_name") is None or vc.get("code") is None:
            logger.error("Code snippet is missing function name or code")
            return {"relevant_code_snippets": []}

        logger.info("Filtering code snippet in %s | %s", vc["file_path"], vc["function_name"])

        code_context = vc.get("code_context", "")
        code = vc["code"]

        n_tokens_code = len(self.encoding.encode(vc["code"]))
        n_tokens_extra = len(self.encoding.encode(code_context))

        if n_tokens_extra > 5000:
            logger.warning(
                "Code snippet %s | %s context is too large (%d tokens), truncating it",
                vc["file_path"],
                vc["function_name"],
                n_tokens_extra,
            )
            code_context = (
                self.encoding.decode(self.encoding.encode(code_context)[:1000])
                + "\n[...]\n"
                + self.encoding.decode(self.encoding.encode(code_context)[-1000:])
            )

        if n_tokens_code > 5000:
            logger.warning(
                "Code snippet %s | %s is too large (%d tokens)",
                vc["file_path"],
                vc["function_name"],
                n_tokens_code,
            )
            if not vc["file_path"].endswith(VALID_PATCH_EXTENSIONS):
                logger.warning("Code snippet %s | %s is not a valid extension, removing...")
                return {"relevant_code_snippets": []}

            code = (
                self.encoding.decode(self.encoding.encode(vc["code"])[:1000])
                + "\n\n[...]\n\n"
                + self.encoding.decode(self.encoding.encode(vc["code"])[-1000:])
            )
            logger.warning(
                "Code snippet %s | %s is too large (%d tokens), truncating it",
                vc["file_path"],
                vc["function_name"],
                n_tokens_code,
            )

        include_code_snippet = self._do_filter_code_snippet(
            state,
            {
                "file_path": vc["file_path"],
                "code": code,
                "function_name": vc["function_name"],
                "code_context": code_context,
            },
        )
        if not include_code_snippet:
            logger.info("Code snippet %s | %s filtered out", vc["file_path"], vc["function_name"])
            return {"relevant_code_snippets": []}

        return {
            "relevant_code_snippets": [
                ContextCodeSnippet(
                    file_path=vc["file_path"],
                    code=vc["code"].rstrip("\n") + ("\n" if vc["code"].endswith("\n") else ""),
                    function_name=vc["function_name"],
                    code_context=code_context,
                )
            ]
        }

    def analyze_build_failure(self, state: PatcherAgentState) -> dict:
        """Analyze the build failure to understand the issue and suggest a fix."""
        logger.info("Analyzing the build failure in Challenge Task %s", self.challenge.name)
        code_snippets = self._get_relevant_code_snippets_msgs(state["relevant_code_snippets"] or [])
        build_analysis: str = functools.reduce(
            lambda x, y: x + y,
            self.build_failure_analysis_chain.stream(
                {
                    "code_snippets": code_snippets,
                    "patch": state["patches"][-1].patch_content,
                    "build_stdout": decode_bytes(state.get("build_stdout")),
                    "build_stderr": decode_bytes(state.get("build_stderr")),
                }
            ),
            "",
        )

        return {
            "build_analysis": build_analysis,
        }
