"""Software Engineer LLM agent, analyzing the root cause of a vulnerability."""

import logging
import re
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
from langchain_core.runnables import Runnable
from buttercup.patcher.agents.common import (
    PatcherAgentState,
    PatcherAgentName,
    PatcherAgentBase,
    ContextCodeSnippet,
    CodeSnippetRequest,
    get_stacktraces_from_povs,
)
from buttercup.common.llm import ButtercupLLM, create_default_llm_with_temperature
from langgraph.types import Command

logger = logging.getLogger(__name__)

ROOT_CAUSE_SYSTEM_MSG = (
    "You are an expert security analyst. Your role is to analyze source code for security vulnerabilities "
    "with the depth and precision needed for automated patch generation."
)

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

If there are multiple stacktraces, consider them as part of the same vulnerability.

{REFLECTION_GUIDANCE}

---

Your task is to produce a **precise, detailed root cause analysis** of the vulnerability. This analysis will be used by an automated patching system. Be rigorous and avoid speculation.

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
        stacktraces = [parse_stacktrace(pov.sanitizer_output) for pov in state.context.povs]
        return ROOT_CAUSE_PROMPT.format_messages(
            DIFF=diff_content,
            PROJECT_NAME=self.challenge.project_name,
            STACKTRACES="\n".join(get_stacktraces_from_povs(state.context.povs)),
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
