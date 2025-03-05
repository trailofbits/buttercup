"""Software Engineer LLM agent, analyzing the root cause of a vulnerability."""

import logging
import subprocess
import re
from typing import Literal
from dataclasses import dataclass, field
from operator import itemgetter
from langchain_core.tools import tool
from langgraph.prebuilt import create_react_agent

import tiktoken
from buttercup.program_model.api.tree_sitter import CodeTS
from buttercup.patcher.context import ContextCodeSnippet
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
    CONTEXT_EXTRA_CODE_TMPL,
    CONTEXT_PROJECT_TMPL,
    CONTEXT_SANITIZER_TMPL,
    PatcherAgentState,
    PatcherAgentName,
    PatcherAgentBase,
)
from buttercup.common.llm import ButtercupLLM, create_default_llm, create_llm
from buttercup.patcher.utils import decode_bytes
from langgraph.types import Command

logger = logging.getLogger(__name__)

ROOT_CAUSE_CODE_SNIPPET_REQUEST_TMPL = """File path: <file_path{i}>
Function name: <function_name{i}>
"""
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
rushing through an answer.

You can request multiple code snippets at once. Request code snippets in the
following way:

```
# CODE SNIPPET REQUESTS:

{root_cause_code_snippet_request_tmpl}

[...]
```

You must use the above format to request code snippets.
"""
ROOT_CAUSE_SYSTEM_TMPL = ROOT_CAUSE_SYSTEM_TMPL.format(
    root_cause_code_snippet_request_tmpl="\n".join(
        ROOT_CAUSE_CODE_SNIPPET_REQUEST_TMPL.format(i=i) for i in range(1, 3)
    )
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

```
# CODE SNIPPET REQUESTS:

File path: <file_path1>
Function name: <function_name1>

File path: <file_path2>
Function name: <function_name2>

[...]
```
"""

CONTEXT_RETRIEVER_SYSTEM_TMPL = """You are a software engineer. Your job is to retrieve the code snippets requested by the user.
You must use the tools provided to you to retrieve the code snippets.

Do not stop until you have retrieved the code definition of the function.
Use `get_function_definition` as the last tool in your chain of calls to actually retrieve the code definition.
"""

CONTEXT_RETRIEVER_RECURSION_LIMIT = 20

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
        default_llm = create_default_llm()
        fallback_llms = [
            create_llm(model_name=ButtercupLLM.OPENAI_GPT_4O_MINI.value),
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

        # TODO: add support for multiple diffs if necessary
        diff_content = next(iter(self.challenge.get_diffs())).read_text()

        messages += [CONTEXT_DIFF_TMPL.format(diff_content=diff_content)]
        if state.context.sanitizer and state.context.sanitizer_output:
            messages += [
                CONTEXT_SANITIZER_TMPL.format(
                    sanitizer=state.context.sanitizer,
                    sanitizer_output=state.context.sanitizer_output,
                )
            ]
        if state.context.vulnerable_functions:
            for code_snippet in state.context.vulnerable_functions:
                code_context = code_snippet.code_context
                if code_context.strip():
                    n_tokens_extra = len(self.encoding.encode(code_context))
                    if n_tokens_extra > 5000:
                        logger.warning(
                            "Code snippet %s | %s context is too large (%d tokens), truncating it",
                            code_snippet.file_path,
                            code_snippet.function_name,
                            n_tokens_extra,
                        )
                        code_context = (
                            self.encoding.decode(self.encoding.encode(code_context)[:1000])
                            + "\n\n[...]\n\n"
                            + self.encoding.decode(self.encoding.encode(code_context)[-1000:])
                        )

                    messages += [CONTEXT_EXTRA_CODE_TMPL.format(code_context=code_context)]

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
        goto, requests_state = self.get_code_snippet_requests(
            diff_analysis,
            current_node=PatcherAgentName.DIFF_ANALYSIS.value,
            default_goto=PatcherAgentName.ROOT_CAUSE_ANALYSIS.value,
        )
        update_state.update(requests_state)
        return Command(
            update=update_state,
            goto=goto,
        )

    def _parse_code_snippet_msg(self, msg: str) -> tuple[str, str, str]:
        """Parse the code snippet message."""
        # Extract code part from the message using regex
        code_pattern = re.compile(r"File path:.*?\nFunction name:.*?\nCode:\n(.*?)$", re.DOTALL)
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

    def context_retriever(self, state: PatcherAgentState) -> Command:
        """Retrieve the context for the diff analysis."""
        logger.info("Retrieving the context for the diff analysis in Challenge Task %s", self.challenge.name)
        logger.debug("Code snippet requests: %s", state.code_snippet_requests)

        code_ts = CodeTS(self.challenge)

        @tool
        def ls(path: str) -> str:
            """List the files in the given path in the project's source directory."""
            path = self.rebase_src_path(path)

            logger.info("Listing files in %s", path)
            return subprocess.check_output(["ls", "-l", path], cwd=self.challenge.get_source_path()).decode("utf-8")

        @tool
        def grep(path: str, pattern: str) -> str:
            """Grep for a string in a file. Prefer using this tool over cat."""
            path = self.rebase_src_path(path)

            logger.info("Searching for %s in %s", pattern, path)
            return subprocess.check_output(["grep", "-nr", pattern, path], cwd=self.challenge.get_source_path()).decode(
                "utf-8"
            )

        @tool
        def cat(path: str) -> str:
            """Read the contents of a file. Use this tool only if grep and get_lines do not work as it might return a large amount of text."""
            path = self.rebase_src_path(path)

            logger.info("Reading contents of %s", path)
            return self.challenge.get_source_path().joinpath(path).read_text()

        @tool
        def get_lines(path: str, start: int, end: int) -> str:
            """Get a range of lines from a file. Prefer using this tool over cat."""
            path = self.rebase_src_path(path)

            logger.info("Getting lines %d-%d of %s", start, end, path)
            return "\n".join(self.challenge.get_source_path().joinpath(path).read_text().splitlines()[start:end])

        @tool(return_direct=True)
        def get_function_definition(path: str, function_name: str) -> str:
            """Get the definition of a function in a file. You MUST use this tool as the last call in your chain of calls."""
            path = self.rebase_src_path(path)

            logger.info("Getting definition of %s in %s", function_name, path)
            bodies = code_ts.get_function_code(path, function_name)
            if not bodies:
                return "No definition found for function"

            # TODO: allow for multiple bodies
            return bodies[0]

        tools = [ls, grep, get_lines, cat, get_function_definition]
        agent = create_react_agent(
            self.llm,
            tools,
            prompt=CONTEXT_RETRIEVER_SYSTEM_TMPL,
        )

        res = []
        for request in state.code_snippet_requests:
            logger.info("Retrieving code snippet for %s | %s", request.file_path, request.function_name)
            snippet = agent.invoke(
                {
                    "messages": [
                        ("human", f"Please retrieve the code snippet for {request.file_path} | {request.function_name}")
                    ]
                },
                {
                    "recursion_limit": CONTEXT_RETRIEVER_RECURSION_LIMIT,
                },
            )
            logger.info("Code snippet retrieved for %s | %s", request.file_path, request.function_name)
            msg = snippet["messages"][-1].content
            code = self._parse_code_snippet_msg(msg)

            res.append(
                ContextCodeSnippet(
                    file_path=request.file_path,
                    function_name=request.function_name,
                    code=code,
                    code_context="",
                )
            )

        return Command(
            update={
                "relevant_code_snippets": res,
                "code_snippet_requests": [],
            },
            goto=state.prev_node,
        )

    def _get_relevant_code_snippets_msgs(
        self, relevant_code_snippets: list[ContextCodeSnippet]
    ) -> list[BaseMessage | str]:
        messages: list[BaseMessage | str] = []
        for code_snippet in relevant_code_snippets:
            messages += [
                CONTEXT_CODE_SNIPPET_TMPL.format(
                    file_path=code_snippet.file_path,
                    code=code_snippet.code,
                    function_name=code_snippet.function_name,
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
            "build_succeeded": False,
            "pov_fixed": False,
            "tests_passed": False,
        }
        goto, requests_state = self.get_code_snippet_requests(
            root_cause,
            current_node=PatcherAgentName.ROOT_CAUSE_ANALYSIS.value,
            default_goto=PatcherAgentName.CREATE_PATCH.value,
        )
        update_state.update(requests_state)
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
