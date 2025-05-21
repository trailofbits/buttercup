"""Software Engineer LLM agent, analyzing the root cause of a vulnerability."""

import logging
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
from langchain_core.runnables import Runnable, RunnableConfig
from buttercup.patcher.agents.common import (
    PatcherAgentState,
    PatcherAgentName,
    PatcherAgentBase,
    RootCauseAnalysis,
    ContextCodeSnippet,
)
from buttercup.common.llm import ButtercupLLM, create_default_llm_with_temperature
from buttercup.patcher.utils import pick_temperature
from langgraph.types import Command

logger = logging.getLogger(__name__)

ROOT_CAUSE_SYSTEM_MSG = (
    """You are an expert security vulnerability analyst tasked with reviewing code for potential security issues."""
)
ROOT_CAUSE_USER_MSG = """Your analysis will be used by an autonomous patching system to generate a fix, so accuracy and depth are crucial.

First, review the following information about the code and potential vulnerability:

<vulnerability_diff>
{DIFF}
</vulnerability_diff>

<code_snippets>
{CODE_SNIPPETS}
</code_snippets>

<sanitizer_output>
{SANITIZER_OUTPUT}
</sanitizer_output>

<project_name>
{PROJECT_NAME}
</project_name>

<sanitizer_used>
{SANITIZER}
</sanitizer_used>

{REFLECTION_GUIDANCE}

Your task is to analyze this information and provide a detailed root cause analysis of the security vulnerability. Focus on the specific vulnerability indicated by the stacktrace and crash. Be precise and thorough, avoiding vague assertions.

Before providing your final output, wrap your thinking process inside <vulnerability_breakdown> tags. In this section:

1. Understand the original intention of the code (use the `understand_code_snippet` tool):
   - Analyze the purpose and functionality of the code involved in the vulnerability.
   - Identify key components and their intended interactions.

2. Determine the exact nature and type of the vulnerability:
   - Classify the vulnerability using standard terminology.
   - Explain how it deviates from the intended code behavior.

3. Explain how and why the vulnerability occurs:
   - Describe the sequence of operations leading to the vulnerability.
   - Identify any failed security checks or mechanisms.

4. Describe the data flow and execution path that triggers the vulnerability:
   - Trace the flow of data from input to the point of failure.
   - Highlight any transformations or validations applied to the data.

5. Identify which specific variables and operations are involved:
   - List all relevant variables, their types, and how they're used.
   - Describe critical operations that contribute to the vulnerability.

6. List functions, classes, files, types, etc. that are directly involved in the vulnerability.

7. Quote and analyze relevant parts from each provided source (vulnerability diff, code snippets, sanitizer output, etc.).

8. Only request additional code snippets if they are CRITICAL to understanding the vulnerability. A code snippet is critical only if:
   - It contains the exact point of failure
   - It contains code that directly leads to the vulnerability
   - It contains security checks that failed to prevent the vulnerability
   Do NOT request code snippets just to understand the general context or program flow.

9. List and number all possible attack vectors related to this vulnerability.

10. Identify the exact point where the vulnerability occurs, quoting the relevant code.

11. Classify the vulnerability using standard terminology (e.g., 'Buffer Overflow', 'Use-After-Free'). Include both the primary vulnerability class and any relevant subtype.

12. Summarize your findings.

After your analysis, provide your final output in the following format:

<vulnerability_analysis>
<code_snippet_requests>
[Additional code snippets required ONLY if they contain the exact point of failure, code that directly leads to the vulnerability, or failed security checks. Leave empty if the provided snippets are sufficient.]
</code_snippet_requests>

<classification>
[Formal classification of the vulnerability using standard terminology (e.g. 'Buffer Overflow', 'Use-After-Free'). Include both the primary vulnerability class and any relevant subtype.]
</classification>

<root_cause>
[Comprehensive explanation of how and why the vulnerability occurs. It is fine for this section to be long. Include:
1. The exact point of failure in the code
2. The sequence of operations that leads to the vulnerability
3. Why existing security controls fail to prevent it
4. The potential impact if exploited
5. Any relevant code patterns or anti-patterns involved]
</root_cause>

<affected_variables>
[List of specific variables and data structures involved in the vulnerability, including:
1. Variables that can be corrupted or misused
2. Pointers or references that may become invalid
3. Buffer sizes and array indices
4. Any user-controlled input variables]
</affected_variables>

<trigger_conditions>
[Precise conditions required to trigger the vulnerability, such as:
1. Specific input values or ranges
2. Program states or execution paths
3. Timing or race conditions
4. Resource conditions (memory, handles, etc.)]
</trigger_conditions>

<data_flow_analysis>
[Trace of how data flows through the program to trigger the vulnerability:
1. Source of untrusted input
2. Transformations applied to the data
3. Propagation through function calls
4. Point where the data causes the vulnerability]
</data_flow_analysis>

<security_constraints>
[List of security constraints that should be considered when writing a patch, e.g. 'Do not modify function X', 'Do not modify variable Y', etc.]
</security_constraints>
</vulnerability_analysis>

Remember:
- Focus on the SPECIFIC vulnerability indicated by the stacktrace and crash
- Be precise and thorough, avoid vague assertions
- Identify the EXACT point where the vulnerability occurs
- Consider ALL possible attack vectors related to this vulnerability
- Ensure your analysis enables a precise and targeted fix
- Only request additional code snippets if they are CRITICAL to understanding the vulnerability
- Do NOT request code snippets just to understand the general context or program flow

Now, proceed with your analysis and final output.
"""

ROOT_CAUSE_PROMPT = ChatPromptTemplate.from_messages(
    [
        ("system", ROOT_CAUSE_SYSTEM_MSG),
        ("user", ROOT_CAUSE_USER_MSG),
        MessagesPlaceholder(variable_name="messages"),
        ("ai", "<vulnerability_breakdown>"),
    ]
)

REFLECTION_GUIDANCE_TMPL = """
You have received additional guidance on what to do next, you should follow it as much as possible.

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
        default_llm = create_default_llm_with_temperature(model_name=ButtercupLLM.OPENAI_GPT_4O.value)
        fallback_llms = [
            create_default_llm_with_temperature(model_name=ButtercupLLM.CLAUDE_3_7_SONNET.value),
        ]
        self.llm = default_llm.with_fallbacks(fallback_llms)

        @tool(description=self._understand_code_snippet.__doc__)
        def understand_code_snippet(
            code_snippet_id: str, focus_area: str, *, state: Annotated[BaseModel, InjectedState]
        ) -> str:
            assert isinstance(state, PatcherAgentState)
            return self._understand_code_snippet(state, code_snippet_id, focus_area)

        tools = [
            understand_code_snippet,
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
        stacktrace = parse_stacktrace(state.context.sanitizer_output)
        stacktrace_lines = [
            (stackframe.filename, int(stackframe.fileline))
            for frame in stacktrace.frames
            for stackframe in frame
            if stackframe.filename is not None and stackframe.fileline is not None
        ]
        return ROOT_CAUSE_PROMPT.format_messages(
            DIFF=diff_content,
            PROJECT_NAME=self.challenge.project_name,
            SANITIZER=state.context.sanitizer,
            SANITIZER_OUTPUT=state.cleaned_stacktrace,
            CODE_SNIPPETS="\n".join(
                [self._comment_code_snippet(state, stacktrace_lines, cs) for cs in state.relevant_code_snippets]
            ),
            REFLECTION_GUIDANCE=self._get_reflection_guidance_prompt(state),
            messages=state.messages,
        )

    def _parse_root_cause_analysis(self, response: str) -> RootCauseAnalysis:
        """Parse the root cause analysis from the response."""
        # Extract content between vulnerability_analysis tags
        if "<vulnerability_analysis>" not in response:
            return RootCauseAnalysis(root_cause=response)

        if "</vulnerability_analysis>" not in response:
            response += "</vulnerability_analysis>"

        start = response.find("<vulnerability_analysis>") + len("<vulnerability_analysis>")
        end = response.find("</vulnerability_analysis>")
        analysis = response[start:end].strip()

        # Extract each field
        def extract_field(field: str) -> str | list[str] | None:
            start_tag = f"<{field}>"
            end_tag = f"</{field}>"
            start = analysis.find(start_tag) + len(start_tag)
            end = analysis.find(end_tag)
            if start == -1 or end == -1:
                return None
            content = analysis[start:end].strip()
            if not content:
                return None
            return content

        res = RootCauseAnalysis(
            code_snippet_requests=extract_field("code_snippet_requests"),
            classification=extract_field("classification"),
            root_cause=extract_field("root_cause"),
            affected_variables=extract_field("affected_variables"),
            trigger_conditions=extract_field("trigger_conditions"),
            data_flow_analysis=extract_field("data_flow_analysis"),
            security_constraints=extract_field("security_constraints"),
        )
        if res.code_snippet_requests == "" or res.code_snippet_requests == "[]":
            res.code_snippet_requests = None

        return res

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

    def analyze_vulnerability(self, state: PatcherAgentState) -> Command[Literal[PatcherAgentName.CREATE_PATCH.value]]:  # type: ignore[name-defined]
        """Analyze the diff analysis and the code to understand the
        vulnerability in the current code."""
        logger.info(
            "[%s / %s] Analyzing the vulnerability in Challenge Task %s",
            state.context.task_id,
            state.context.submission_index,
            self.challenge.name,
        )

        execution_info = state.execution_info
        execution_info.prev_node = PatcherAgentName.ROOT_CAUSE_ANALYSIS

        root_cause_dict = self.root_cause_chain.invoke(
            state,
            config=RunnableConfig(
                configurable={
                    "llm_temperature": pick_temperature(),
                },
            ),
        )
        try:
            state = PatcherAgentState.model_validate(root_cause_dict)
        except ValidationError as e:
            logger.error("Invalid state dict for root cause: %s", e)
            return Command(
                update={
                    "execution_info": execution_info,
                },
                goto=PatcherAgentName.REFLECTION.value,
            )

        root_cause_str = str(state.messages[-1].content)
        root_cause = self._parse_root_cause_analysis(root_cause_str)
        if root_cause.code_snippet_requests:
            return Command(
                update={
                    "root_cause": root_cause,
                    "execution_info": execution_info,
                },
                goto=PatcherAgentName.REFLECTION.value,
            )

        return Command(
            update={
                "root_cause": root_cause,
            },
            goto=PatcherAgentName.PATCH_STRATEGY.value,
        )
