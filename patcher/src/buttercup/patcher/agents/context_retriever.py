"""Agent that retrieves code snippets from the project."""

from __future__ import annotations

import logging
import langgraph.errors
import operator
import re
from langchain_openai.chat_models.base import BaseChatOpenAI
from concurrent.futures import as_completed
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from buttercup.common.stack_parsing import parse_stacktrace
from langgraph.checkpoint.memory import InMemorySaver
from langchain_core.messages import AnyMessage, SystemMessage, HumanMessage
from functools import lru_cache
from buttercup.common.challenge_task import CommandResult
from buttercup.patcher.agents.config import PatcherConfig
from dataclasses import dataclass, field
from langchain_core.messages import ToolMessage
from typing import Annotated, Any, Literal
from pydantic import Field, ValidationError, BaseModel
from pathlib import Path
from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState
from langchain_core.tools.base import InjectedToolCallId
from buttercup.common.challenge_task import ChallengeTask

from langchain_core.runnables import Runnable, RunnableConfig
from langchain_core.runnables.config import get_executor_for_config
from buttercup.program_model.utils.common import Function, TypeDefinition
from buttercup.patcher.agents.common import (
    PatcherAgentBase,
    ContextRetrieverState,
    ContextCodeSnippet,
    CodeSnippetKey,
    CodeSnippetRequest,
    PatcherAgentName,
    PatcherAgentState,
)
from buttercup.common.llm import ButtercupLLM, create_default_llm
from langgraph.types import Command
from langgraph.prebuilt.chat_agent_executor import AgentStatePydantic, create_react_agent


from buttercup.program_model.codequery import CodeQueryPersistent

logger = logging.getLogger(__name__)

SYSTEM_TMPL = """You are an AI assistant tasked with helping a software engineer find and extract relevant code snippets from a project."""

CODE_SNIPPET_KEY_TMPL = """
<code_snippet>
<identifier>{IDENTIFIER}</identifier>
<description>{DESCRIPTION}</description>
<file_path>{FILE_PATH}</file_path>
<start_line>{START_LINE}</start_line>
<end_line>{END_LINE}</end_line>
</code_snippet>
"""

USER_MSG = """You have access to some tools to navigate the project and search for code.

The project you will be working with is located at:
<project_name>
{PROJECT_NAME}
</project_name>

The software engineer has made the following request:
<engineer_request>
{REQUEST}
</engineer_request>

Code snippets tracked so far:
<code_snippets>
{CODE_SNIPPETS}
</code_snippets>

<cwd>
{CWD}
</cwd>

<ls_cwd>
{LS_CWD}
</ls_cwd>

Do not make up any information, only use the provided tools and the information available in the project.
Do not make up any file paths.
Remember to use the provided tools only as defined, and do not attempt to modify or extend their functionality. If you encounter any errors or cannot find the requested information, explain the issue in your answer and suggest potential next steps or alternative approaches.
Try to use `get_function`, `get_type` tools as much as possible and rely on others only if these tools fail or do not work as expected.
You can use `track_lines` tool to track a code snippet from a file, but only if you cannot use the other tools and you have tested them recently.

Stop only if `check_code_snippets` tool returns that you have found all the code snippets you need, or if you are completely sure what was requested is not present in the code.
"""

CHECK_CODE_SNIPPETS_USER_MSG = """You are an AI assistant. Your job is to provide code snippets to the software engineer that answers the original request.

The original request was:
<original_request>
{REQUEST}
</original_request>

Here is the list of code snippets you have found:
<code_snippets>
{CODE_SNIPPETS}
</code_snippets>

Did you find all the code snippets you need?
Did you completely answer the original request?
Do the code snippets fully answer the original request? (e.g. if the original \
request was to find the code snippet that implements a function, make sure you \
have found the code snippet that implements that function and that the function
is fully implemented)
"""

CHECK_CODE_SNIPPETS_PROMPT = ChatPromptTemplate.from_messages(
    [
        ("user", CHECK_CODE_SNIPPETS_USER_MSG),
    ]
)

DUPLICATE_CODE_SNIPPET_USER_MSG = """You are an AI assistant. Your job is to check if a code snippet request is already satisfied by the available code snippets.

Here is the code snippet request:
<code_request>
{CODE_REQUEST}
</code_request>

Here are the available code snippets:
<code_snippets>
{CODE_SNIPPETS}
</code_snippets>

Check if any of the available code snippets already satisfy this request. Consider:
1. Does any snippet contain the exact code being requested?
2. Does any snippet provide equivalent or superset functionality?
3. Is the requested code fully visible in the existing snippets?

Provide your analysis and clearly state whether the request is already satisfied or not.

<analysis>
<explanation>......</explanation>
<is_satisfied>TRUE/FALSE</is_satisfied>
</analysis>
"""

DUPLICATE_CODE_SNIPPET_PROMPT = ChatPromptTemplate.from_messages(
    [
        ("user", DUPLICATE_CODE_SNIPPET_USER_MSG),
        ("ai", "<analysis>"),
    ]
)

INITIAL_CODE_SNIPPET_REQUESTS_USER_MSG = """You are an AI assistant tasked with identifying additional code snippets needed to understand a security vulnerability.

You have access to:
1. A stacktrace showing where the vulnerability occurred
2. Any code snippets already retrieved

<stacktrace>
{STACKTRACE}
</stacktrace>

<code_snippets>
{CODE_SNIPPETS}
</code_snippets>

Your task is to analyze this information and generate requests for additional code snippets that would help understand the vulnerability better.

IMPORTANT: Only request code snippets that are ABSOLUTELY ESSENTIAL to understanding the vulnerability AND are NOT already available in the existing code snippets. A code snippet is essential ONLY if it is DIRECTLY involved in the vulnerability, specifically:

- The EXACT line where the vulnerability occurs (e.g., where the buffer overflow happens)
- The EXACT security check that failed (e.g., the bounds check that was missing)
- The EXACT variable that was corrupted (e.g., the buffer that overflowed)

DO NOT request code snippets for:
- Functions that are only called by vulnerable code
- Types that are only used by vulnerable code
- Helper functions or utility code
- Code that is only indirectly related
- Code that provides context or background
- Code that shows program flow
- Code that might be "useful to understand"

BEFORE making any requests:
1. Carefully review ALL existing code snippets
2. Identify what information is already available
3. Only request snippets that contain NEW information not present in existing snippets
4. If a function or type is already shown in the existing snippets, DO NOT request it again
5. If a file is already shown in the existing snippets, carefully check if you need more lines from it
6. Ask yourself: "Is this snippet ABSOLUTELY necessary to understand the vulnerability?"

Generate your requests in the following format:
<request>Description of the code snippet needed, including specific function names, types, or variables</request>

For example:
<request>Implementation of function `foo` in `src/foo.c` where the buffer overflow occurs</request>
<request>Implementation of function `bar` in `src/bar.c` that fails to validate buffer size</request>
<request>Type definition of `buffer_t` in `include/buffer.h` that gets corrupted</request>

Guidelines:
- Be specific about what you're looking for
- Include file paths when known
- Focus ONLY on the EXACT point of vulnerability
- Request the ABSOLUTE MINIMUM amount of code snippets needed
- Do not make up any information, only use the provided tools and the information available in the project
- You MUST request ONLY the code snippets that contain the EXACT point of vulnerability
- You MUST NOT request code snippets that are already available in the existing snippets
- You MUST NOT request code snippets that are only indirectly related to the vulnerability

First, list the code snippets that you think are the most relevant to the vulnerability with an explanation of why you think they are relevant.
Then rate them from 1 to 10, where 1 is the least relevant and 10 is the most relevant.
Finally, output the <request> tags, one per line, for only the ABSOLUTELY ESSENTIAL snippets that are NOT already available.
"""

INITIAL_CODE_SNIPPET_REQUESTS_PROMPT = ChatPromptTemplate.from_messages(
    [
        ("user", INITIAL_CODE_SNIPPET_REQUESTS_USER_MSG),
    ]
)

FILTER_CODE_SNIPPETS_USER_MSG = """You are an AI assistant. Your job is to evaluate whether a code snippet is relevant to one of the requests.

Here are the requests:
<requests>
{REQUESTS}
</requests>

Here is the code snippet:
<code_snippet>
{CODE_SNIPPET}
</code_snippet>

Evaluate whether the code snippet is relevant to the request.
Return:
<explanation>......</explanation>
<is_relevant>TRUE/FALSE</is_relevant>
"""

FILTER_CODE_SNIPPETS_PROMPT = ChatPromptTemplate.from_messages(
    [
        ("user", FILTER_CODE_SNIPPETS_USER_MSG),
    ]
)


class CheckCodeSnippetsOutput(BaseModel):
    """Output of the check_code_snippets tool"""

    reasoning: str = Field(
        description="Scratchpad space to reason about the code snippets you have found, the original request and whether you have found all the code snippets you need"
    )
    found_all: bool = Field(description="Whether you have found all the code snippets you need")
    fully_answered_request: bool = Field(description="Did you completely answer the original request?")
    fully_implemented: bool = Field(description="Do the code snippets fully answer the original request?")
    success: bool = Field(description="Can you consider the request satisfied?")


class CodeSnippetManagerState(AgentStatePydantic):
    """State for the code snippet manager"""

    request: str
    challenge_task_dir: Path
    work_dir: Path
    code_snippets: Annotated[list[ContextCodeSnippet], operator.add] = Field(default_factory=list)


@lru_cache(maxsize=100)
def _get_challenge(task_dir: Path) -> ChallengeTask:
    return ChallengeTask(task_dir, local_task_dir=task_dir)


@lru_cache(maxsize=100)
def _get_codequery(task_dir: Path, work_dir: Path) -> CodeQueryPersistent:
    challenge = _get_challenge(task_dir)
    return CodeQueryPersistent(challenge, work_dir=work_dir)


def _wrap_command_output(cmd_res: CommandResult, output: str | None = None) -> str:
    if output is None:
        output = cmd_res.output.decode("utf-8")

    return f"""<command_output>
<returncode>{cmd_res.returncode}</returncode>
<stdout>
{output}
</stdout>
<stderr>
{cmd_res.error}
</stderr>
</command_output>"""


@tool
def think(reasoning: str) -> str:
    """Think more about the problem and the tools available to you."""
    return f"""Think more about the problem and the tools available to you. \
You should try to find the most relevant code snippet. Reasoning: \
{reasoning}. Did you call the `get_function`, \
`get_type`, `track_lines` tools \
with the newly discovered information?"""


@tool
def check_code_snippets(state: Annotated[CodeSnippetManagerState, InjectedState]) -> str:
    """Check if you have found at least one code snippet. This tool MUST be called before stopping."""
    if len(state.code_snippets) == 0:
        return """The request has NOT been satisfied yet. You MUST keep going.

You haven't found any code snippets yet. You must call \
`get_function`, `get_type`, `track_lines` tools to keep track of the code snippets. \
Also, think more about the problem and the tools available to you. \
You should try to find the most relevant code snippet."""

    llm = create_default_llm(model_name=ButtercupLLM.OPENAI_GPT_4O_MINI.value)
    fallback_llms = [
        create_default_llm(model_name=ButtercupLLM.CLAUDE_3_5_HAIKU.value),
    ]
    llm = llm.with_fallbacks(fallback_llms)
    check_code_snippets_chain = CHECK_CODE_SNIPPETS_PROMPT | llm.with_structured_output(CheckCodeSnippetsOutput)
    try:
        res: CheckCodeSnippetsOutput = check_code_snippets_chain.invoke(
            {
                "REQUEST": state.request,
                "CODE_SNIPPETS": "\n".join(str(code_snippet) for code_snippet in state.code_snippets),
            }
        )
    except Exception as e:
        logger.error("Error checking code snippets: %s", e)
        return "Error checking code snippets. Please try again."

    if not res.success:
        return f"""The request has NOT been satisfied yet. You MUST keep going.

Reasoning:
{res.reasoning}
"""

    return "You have found all the code snippets you need. You can stop now."


def _return_command_tool_message(
    tool_call_id: str, message: str, new_code_snippets: list[ContextCodeSnippet] | None = None
) -> Command:
    update_state: dict[str, Any] = {
        "messages": [ToolMessage(content=message, tool_call_id=tool_call_id)],
    }
    if new_code_snippets:
        update_state["code_snippets"] = new_code_snippets

    return Command(update=update_state)


@tool
def ls(
    file_path: str,
    *,
    state: Annotated[CodeSnippetManagerState, InjectedState],
) -> str:
    """List the files in the given file_path in the project's source directory."""
    path = Path(file_path)
    logger.info("Listing files in %s", path)
    args = ["ls", "-l"]
    if path:
        args.append(str(path))
    challenge = _get_challenge(state.challenge_task_dir)
    ls_cmd_res = challenge.exec_docker_cmd(args)
    return _wrap_command_output(ls_cmd_res)


@tool
def grep(
    pattern: str,
    file_path: str | None,
    state: Annotated[CodeSnippetManagerState, InjectedState],
) -> str:
    """Grep for a string and return a 5-line context around the match, together \
    with line numbers. If no file_path is provided, search the entire project. \
    Prefer using this tool over cat. If you need to search several files, just \
    call call this tool without any file_path."""
    path = Path(file_path) if file_path else None
    logger.info("Searching for %s in %s", pattern, path)
    args = ["grep", "-C", "5", "-nHr", pattern]
    if path:
        args.append(str(path))
    challenge = _get_challenge(state.challenge_task_dir)
    grep_cmd_res = challenge.exec_docker_cmd(args)
    return _wrap_command_output(grep_cmd_res)


@tool
def cat(file_path: str, state: Annotated[CodeSnippetManagerState, InjectedState]) -> str:
    """Read the contents of a file. Use this tool only if grep and get_lines do not work as it might return a large amount of text."""
    path = Path(file_path)
    logger.info("Reading contents of %s", path)
    challenge = _get_challenge(state.challenge_task_dir)
    cat_cmd_res = challenge.exec_docker_cmd(["cat", str(path)])
    return _wrap_command_output(cat_cmd_res)


@tool
def get_lines(
    file_path: str,
    start: int,
    end: int,
    state: Annotated[CodeSnippetManagerState, InjectedState],
) -> str:
    """Get a range of lines from a file. Prefer using this tool over cat."""
    path = Path(file_path)
    logger.info("Getting lines %d-%d of %s", start, end, path)
    challenge = _get_challenge(state.challenge_task_dir)
    get_lines_res_cmd = challenge.exec_docker_cmd(["cat", str(path)])
    get_lines_output = get_lines_res_cmd.output.decode("utf-8").splitlines()[start:end]
    return _wrap_command_output(get_lines_res_cmd, "\n".join(get_lines_output))


@tool
def track_lines(
    file_path: str,
    start: int,
    end: int,
    function_name: str | None,
    type_name: str | None,
    code_snippet_description: str,
    state: Annotated[CodeSnippetManagerState, InjectedState],
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command:
    """Track a range of lines from a file as a code snippet. start/end are 1-indexed. Prefer \
    get_function, get_type tools if possible, use this \
    tool only if you cannot use the other tools. `code_snippet_description` is a \
    description of the code snippet you are tracking, e.g. 'Implementation of function X', \
    'Class Y', 'Definition of type Z', etc. If you are tracking a function or type, \
    pass the function_name or type_name respectively (one or the other, not both)."""
    path = Path(file_path)
    code_snippets = None
    if function_name:
        code_snippets = _get_function(function_name, file_path, state)
    elif type_name:
        code_snippets = _get_type(type_name, file_path, state)

    if code_snippets:
        return _return_command_tool_message(
            tool_call_id,
            f"Found {len(code_snippets)} code snippets for {code_snippet_description}",
            code_snippets,
        )

    logger.info("Getting lines %d-%d of %s", start, end, path)
    challenge = _get_challenge(state.challenge_task_dir)
    get_lines_res_cmd = challenge.exec_docker_cmd(["cat", str(path)])
    # Get a few lines before and after the requested lines in case the LLM does
    # small mistakes when requesting the lines
    start = max(0, start - 5)
    end = end + 5
    get_lines_output = get_lines_res_cmd.output.decode("utf-8").splitlines()[start:end]
    if not path.is_absolute():
        path = challenge.workdir_from_dockerfile().joinpath(path)

    code_snippet = ContextCodeSnippet(
        key=CodeSnippetKey(
            file_path=path.as_posix(),
        ),
        start_line=start,
        end_line=end,
        code="\n".join(get_lines_output),
        description=code_snippet_description,
    )
    return _return_command_tool_message(
        tool_call_id,
        f"Tracked lines {start}-{end} from {path} as a code snippet.",
        [code_snippet],
    )


def _get_codequery_function(codequery: CodeQueryPersistent, name: str, path: Path | None) -> Function:
    functions = codequery.get_functions(name, path)
    if not functions:
        raise ValueError(f"No definition found for function {name} in {path}")

    return functions[0]


def _add_functions_code_snippets(functions: list[Function], suffix: str = "") -> list[ContextCodeSnippet]:
    return [
        ContextCodeSnippet(
            key=CodeSnippetKey(
                file_path=function.file_path.as_posix(),
            ),
            start_line=body.start_line,
            end_line=body.end_line,
            code=body.body,
            description=f"Implementation of function {function.name}{suffix}",
        )
        for function in functions
        for body in function.bodies
    ]


def _add_type_definitions_code_snippets(type_definitions: list[TypeDefinition]) -> list[ContextCodeSnippet]:
    return [
        ContextCodeSnippet(
            key=CodeSnippetKey(
                file_path=type_def.file_path.as_posix(),
            ),
            code=type_def.definition,
            start_line=type_def.definition_line,
            end_line=type_def.definition_line + len(type_def.definition.splitlines()),
            description=f"Definition of type {type_def.name}",
        )
        for type_def in type_definitions
    ]


def _clean_function_name(function_name: str) -> str:
    if function_name.startswith("OSS_FUZZ_"):
        return function_name[len("OSS_FUZZ_") :]
    return function_name


def _get_function(
    function_name: str,
    file_path: str | None,
    state: Annotated[CodeSnippetManagerState, InjectedState],
) -> list[ContextCodeSnippet]:
    path = Path(file_path) if file_path else None
    challenge = _get_challenge(state.challenge_task_dir)
    if path and not path.is_absolute():
        # If the path is not absolute, it is relative to the container workdir
        path = challenge.workdir_from_dockerfile().joinpath(path)

    logger.info("Getting function definition of %s in %s", function_name, path)
    function_name = _clean_function_name(function_name)
    codequery = _get_codequery(state.challenge_task_dir, state.work_dir)
    functions = codequery.get_functions(function_name, path)
    if not functions:
        functions = codequery.get_functions(function_name, path, fuzzy=True)
        if not functions:
            functions = codequery.get_functions(function_name, None)
            if not functions:
                functions = codequery.get_functions(function_name, None, fuzzy=True)
                if not functions:
                    raise ValueError(f"No definition found for function {function_name} in {path}")

    return _add_functions_code_snippets(functions)


@tool
def get_function(
    function_name: str,
    file_path: str | None,
    state: Annotated[CodeSnippetManagerState, InjectedState],
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command:
    """Get the definition of a function. If available, pass a file_path, \
    otherwise pass None. Use this when you want to get information about a \
    function. If not sure about the file path, pass None. Prefer using this \
    tool over any other and rely on others only if this tool fails or does \
    not work. This tool is just going to return a message whether it found \
    the function or not, but it won't provide the code snippet directly. The \
    function should be considered as retrieved anyway."""
    code_snippets = _get_function(function_name, file_path, state)
    return _return_command_tool_message(
        tool_call_id,
        f"Found {len(code_snippets)} code snippets for function {function_name}. Use `check_code_snippets` tool to verify if you have found all the code snippets you need.",
        code_snippets,
    )


@tool
def get_callers(
    function_name: str,
    file_path: str | None,
    state: Annotated[CodeSnippetManagerState, InjectedState],
) -> str:
    """Get the callers of a function."""
    path = Path(file_path) if file_path else None
    logger.info("Getting callers of %s in %s", function_name, path)
    codequery = _get_codequery(state.challenge_task_dir, state.work_dir)
    function = _get_codequery_function(codequery, function_name, path)
    callers = codequery.get_callers(function)
    if not callers:
        raise ValueError(f"No callers found for function {function_name} in {path}")

    msg = f"""Found {len(callers)} callers of function {function_name}:
{"\n".join(f"- `{caller.name}` in `{caller.file_path}`" for caller in callers)}

If you need to get the definition of the caller in order to satisfy the request, \
call `get_function` tool with the caller's name and file_path.
"""

    return msg


@tool
def get_callees(
    function_name: str,
    file_path: str | None,
    state: Annotated[CodeSnippetManagerState, InjectedState],
) -> str:
    """Get the callees of a function."""
    path = Path(file_path) if file_path else None
    logger.info("Getting callees of %s in %s", function_name, path)
    codequery = _get_codequery(state.challenge_task_dir, state.work_dir)
    function = _get_codequery_function(codequery, function_name, path)
    callees = codequery.get_callees(function)
    if not callees:
        raise ValueError(f"No callees found for function {function_name} in {path}")

    msg = f"""Found {len(callees)} callees of function {function_name}:
{"\n".join(f"- `{callee.name}` in `{callee.file_path}`" for callee in callees)}

If you need to get the definition of the callee in order to satisfy the request, \
call `get_function` tool with the callee's name and file_path.
"""

    return msg


def _get_type(
    type_name: str,
    file_path: str | None,
    state: Annotated[CodeSnippetManagerState, InjectedState],
) -> list[ContextCodeSnippet]:
    path = Path(file_path) if file_path else None

    logger.info("Getting type definition of %s in %s", type_name, path)
    codequery = _get_codequery(state.challenge_task_dir, state.work_dir)
    types = codequery.get_types(type_name, path)
    if not types:
        types = codequery.get_types(type_name, path, fuzzy=True)
        if not types:
            raise ValueError(f"No definition found for type {type_name} in {path}")

    return _add_type_definitions_code_snippets(types)


@tool
def get_type(
    type_name: str,
    file_path: str | None,
    state: Annotated[CodeSnippetManagerState, InjectedState],
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
    code_snippets = _get_type(type_name, file_path, state)
    return _return_command_tool_message(
        tool_call_id,
        f"Found {len(code_snippets)} code snippets for type {type_name}. Use `check_code_snippets` tool to verify if you have found all the code snippets you need.",
        code_snippets,
    )


@dataclass
class ContextRetrieverAgent(PatcherAgentBase):
    """Agent that retrieves code snippets from the project."""

    agent: Runnable = field(init=False)
    cheap_llm: BaseChatOpenAI = field(init=False)
    cheap_fallback_llms: list[BaseChatOpenAI] = field(init=False)
    initial_snippets_chain: Runnable = field(init=False)

    def __post_init__(self) -> None:
        """Initialize a few fields"""
        self.cheap_llm = create_default_llm(model_name=ButtercupLLM.OPENAI_GPT_4O_MINI.value)
        self.cheap_fallback_llms = [
            create_default_llm(model_name=ButtercupLLM.CLAUDE_3_5_HAIKU.value),
        ]

        self.tools = [
            ls,
            grep,
            get_lines,
            cat,
            get_function,
            get_type,
            get_callers,
            get_callees,
            track_lines,
            think,
            check_code_snippets,
        ]
        checkpointer = InMemorySaver()
        default_agent = create_react_agent(
            model=self.cheap_llm,
            state_schema=CodeSnippetManagerState,
            tools=self.tools,
            prompt=self._prompt,
            checkpointer=checkpointer,
        )
        fallback_agents = [
            create_react_agent(
                model=llm,
                state_schema=CodeSnippetManagerState,
                tools=self.tools,
                prompt=self._prompt,
                checkpointer=checkpointer,
            )
            for llm in self.cheap_fallback_llms
        ]
        self.agent = default_agent.with_fallbacks(fallback_agents)
        self.code_snippet_duplicates_chain = (
            DUPLICATE_CODE_SNIPPET_PROMPT
            | self.cheap_llm.with_fallbacks(self.cheap_fallback_llms)
            | StrOutputParser()
            | self._parse_duplicate_code_snippet_output
        )

        self.initial_snippets_chain = (
            INITIAL_CODE_SNIPPET_REQUESTS_PROMPT
            | self.cheap_llm.with_fallbacks(self.cheap_fallback_llms)
            | StrOutputParser()
            | self._parse_initial_code_snippet_requests_output
        )

        self.filter_code_snippets_chain = (
            FILTER_CODE_SNIPPETS_PROMPT
            | self.cheap_llm.with_fallbacks(self.cheap_fallback_llms)
            | StrOutputParser()
            | self._parse_filter_code_snippets_output
        )

        ls_cwd = self.challenge.exec_docker_cmd(["ls", "-l"])
        if ls_cwd.success:
            self.ls_cwd = ls_cwd.output.decode("utf-8")
        else:
            self.ls_cwd = "ls cwd failed"

    def _prompt(self, state: CodeSnippetManagerState) -> list[AnyMessage]:
        challenge = _get_challenge(state.challenge_task_dir)
        return [
            SystemMessage(content=SYSTEM_TMPL),
            HumanMessage(
                content=USER_MSG.format(
                    REQUEST=state.request,
                    PROJECT_NAME=challenge.project_name,
                    CODE_SNIPPETS="".join(
                        [
                            CODE_SNIPPET_KEY_TMPL.format(
                                FILE_PATH=code_snippet.key.file_path,
                                IDENTIFIER=code_snippet.key.identifier,
                                DESCRIPTION=code_snippet.description,
                                START_LINE=code_snippet.start_line,
                                END_LINE=code_snippet.end_line,
                            )
                            for code_snippet in state.code_snippets
                        ]
                    ),
                    LS_CWD=self.ls_cwd,
                    CWD=challenge.workdir_from_dockerfile(),
                )
            ),
            *state.messages,  # type: ignore[list-item]
        ]

    def _parse_duplicate_code_snippet_output(self, output: str) -> bool:
        try:
            # Extract text between <is_satisfied> tags if present
            match = re.search(r"<is_satisfied>(.*?)</is_satisfied>", output)
            if match:
                return match.group(1).strip().lower() == "true"

            return output.strip().lower() == "true"
        except Exception:
            logger.error("Error parsing duplicate code snippet output: %s", output)
            return False

    def _parse_initial_code_snippet_requests_output(self, output: str) -> list[CodeSnippetRequest]:
        return [
            CodeSnippetRequest(request=match.group(1).strip())
            for match in re.finditer(r"<request>(.*?)</request>", output, re.DOTALL)
            if match.group(1).strip()
        ]

    def _parse_filter_code_snippets_output(self, output: str) -> bool:
        try:
            # Extract text between <is_relevant> tags if present
            match = re.search(r"<is_relevant>(.*?)</is_relevant>", output)
            if match:
                return match.group(1).strip().lower() == "true"

            return output.strip().lower() == "true"
        except Exception:
            logger.error("Error parsing filter code snippets output: %s", output)
            return False

    def _filter_code_snippet(
        self, requests: list[CodeSnippetRequest], code_snippet: ContextCodeSnippet, config: RunnableConfig
    ) -> bool:
        """Filter a code snippet based on the request."""
        return self.filter_code_snippets_chain.invoke(
            {
                "REQUESTS": "\n".join(request.request for request in requests),
                "CODE_SNIPPET": code_snippet,
            }
        )

    def _filter_code_snippets(
        self, requests: list[CodeSnippetRequest], code_snippets: list[ContextCodeSnippet], config: RunnableConfig
    ) -> list[ContextCodeSnippet]:
        """Filter a list of code snippets based on the request."""
        res = []
        with get_executor_for_config(config) as executor:
            futures = [
                executor.submit(
                    self._filter_code_snippet,
                    requests,
                    code_snippet,
                    config,
                )
                for code_snippet in code_snippets
            ]
            for future in as_completed(futures):
                if future.result():
                    res.append(code_snippets[futures.index(future)])

        return res

    def is_code_snippet_already_retrieved(
        self, existing_code_snippets: set[ContextCodeSnippet], snippet_request: CodeSnippetRequest
    ) -> bool:
        if not existing_code_snippets:
            return False

        res: bool = self.code_snippet_duplicates_chain.invoke(
            {
                "CODE_REQUEST": snippet_request.request,
                "CODE_SNIPPETS": "\n".join(
                    CODE_SNIPPET_KEY_TMPL.format(
                        FILE_PATH=code_snippet.key.file_path,
                        IDENTIFIER=code_snippet.key.identifier,
                        DESCRIPTION=code_snippet.description,
                        START_LINE=code_snippet.start_line,
                        END_LINE=code_snippet.end_line,
                    )
                    for code_snippet in existing_code_snippets
                ),
            }
        )
        return res

    def process_request(
        self, relevant_code_snippets: set[ContextCodeSnippet], request: CodeSnippetRequest, configuration: PatcherConfig
    ) -> list[ContextCodeSnippet]:
        """Process a request for a code snippet."""
        if self.is_code_snippet_already_retrieved(relevant_code_snippets, request):
            logger.info("Code snippet for request '%s' is already retrieved", request.request)
            return []

        logger.info("Retrieving code snippet for request '%s'", request.request)
        input_state = {
            "request": request.request,
            "challenge_task_dir": self.challenge.task_dir,
            "work_dir": configuration.work_dir,
        }
        configuration = configuration.clone()
        try:
            self.agent.invoke(
                input_state,
                config=RunnableConfig(
                    recursion_limit=configuration.context_retriever_recursion_limit,
                    configurable=configuration.model_dump(),
                ),
            )
        except langgraph.errors.GraphRecursionError:
            logger.error("Reached recursion limit for request '%s'", request.request)

        ctx_state_dict = self.agent.get_state(RunnableConfig(configurable=configuration.model_dump())).values  # type: ignore[attr-defined]
        try:
            ctx_state = CodeSnippetManagerState.model_validate(ctx_state_dict)
        except ValidationError as e:
            logger.error("Invalid state dict for request '%s': %s", request.request, e)
            return []

        logger.info("Retrieved %d code snippets for request '%s'", len(ctx_state.code_snippets), request.request)
        return ctx_state.code_snippets

    def retrieve_context(self, state: ContextRetrieverState, config: RunnableConfig) -> Command:
        """Retrieve the context for the diff analysis."""
        configuration = PatcherConfig.from_configurable(config)
        logger.info("Retrieving the context for the diff analysis in Challenge Task %s", self.challenge.name)
        logger.debug("Code snippet requests: %s", state.code_snippet_requests)

        res = []
        with get_executor_for_config(config) as executor:
            futures = [
                executor.submit(self.process_request, state.relevant_code_snippets, request, configuration)
                for request in state.code_snippet_requests
            ]

            for future in as_completed(futures):
                try:
                    new_snippets = future.result()
                    res.extend(new_snippets)
                except Exception as e:
                    logger.exception("Error processing request: %s", e)
                    continue

        return Command(
            update={
                "execution_info": state.execution_info,
                "relevant_code_snippets": set(self._filter_code_snippets(state.code_snippet_requests, res, config)),
            },
            goto=state.prev_node,
        )

    def get_initial_context(
        self, state: PatcherAgentState, config: RunnableConfig
    ) -> Command[Literal[PatcherAgentName.ROOT_CAUSE_ANALYSIS.value]]:  # type: ignore[name-defined]
        """Get the initial context for the diff analysis."""
        configuration = PatcherConfig.from_configurable(config)
        stacktrace = parse_stacktrace(state.context.sanitizer_output)
        challenge = _get_challenge(state.context.challenge_task_dir)

        # Request code snippet for the first two functions in the stacktrace
        logger.info("[%s] Getting initial context from stacktrace", self.challenge.task_meta.task_id)
        res: list[ContextCodeSnippet] = []

        def process_request(request: CodeSnippetRequest | str) -> list:
            try:
                if isinstance(request, str):
                    request = CodeSnippetRequest(request=request)
                logger.info(
                    "[%s] Processing request %s",
                    self.challenge.task_meta.task_id,
                    request.request,
                )
                return self.process_request(state.relevant_code_snippets, request, configuration)
            except Exception:
                logger.warning(
                    "[%s] Error processing request %s, continuing",
                    self.challenge.task_meta.task_id,
                    request.request if isinstance(request, CodeSnippetRequest) else request,
                )
                return []

        # Get only the first few stackframes that are not in the llvm-project to
        # avoid looking for common functions that are not relevant to the
        # challenge
        stackframes = []
        for frame in stacktrace.frames:
            frames = []
            for stackframe in frame:
                if (
                    challenge.project_name != "llvm-project"
                    and stackframe.filename
                    and stackframe.filename.startswith("/src/llvm-project/compiler-rt")
                ):
                    continue
                if (
                    challenge.project_name != "glibc"
                    and stackframe.filename
                    and stackframe.filename.startswith("/lib/x86_64-linux-gnu")
                ):
                    continue

                skip_names = ["__libc_start_main", "__gmon_start__", "_start"]
                skip_name = any(func in stackframe.function_name for func in skip_names if stackframe.function_name)
                if skip_name:
                    continue

                frames.append(stackframe)
            stackframes.append(frames)

        stackframes = [
            stackframe for frame in stackframes for stackframe in frame[: configuration.n_initial_stackframes]
        ]
        requests = [
            CodeSnippetRequest(
                request=f"Implementation of `{stackframe.function_name}` in `{stackframe.filename}`(line {stackframe.fileline})"
            )
            for stackframe in stackframes
            if stackframe.function_name
        ]

        with get_executor_for_config(config) as executor:
            futures = [
                executor.submit(
                    process_request,
                    request,
                )
                for request in requests
            ]
            for future in as_completed(futures):
                try:
                    new_snippets = future.result()
                    res.extend(new_snippets)
                except Exception as e:
                    logger.exception("Error processing request: %s", e)
                    continue

        initial_code_snippet_requests = self.initial_snippets_chain.invoke(
            {
                "STACKTRACE": state.cleaned_stacktrace,
                "CODE_SNIPPETS": "\n".join(str(code_snippet) for code_snippet in res),
            }
        )
        with get_executor_for_config(config) as executor:
            futures = [
                executor.submit(self.process_request, set(res), request, configuration)
                for request in initial_code_snippet_requests
            ]

            for future in as_completed(futures):
                try:
                    new_snippets = future.result()
                    res.extend(new_snippets)
                except Exception as e:
                    logger.exception("Error processing request: %s", e)
                    continue

        return Command(
            update={
                "relevant_code_snippets": set(
                    self._filter_code_snippets(requests + initial_code_snippet_requests, res, config)
                ),
            },
            goto=PatcherAgentName.ROOT_CAUSE_ANALYSIS.value,
        )
