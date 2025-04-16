"""Agent that retrieves code snippets from the project."""

from __future__ import annotations

import logging
import langgraph.errors
import operator
from langchain_core.language_models import BaseChatModel
from dataclasses import dataclass, field
from langchain_core.messages import ToolMessage
from typing import Annotated, Sequence, Literal
from langgraph.managed import IsLastStep, RemainingSteps
from pydantic import BaseModel, Field
from pathlib import Path
from enum import Enum
from langchain_core.tools import BaseTool
from langgraph.graph import StateGraph, add_messages
from langgraph.prebuilt import ToolNode
from langgraph.constants import END
from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState
from langchain_core.tools.base import InjectedToolCallId
from buttercup.common.challenge_task import ChallengeTask

from langchain_core.messages import BaseMessage
from langchain_core.runnables import Runnable, RunnableConfig
from langchain_core.prompts import ChatPromptTemplate
from buttercup.patcher.agents.common import PatcherAgentBase, ContextRetrieverState, ContextCodeSnippet, CodeSnippetKey
from buttercup.common.llm import ButtercupLLM, create_default_llm
from langgraph.types import Command


from buttercup.program_model.codequery import CodeQueryPersistent

logger = logging.getLogger(__name__)

SYSTEM_TMPL = """You are an AI assistant tasked with helping a software engineer find and extract relevant code snippets from a project."""

USER_MSG = """You have access to some tools to navigate the project and search for code.

The project you will be working with is located at:
<project_name>
{PROJECT_NAME}
</project_name>

The software engineer has made the following request:
<engineer_request>
{REQUEST}
</engineer_request>

Throughout this process, maintain a <scratchpad> where you document your thought process, the commands you're using, and the results you're finding. This will help you keep track of your progress and make informed decisions about next steps.
Do not make up any information, only use the provided tools and the information available in the project.
Do not make up any file paths.
Remember to use the provided tools only as defined, and do not attempt to modify or extend their functionality. If you encounter any errors or cannot find the requested information, explain the issue in your answer and suggest potential next steps or alternative approaches.
Try to use `get_function_definition` and `get_type_definition` tools as much as possible and rely on others only if these tools fail or do not work as expected.
Answer with <END> when you have found all the code snippets requested.
"""

RECURSION_LIMIT = 20

MESSAGES = ChatPromptTemplate.from_messages([("human", "Please satisfy this request: {request}")])


class State(BaseModel):
    """State for the context retriever agent."""

    messages: Annotated[Sequence[BaseMessage], add_messages]
    is_last_step: IsLastStep | None = None
    remaining_steps: RemainingSteps | None = None

    challenge: ChallengeTask
    context_retriever_agent: ContextRetrieverAgent
    project_name: str
    request: str
    code_snippets: Annotated[list[ContextCodeSnippet], operator.add] = Field(default_factory=list)
    tmp_code_snippets: TmpCodeSnippets


class NodeNames(str, Enum):
    """Names of the nodes in the state graph."""

    AGENT = "agent"
    TOOLS = "tools"


@tool
def ls(
    file_path: str, state: Annotated[BaseModel, InjectedState], tool_call_id: Annotated[str, InjectedToolCallId]
) -> Command:
    """List the files in the given file_path in the project's source directory."""
    # NOTE: can't use `State` directly in the signature because langgraph would fail to inject the state
    assert isinstance(state, State)

    path = Path(file_path)
    logger.info("Listing files in %s", path)
    args = ["ls", "-l"]
    if path:
        args.append(str(path))
    ls_cmd_res = state.challenge.exec_docker_cmd(args)
    if not ls_cmd_res.success:
        raise ValueError(f"Failed to list files in {path}: {ls_cmd_res.error}")

    ls_output = ls_cmd_res.output.decode("utf-8")
    return Command(update={"messages": [ToolMessage(ls_output, tool_call_id=tool_call_id)]})


@tool
def grep(
    pattern: str,
    file_path: str | None,
    state: Annotated[BaseModel, InjectedState],
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command:
    """Grep for a string and return a 5-line context around the match, together with line numbers. If no file_path is provided, search the entire project. Prefer using this tool over cat."""
    # NOTE: can't use `State` directly in the signature because langgraph would fail to inject the state
    assert isinstance(state, State)

    path = Path(file_path) if file_path else None
    logger.info("Searching for %s in %s", pattern, path)
    args = ["grep", "-C", "5", "-nHr", pattern]
    if path:
        args.append(str(path))
    grep_cmd_res = state.challenge.exec_docker_cmd(args)
    if not grep_cmd_res.success:
        raise ValueError(f"Failed to grep for {pattern} in {path}: {grep_cmd_res.error}")

    grep_output = grep_cmd_res.output.decode("utf-8")
    return Command(update={"messages": [ToolMessage(grep_output, tool_call_id=tool_call_id)]})


@tool
def cat(
    file_path: str, state: Annotated[BaseModel, InjectedState], tool_call_id: Annotated[str, InjectedToolCallId]
) -> Command:
    """Read the contents of a file. Use this tool only if grep and get_lines do not work as it might return a large amount of text."""
    # NOTE: can't use `State` directly in the signature because langgraph would fail to inject the state
    assert isinstance(state, State)

    path = Path(file_path)
    logger.info("Reading contents of %s", path)
    cat_cmd_res = state.challenge.exec_docker_cmd(["cat", str(path)])
    if not cat_cmd_res.success:
        raise ValueError(f"Failed to read contents of {path}: {cat_cmd_res.error}")

    cat_output = cat_cmd_res.output.decode("utf-8")
    return Command(update={"messages": [ToolMessage(cat_output, tool_call_id=tool_call_id)]})


@tool
def get_lines(
    file_path: str,
    start: int,
    end: int,
    state: Annotated[BaseModel, InjectedState],
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command:
    """Get a range of lines from a file. Prefer using this tool over cat."""
    # NOTE: can't use `State` directly in the signature because langgraph would fail to inject the state
    assert isinstance(state, State)

    path = Path(file_path)
    logger.info("Getting lines %d-%d of %s", start, end, path)
    get_lines_res_cmd = state.challenge.exec_docker_cmd(["cat", str(path)])
    if not get_lines_res_cmd.success:
        raise ValueError(f"Failed to get lines {start}-{end} of {path}: {get_lines_res_cmd.error}")

    get_lines_output = get_lines_res_cmd.output.decode("utf-8").splitlines()[start:end]
    return Command(update={"messages": [ToolMessage("\n".join(get_lines_output), tool_call_id=tool_call_id)]})


@tool
def get_function_definition(
    function_name: str,
    file_path: str | None,
    state: Annotated[BaseModel, InjectedState],
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command:
    """Get the definition of a function. If available, pass a file_path, \
    otherwise pass None. Use this when you want to get information about a \
    function. If not sure about the file path, pass None. Prefer using this \
    tool over any other and rely on others only if this tool fails or does \
    not work. This tool is just going to return a message whether it found \
    the function or not, but it won't provide the code snippet directly. The \
    function should be considered as retrieved anyway."""
    # NOTE: can't use `State` directly in the signature because langgraph would fail to inject the state
    assert isinstance(state, State)

    path = Path(file_path) if file_path else None
    if path and not path.is_absolute():
        # If the path is not absolute, it is relative to the container workdir
        path = state.challenge.workdir_from_dockerfile().joinpath(path)

    logger.info("Getting function definition of %s in %s", function_name, path)
    functions = state.context_retriever_agent.codequery.get_functions(function_name, path)
    if not functions:
        functions = state.context_retriever_agent.codequery.get_functions(function_name, path, fuzzy=True)
        if not functions:
            return Command(
                update={"messages": [ToolMessage("No definition found for function", tool_call_id=tool_call_id)]}
            )

    code_snippets = [
        ContextCodeSnippet(
            key=CodeSnippetKey(
                file_path=function.file_path.as_posix(),
                identifier=function.name,
            ),
            code=body.body,
        )
        for function in functions
        for body in function.bodies
    ]
    state.tmp_code_snippets.code_snippets.extend(code_snippets)
    return Command(
        update={
            "messages": [
                ToolMessage(
                    f"Found {len(code_snippets)} code snippets for function {function_name}", tool_call_id=tool_call_id
                )
            ],
            "code_snippets": code_snippets,
        }
    )


@tool
def get_type_definition(
    type_name: str,
    file_path: str | None,
    state: Annotated[BaseModel, InjectedState],
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command:
    """Get the definition of a type. If available, pass a file_path, \
    otherwise pass None. Use this when you want to get information about a type. \
    If not sure about the file path, pass None. Prefer using this tool over any \
    other and \
    rely on others only if this tool fails or does not work. This tool is just \
    going to return a message whether it found the type or not, but it won't \
    provide the code snippet directly. The type should be considered as \
    retrieved anyway."""
    # NOTE: can't use `State` directly in the signature because langgraph would fail to inject the state
    assert isinstance(state, State)

    path = Path(file_path) if file_path else None

    logger.info("Getting type definition of %s in %s", type_name, path)
    types = state.context_retriever_agent.codequery.get_types(type_name, path)
    if not types:
        types = state.context_retriever_agent.codequery.get_types(type_name, path, fuzzy=True)
        if not types:
            return Command(
                update={"messages": [ToolMessage("No definition found for type", tool_call_id=tool_call_id)]}
            )

    code_snippets = [
        ContextCodeSnippet(
            key=CodeSnippetKey(
                file_path=path.as_posix() if path else "<type-path>",  # TODO: get this from the type definition
                identifier=type_def.name,
            ),
            code=type_def.definition,
        )
        for type_def in types
    ]
    state.tmp_code_snippets.code_snippets.extend(code_snippets)
    return Command(
        update={
            "messages": [
                ToolMessage(f"Found {len(code_snippets)} code snippets for type {type_name}", tool_call_id=tool_call_id)
            ],
            "code_snippets": code_snippets,
        }
    )


class TmpCodeSnippets(BaseModel):
    """Temporary code snippets."""

    code_snippets: list[ContextCodeSnippet] = Field(default_factory=list)


@dataclass
class ContextRetrieverAgent(PatcherAgentBase):
    """Agent that retrieves code snippets from the project."""

    work_dir: Path
    max_retries: int = 30
    recursion_limit: int = 80
    llm: BaseChatModel = field(init=False)
    current_retries: int = field(init=False, default=0)
    codequery: CodeQueryPersistent = field(init=False)
    tools: list[BaseTool] = field(init=False)

    def __post_init__(self) -> None:
        """Initialize a few fields"""
        default_llm = create_default_llm(model_name=ButtercupLLM.OPENAI_GPT_4O.value)
        fallback_llms = [
            create_default_llm(model_name=ButtercupLLM.CLAUDE_3_5_SONNET.value),
        ]

        self.tools = [
            ls,
            grep,
            get_lines,
            cat,
            get_function_definition,
            get_type_definition,
        ]
        self.llm = default_llm.with_fallbacks(fallback_llms)
        self.llm_with_tools = self.llm.bind_tools(self.tools)
        self.codequery = CodeQueryPersistent(self.challenge, work_dir=self.work_dir)

    def _call_model(self, state: State) -> Command[Literal[NodeNames.TOOLS.value, END]]:  # type: ignore[name-defined]
        """Call the model."""
        user_msg = USER_MSG.format(
            REQUEST=state.request,
            PROJECT_NAME=state.project_name,
        )
        res = self.llm_with_tools.invoke(
            [
                {"role": "system", "content": SYSTEM_TMPL},
                {"role": "user", "content": user_msg},
                *state.messages,
            ]
        )
        if "<END>" in res.content:
            return Command(update={"messages": [res]}, goto=END)

        return Command(update={"messages": [res]}, goto=NodeNames.TOOLS.value)

    def _create_agent(self) -> Runnable:
        """Create the agent."""
        workflow = StateGraph(State)
        tool_node = ToolNode(self.tools, name=NodeNames.TOOLS.value)
        workflow.add_node(NodeNames.AGENT.value, self._call_model)
        workflow.add_node(NodeNames.TOOLS.value, tool_node)

        workflow.set_entry_point(NodeNames.AGENT.value)
        workflow.add_edge(NodeNames.TOOLS.value, NodeNames.AGENT.value)
        return workflow.compile()

    def retrieve_context(self, state: ContextRetrieverState) -> Command:
        """Retrieve the context for the diff analysis."""
        if self.current_retries >= self.max_retries:
            logger.warning("Reached max context retrieval retries, skipping")
            return Command(
                update={
                    "ctx_request_limit": True,
                },
                goto=state.prev_node,
            )

        logger.info("Retrieving the context for the diff analysis in Challenge Task %s", self.challenge.name)
        logger.debug("Code snippet requests: %s", state.code_snippet_requests)

        agent = self._create_agent()

        res = []
        for request in state.code_snippet_requests:
            logger.info("Retrieving code snippet for request '%s'", request.request)
            tmp_code_snippets = TmpCodeSnippets()
            input_state = {
                "request": request.request,
                "project_name": self.challenge.project_name,
                "challenge": self.challenge,
                "context_retriever_agent": self,
                "tmp_code_snippets": tmp_code_snippets,
            }
            try:
                ctx_state_dict: dict = agent.invoke(
                    input_state,
                    RunnableConfig(
                        recursion_limit=RECURSION_LIMIT,
                        configurable={
                            "thread_id": hash(request.request),
                        },
                    ),
                )
            except langgraph.errors.GraphRecursionError:
                logger.error("Reached recursion limit for request '%s'", request.request)
                ctx_state_dict = {
                    "messages": [],
                    "challenge": self.challenge,
                    "project_name": self.challenge.project_name,
                    "context_retriever_agent": self,
                    "request": request.request,
                    "code_snippets": tmp_code_snippets.code_snippets,
                    "tmp_code_snippets": tmp_code_snippets,
                }

            if logger.level <= logging.DEBUG:
                for message in ctx_state_dict["messages"]:
                    string_representation = f"{message.type.upper()}: {message.content}"
                    logger.debug(string_representation)

            ctx_state = State(**ctx_state_dict)
            if not ctx_state.code_snippets:
                # TODO: pass back these errors to the caller so that it can retry in other ways
                logger.warning("No code snippet returned from the agent for request '%s'", request.request)
                continue

            logger.info("Code snippets retrieved for request '%s'", request.request)
            res.extend(ctx_state.code_snippets)

        self.current_retries += 1
        return Command(
            update={
                "relevant_code_snippets": set(res),
            },
            goto=state.prev_node,
        )
