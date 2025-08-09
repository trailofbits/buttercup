"""Software Engineer LLM agent, analyzing the root cause of a vulnerability."""

import logging
import re
from unidiff import PatchSet
import langgraph.errors
from typing import Annotated, Literal
from langgraph.prebuilt import InjectedState
from langchain_core.prompts import MessagesPlaceholder
from pydantic import BaseModel, ValidationError
from langchain_core.messages import BaseMessage
from langgraph.prebuilt import create_react_agent
from langchain_core.tools import tool
from dataclasses import dataclass, field
from buttercup.common.stack_parsing import parse_stacktrace
from langchain_core.prompts import (
    ChatPromptTemplate,
)
from buttercup.patcher.utils import truncate_output, TruncatePosition
from langchain_core.runnables import Runnable
from buttercup.patcher.agents.common import (
    PatcherAgentState,
    PatcherAgentName,
    PatcherAgentBase,
    ContextCodeSnippet,
    CodeSnippetRequest,
    get_stacktraces_from_povs,
    stacktrace_to_str,
    MAX_STACKTRACE_LENGTH,
)
from buttercup.common.llm import ButtercupLLM, create_default_llm_with_temperature
from langgraph.types import Command

logger = logging.getLogger(__name__)

MAX_DIFF_LENGTH = MAX_STACKTRACE_LENGTH

ROOT_CAUSE_SYSTEM_MSG = """You are PatchGen-LLM, an autonomous component in an end-to-end security-patching pipeline.
Goal: perform a Root Cause Analysis of one (or more) security vulnerabilities.
The Root Cause Analysis will be used by a downstream code-generation agent, so factual and structural accuracy are critical.
"""

ROOT_CAUSE_USER_MSG = """You are analyzing a security vulnerability in the following project:

<project_name>
{PROJECT_NAME}
</project_name>

If available, the vulnerability has been introduced/enabled by the following diff:
<vulnerability_diff>
{DIFF}
</vulnerability_diff>

You also have access to the following context:
<code_snippets>
{CODE_SNIPPETS}
</code_snippets>

The vulnerability has triggered one or more sanitizers, with the following stacktraces:
<stacktraces>
{STACKTRACES}
</stacktraces>

If there are multiple stacktraces, consider them as being different \
manifestations of the same vulnerability. In such cases, you should try as much \
as possible to discover the single real root cause of the vulnerabilities and \
not just the immediate symptoms.

{REFLECTION_GUIDANCE}

---

Your task is to produce a **precise, detailed Root Cause Analysis** of the vulnerability. Be rigorous and avoid speculation.

Request additional code snippets if they are *critical* to understand the root cause:
   - Exact failure location
   - Vulnerable control/data flow
   - Failed security checks
   
   To request additional code snippets, use the following format:
   ```
   <code_snippet_request>
   [Your detailed request for specific code, including file paths and line numbers if known]
   </code_snippet_request>
   ```
   You can include multiple requests by using multiple sets of these tags.

Guidelines:
* Stay focused on the vulnerability in the stack traces/crashes.
* Be specific and technically rigorous.
* Avoid general context unless it's essential to root cause.
* Don't request additional code unless it's clearly necessary.
* Your output must support a precise, targeted fix.
* Do not suggest code changes, only analyze the vulnerability.

Now proceed with your analysis.
"""

ROOT_CAUSE_PROMPT = ChatPromptTemplate.from_messages(
    [
        ("system", ROOT_CAUSE_SYSTEM_MSG),
        ("user", ROOT_CAUSE_USER_MSG),
        MessagesPlaceholder(variable_name="messages"),
    ]
)

REFLECTION_GUIDANCE_TMPL = """
You've received new guidance. Review it carefully and incorporate it fully into your analysis.

<reflection_guidance>
{REFLECTION_GUIDANCE}
</reflection_guidance>
"""


@dataclass
class RootCauseAgent(PatcherAgentBase):
    """Software Engineer LLM agent, triaging a vulnerability."""

    llm: Runnable = field(init=False)
    root_cause_chain: Runnable = field(init=False)

    def __post_init__(self) -> None:
        """Initialize a few fields"""
        kwargs = {
            "temperature": 1,
            "max_tokens": 20000,
        }
        default_llm = create_default_llm_with_temperature(
            model_name=ButtercupLLM.OPENAI_GPT_4_1.value,
            **kwargs,
        )
        fallback_llms = [
            create_default_llm_with_temperature(
                model_name=ButtercupLLM.CLAUDE_3_7_SONNET.value,
                **kwargs,
            ),
        ]
        self.llm = default_llm.with_fallbacks(fallback_llms)

        @tool(description=self._understand_code_snippet.__doc__)
        def understand_code_snippet(
            code_snippet_id: str, focus_area: str, *, state: Annotated[BaseModel, InjectedState]
        ) -> str:
            assert isinstance(state, PatcherAgentState)
            return self._understand_code_snippet(state, code_snippet_id, focus_area)

        @tool(description=self._list_diffs.__doc__)
        def list_diffs() -> str:
            return self._list_diffs()

        @tool(description=self._get_diffs.__doc__)
        def get_diffs(diff_file_paths: list[str]) -> str:
            return self._get_diffs(diff_file_paths)

        tools = [
            understand_code_snippet,
            list_diffs,
            get_diffs,
        ]
        default_agent = create_react_agent(
            model=default_llm,
            state_schema=PatcherAgentState,
            tools=tools,
            prompt=self._root_cause_prompt,
        )
        fallback_agents = [
            create_react_agent(
                model=llm,
                state_schema=PatcherAgentState,
                tools=tools,
                prompt=self._root_cause_prompt,
            )
            for llm in fallback_llms
        ]

        self.root_cause_chain = default_agent.with_fallbacks(fallback_agents)

    def _root_cause_prompt(self, state: PatcherAgentState) -> list[BaseMessage]:
        diff_content = "\n".join(diff.read_text() for diff in self.challenge.get_diffs())
        # Truncate diff content to the same as max stacktrace length
        diff_content = truncate_output(diff_content, max_length=MAX_DIFF_LENGTH, truncate_position=TruncatePosition.END)
        stacktraces = [parse_stacktrace(pov.sanitizer_output) for pov in state.context.povs]
        stacktraces_strs = get_stacktraces_from_povs(state.context.povs)

        last_patch_attempt = state.get_last_patch_attempt()
        if last_patch_attempt and not last_patch_attempt.pov_fixed:
            sanitizer_output = last_patch_attempt.pov_stdout.decode("utf-8") if last_patch_attempt.pov_stdout else ""
            sanitizer_output += last_patch_attempt.pov_stderr.decode("utf-8") if last_patch_attempt.pov_stderr else ""
            stacktraces_strs.append(stacktrace_to_str("", sanitizer_output))

        stacktraces_str = "\n".join(stacktraces_strs)

        return ROOT_CAUSE_PROMPT.format_messages(
            DIFF=diff_content,
            PROJECT_NAME=self.challenge.project_name,
            STACKTRACES=stacktraces_str,
            CODE_SNIPPETS="\n".join([cs.commented_code(stacktraces) for cs in state.relevant_code_snippets]),
            REFLECTION_GUIDANCE=self._get_reflection_guidance_prompt(state),
            messages=state.messages,
        )

    def _get_reflection_guidance_prompt(self, state: PatcherAgentState) -> str:
        if state.execution_info.reflection_decision == PatcherAgentName.ROOT_CAUSE_ANALYSIS:
            return REFLECTION_GUIDANCE_TMPL.format(REFLECTION_GUIDANCE=state.execution_info.reflection_guidance)

        return ""

    def _comment_code_snippet(
        self, state: PatcherAgentState, stacktrace_lines: list[tuple[str, int]], code_snippet: ContextCodeSnippet
    ) -> str:
        """Return the string representation of the code snippet with the line numbers."""
        code = []
        for lineno, line in enumerate(code_snippet.code.split("\n"), start=code_snippet.start_line):
            if (code_snippet.key.file_path, lineno) in stacktrace_lines:
                code.append(f"{line} // LINE {lineno} | CRASH INFO")
            else:
                code.append(line)

        return f"""<code_snippet>
<identifier>{code_snippet.key.identifier}</identifier>
<file_path>{code_snippet.key.file_path}</file_path>
<description>{code_snippet.description}</description>
<start_line>{code_snippet.start_line}</start_line>
<end_line>{code_snippet.end_line}</end_line>
<code>
{"\n".join(code)}
</code>
</code_snippet>
"""

    def _parse_code_snippet_requests(self, root_cause_str: str) -> list[CodeSnippetRequest]:
        """Parse the code snippet requests from the root cause string."""

        requests = []
        pattern = r"<code_snippet_request>(.*?)</code_snippet_request>"
        matches = re.findall(pattern, root_cause_str, re.DOTALL)
        for match in matches:
            requests.append(CodeSnippetRequest(request=match.strip()))
        return requests

    def _list_diffs(self) -> str:
        """List the available diff files for the code under analysis.

        This function returns the list of diff files that were applied to the code under analysis.
        Each diff file contains one or several patches, applied to one or several source files.
        This function doesn't return the actual diff content. In order to retrieve the diff content
        you must use the `get_diffs` tool with the diff file path(s) to get the diff contents of
        those files.

        Below is an example of the output format:

        <diff_files>
        <diff_file>
            <diff_file_path>path/to/diff/file.patch</diff_file_path>
            <modified_file>
                <file_path>path/to/file.c</file_path>
                <modified_lines_range>
                    <start_line>10</start_line>
                    <end_line>25</end_line>
                </modified_lines_range>
                <modified_lines_range>
                    <start_line>226</start_line>
                    <end_line>230</end_line>
                </modified_lines_range>
            </modified_file>
            <modified_file>
                <file_path>path/to/file2.c</file_path>
                <modified_lines_range>
                    <start_line>10</start_line>
                    <end_line>25</end_line>
                </modified_lines_range>
            </modified_file>
        </diff_file>
        </diff_files>

                Args:
                    This function takes no arguments.

                Returns:
                    The list of diffs that were applied to the code under analysis.
                    Actual diff content must then be retrieved using the `get_diffs` tool.
        """
        diff_list = []
        for diff_file_path in self.challenge.get_diffs():
            diff_text = diff_file_path.read_text()
            # Parse raw diff to get file and lines
            parsed_diff = get_modified_line_ranges(diff_text)
            for file_path, line_ranges in parsed_diff:
                diff_list.append(
                    f"""<diff_file>
<diff_file_path>{diff_file_path}</diff_file_path>
<modified_file>
  <file_path>{file_path}</file_path>
  <modified_lines_range>
    {"\n".join([f"<start_line>{start_line}</start_line><end_line>{end_line}</end_line>" for start_line, end_line in line_ranges])}
  </modified_lines_range>
</modified_file>
</diff_file>
"""
                )
        return f"<diff_files>\n{'\n'.join(diff_list)}\n</diff_files>"

    def _get_diffs(self, diff_file_paths: list[str]) -> str:
        """Get the diff content for given diff files.

        This function returns the diff content for diffs that have been applied to the code under analysis.
        This functions accepts a list of diff file paths, and returns the diff content of all these diff files.
        The diff file paths must correspond to diff file paths listed by the `list_diffs` tool.

        In order to use this function, you should first call the `list_diffs` tool to get the list of diff files and
        see information about the patches they contain (modified files and line ranges). Then decide which
        diffs are relevant and retrieve their actual content using this function.

        Args:
            diff_file_paths: A list of diff file paths to retrieve the diff content for.

        Returns:
            A string containing the diff content for the given diff file paths.
        """
        diff_text = ""
        for diff_path in self.challenge.get_diffs():
            if str(diff_path) in diff_file_paths:
                diff_text += diff_path.read_text() + "\n"
        return diff_text

    def analyze_vulnerability(
        self, state: PatcherAgentState
    ) -> Command[Literal[PatcherAgentName.PATCH_STRATEGY.value, PatcherAgentName.REFLECTION.value]]:  # type: ignore[name-defined]
        """Analyze the diff analysis and the code to understand the
        vulnerability in the current code."""
        logger.info(
            "[%s / %s] Analyzing the vulnerability in Challenge Task %s",
            state.context.task_id,
            state.context.internal_patch_id,
            self.challenge.name,
        )

        execution_info = state.execution_info
        execution_info.prev_node = PatcherAgentName.ROOT_CAUSE_ANALYSIS

        try:
            root_cause_dict = self.root_cause_chain.invoke(state)
        except langgraph.errors.GraphRecursionError:
            logger.error(
                "Reached recursion limit for root cause analysis in Challenge Task %s/%s",
                state.context.task_id,
                self.challenge.name,
            )
            return Command(
                update={
                    "execution_info": execution_info,
                },
                goto=PatcherAgentName.REFLECTION.value,
            )
        except Exception as e:
            logger.exception("Error parsing root cause: %s", e)
            return Command(
                update={
                    "execution_info": execution_info,
                },
                goto=PatcherAgentName.REFLECTION.value,
            )

        try:
            root_cause_state = PatcherAgentState.model_validate(root_cause_dict)
            if not root_cause_state.messages:
                raise ValidationError("No messages in root cause state")
        except ValidationError as e:
            logger.exception("Error parsing root cause: %s", e)
            return Command(
                update={
                    "execution_info": execution_info,
                },
                goto=PatcherAgentName.REFLECTION.value,
            )

        root_cause_str = str(root_cause_state.messages[-1].content)
        if "<code_snippet_requests>" in root_cause_str:
            requests = self._parse_code_snippet_requests(root_cause_str)
            execution_info.code_snippet_requests = requests
            return Command(
                update={
                    "execution_info": execution_info,
                },
                goto=PatcherAgentName.REFLECTION.value,
            )

        return Command(
            update={
                "root_cause": root_cause_str,
            },
            goto=PatcherAgentName.PATCH_STRATEGY.value,
        )


def get_modified_line_ranges(diff_text: str) -> list[tuple[str, list[tuple[int, int]]]]:
    """
    Extract file paths and modified line ranges.

    Args:
        diff_text (str): Raw unidiff patch as a string

    Returns:
        List[Tuple[str, List[Tuple[int, int]]]]: List of (file_path, [(start, end), ...])
    """
    patch = PatchSet(diff_text)
    results: list[tuple[str, list[tuple[int, int]]]] = []

    for patched_file in patch:
        ranges = [(hunk.target_start, hunk.target_start + hunk.target_length - 1) for hunk in patched_file]
        results.append((patched_file.path, ranges))

    return results
