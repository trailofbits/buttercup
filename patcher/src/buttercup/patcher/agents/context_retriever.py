"""Agent that retrieves code snippets from the project."""

from __future__ import annotations

import logging
import operator
import re
import tempfile
import time
from concurrent.futures import TimeoutError, as_completed
from dataclasses import dataclass, field
from itertools import groupby
from operator import itemgetter
from pathlib import Path
from typing import Annotated, Any, Literal

import langgraph.errors
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import Runnable, RunnableConfig
from langchain_core.runnables.config import get_executor_for_config
from langchain_core.tools import tool
from langchain_core.tools.base import InjectedToolCallId
from langchain_openai.chat_models.base import BaseChatOpenAI
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END
from langgraph.prebuilt import InjectedState
from langgraph.prebuilt.chat_agent_executor import create_react_agent
from langgraph.types import Command
from pydantic import Field, ValidationError
from redis import Redis

from buttercup.common.challenge_task import ChallengeTask
from buttercup.common.llm import ButtercupLLM, create_default_llm
from buttercup.common.stack_parsing import CrashInfo, parse_stacktrace
from buttercup.patcher.agents.common import (
    BaseCtxState,
    CodeSnippetKey,
    CodeSnippetRequest,
    ContextCodeSnippet,
    ContextRetrieverState,
    PatcherAgentBase,
    PatcherAgentName,
    PatcherAgentState,
    get_stacktraces_from_povs,
)
from buttercup.patcher.agents.config import PatcherConfig
from buttercup.patcher.agents.tools import (
    MAX_OUTPUT_LENGTH,
    cat,
    get_callees,
    get_callers,
    get_function,
    get_function_tool_impl,
    get_lines,
    get_type,
    get_type_tool_impl,
    grep,
    ls,
)
from buttercup.patcher.utils import TruncatePosition, find_file_in_source_dir, get_challenge, truncate_output

# ruff: noqa: E501

logger = logging.getLogger(__name__)

CUSTOM_TEST_MAP_NAME = "custom_test_map"

SYSTEM_TMPL = """You are an agent - please keep going until the user's query is completely resolved, before ending your turn and yielding back to the user. Only terminate your turn when you are sure that the problem is solved.
If you are not sure about file content or codebase structure pertaining to the user's request, use your tools to read files and gather the relevant information: do NOT guess or make up an answer.
You MUST plan extensively before each function call, and reflect extensively on the outcomes of the previous function calls. DO NOT do this entire process by making function calls only, as this can impair your ability to solve the problem and think insightfully.

Assist a software engineer in finding and extracting relevant code snippets from a software project. Use only the provided tools and project context. Prioritize accuracy and completeness. Avoid speculation."""

CODE_SNIPPET_KEY_TMPL = """
<code_snippet>
<identifier>{IDENTIFIER}</identifier>
<description>{DESCRIPTION}</description>
<file_path>{FILE_PATH}</file_path>
<start_line>{START_LINE}</start_line>
<end_line>{END_LINE}</end_line>
</code_snippet>
"""

USER_MSG = """Use the available tools to explore the project and extract relevant code snippets.

Project:
<project_name>
{PROJECT_NAME}
</project_name>

Engineer request:
<engineer_request>
{REQUEST}
</engineer_request>

Tracked snippets so far:
<code_snippets>
{CODE_SNIPPETS}
</code_snippets>

Current directory:
<cwd>
{CWD}
</cwd>

Files in current directory:
<ls_cwd>
{LS_CWD}
</ls_cwd>

Guidelines:
- DO NOT fabricate code, paths, or functionality.
- Your first step should always be to identify the exact function, type, or code range using tools like `get_function` or `get_type`.
- ONLY use `track_snippet` after you have confirmed that:
  1. The code snippet is correct and complete,
  2. It answers the engineer's request,
- Do NOT call `track_snippet` speculatively or based on partial guesses.
- Clearly explain your reasoning for calling `track_snippet`, and what the snippet represents.
- If a tool fails or more context is needed, explain the issue and propose next steps.

REMEMBER: The purpose of `track_snippet` is to **record already verified** code—not to discover or search.
"""

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
4. Is the request fully satisfied? If all versions of a function/type/variable are requested, but only some of them are available, the request is not satisfied.

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
    ],
)

INITIAL_CODE_SNIPPET_REQUESTS_USER_MSG = """You are an AI assistant tasked with identifying additional code snippets needed to understand a security vulnerability.

You have access to:
1. One or more stacktraces showing where the vulnerability occurred
2. Any code snippets already retrieved

<stacktraces>
{STACKTRACES}
</stacktraces>

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

If you do not have any code snippets to request, do not output any <request> tags.
"""

INITIAL_CODE_SNIPPET_REQUESTS_PROMPT = ChatPromptTemplate.from_messages(
    [
        ("user", INITIAL_CODE_SNIPPET_REQUESTS_USER_MSG),
    ],
)

FILTER_CODE_SNIPPETS_USER_MSG = """You are an AI assistant. Your job is to evaluate whether a code snippet is relevant to one of the requests.
Be mindful that the function/type/variable names might be slightly different from the ones in the requests (e.g. they might be in a slightly different file, or they might have some prefix/suffix like OSS_FUZZ_). If you are not sure, consider the code snippet as relevant.

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
    ],
)

FIND_TESTS_SYSTEM_TMPL = """You are an agent - please keep going until the user's query is completely resolved, before ending your turn and yielding back to the user. Only terminate your turn when you are sure that the problem is solved.
If you are not sure about file content or codebase structure pertaining to the user's request, use your tools to read files and gather the relevant information: do NOT guess or make up an answer.
You MUST plan extensively before each function call, and reflect extensively on the outcomes of the previous function calls. DO NOT do this entire process by making function calls only, as this can impair your ability to solve the problem and think insightfully."""

FIND_TESTS_USER_MSG = """Your goal is to provide accurate and complete \
instructions for building and testing the project. You must continue working \
until you have valid instructions confirmed by the `test_instructions` function.

Project name:
<project_name>
{PROJECT_NAME}
</project_name>

Working directory:
<current_working_directory>
{CWD}
</current_working_directory>

The container used to run the tests is built with the following Dockerfile:
<dockerfile>
{DOCKERFILE}
</dockerfile>

Follow these steps to complete your task:

1. Build the project:
   a. Search for build scripts in the /src directory. These are usually used by oss-fuzz to build the project.
   b. If not found, check README, Makefile, CMakeLists.txt, and similar files.
   c. Attempt to build the project (no fuzz-specific configurations).
   d. If the build fails retry.
   e. Continue until you achieve a successful build.

2. Run the test suite:
   a. Search for documented test instructions or test-related files.
   b. Run the actual tests (not just linting or setup procedures).
   c. If tests fail to run, troubleshoot and retry.
   d. Ensure that tests actually ran and passed.

3. Analyze and report:
   After each major step (build and test), analyze the results and report your findings.

4. Validate instructions:
   a. Once you believe you have found the correct set of instructions to build and test the project, call the `test_instructions` function with these instructions as the argument.
   b. If the `test_instructions` function indicates that the instructions are not valid, revise your approach and try again.
   c. Do not terminate your process until you have called `test_instructions` and received confirmation that the instructions are valid.

Throughout your analysis, wrap your discovery process inside <discovery_process> tags. Include the following:

1. File Analysis:
   - List all potentially relevant build and test files.
   - Briefly describe the purpose of each file.

2. Build Process:
   - Detail each step of the build process.
   - Document any commands attempted and their outcomes.
   - If errors occur, list them and describe your troubleshooting steps.

3. Test Process:
   - Outline each step of the test process.
   - Document test commands and their results.
   - If tests fail, describe the errors and your attempts to resolve them.

4. Decision Making:
   - Explain your reasoning for choosing specific build or test methods.
   - Discuss any alternatives considered and why they were rejected.

This detailed breakdown will help ensure a thorough and transparent approach to solving the task. It's OK for this section to be quite long.

Remember:
- Do not try to build a project solely based on your previous knowledge of the project.
- Do not guess or make up answers about file content or codebase structure.
- Use your available tools to read files and gather relevant information when needed.
- Check the build/test commands used by oss-fuzz to have an idea of what to do.
- You SHOULD NOT build the project with fuzzing-specific configurations or fuzzers enabled.
- Plan extensively before each function call and reflect on the outcomes of previous calls.
- Continue working until you have valid instructions confirmed by the `test_instructions` function.

Begin your analysis and proceed step-by-step through the process of discovering the build and test instructions for the given project.
"""

ARE_VALID_TEST_INSTRUCTIONS_USER_MSG = """
You are an expert in software testing. Your task is to evaluate the validity of a set of test instructions.

Here are the test instructions:
<test_instructions>
{TEST_INSTRUCTIONS}
</test_instructions>

Here is the output of the test instructions:
<output>
{OUTPUT}
</output>

Here is the error of the test instructions:
<error>
{ERROR}
</error>

Evaluate whether the test instructions ran correctly.
Test instructions are valid if:
- The project is actually built (e.g. the build commands are correct and the project is built successfully)
- Tests are actually running (e.g. the test commands are correct and the tests are running)
- All tests passed (e.g. the tests are passing)

Wrap your reasoning in <reasoning> tags, then return the result in <are_valid> tags.
For example, if the test instructions are valid, you should return:
<reasoning>
[.....]
</reasoning>
<are_valid>TRUE</are_valid>
"""

ARE_VALID_TEST_INSTRUCTIONS_PROMPT = ChatPromptTemplate.from_messages(
    [
        ("user", ARE_VALID_TEST_INSTRUCTIONS_USER_MSG),
        ("ai", "<reasoning>"),
    ],
)


class CodeSnippetManagerState(BaseCtxState):
    """State for the code snippet manager"""

    request: str
    code_snippets: Annotated[list[ContextCodeSnippet], operator.add] = Field(default_factory=list)


class FindTestsState(BaseCtxState):
    """State for the find tests agent."""

    tests_instructions: Annotated[str | None, reduce_test_instructions] = Field(default=None)


def reduce_test_instructions(cur_instr: str | None, new_instr: str | None) -> str | None:
    if not cur_instr:
        return new_instr
    if not new_instr:
        return cur_instr

    # Both test instructions succeeded (to run, at least), select the last one
    return new_instr


@tool
def think(reasoning: str) -> str:
    """Think more about the problem and the tools available to you."""
    return f"""Think more about the problem and the tools available to you. \
You should try to find the most relevant code snippet. Reasoning: \
{reasoning}. Did you call the `get_function`, \
`get_type`, `track_snippet` tools \
with the newly discovered information?"""


def _return_command_tool_message(
    tool_call_id: str,
    message: str,
    new_code_snippets: list[ContextCodeSnippet] | None = None,
) -> Command:
    update_state: dict[str, Any] = {
        "messages": [ToolMessage(content=message, tool_call_id=tool_call_id)],
    }
    if new_code_snippets:
        update_state["code_snippets"] = new_code_snippets

    return Command(update=update_state)


@tool
def track_snippet(
    file_path: str,
    code_snippet_description: str,
    function_name: str | None,
    type_name: str | None,
    start_line: int | None,
    end_line: int | None,
    *,
    state: Annotated[CodeSnippetManagerState, InjectedState],
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command:
    """Track a range of lines from a file as a code snippet.

    This function records a code snippet from the given file, either by specifying
    a line range or by identifying a function or type name. If `function_name` or
    `type_name` is provided, the function attempts to retrieve the code snippet
    using specialized tools. If these fail or are not provided, it falls back to
    manually extracting lines from the file (if provided).

    The resulting snippet is enriched with a description and optionally buffered
    with a few lines before and after the requested range to reduce the impact of
    minor off-by-one or range errors.

    Args:
        file_path (str): Path to the source file.
        code_snippet_description (str): Human-readable description of the code snippet
            (e.g., "Implementation of validate_input()", "Definition of struct Foo").
        function_name (str | None): Name of the function to extract, if applicable.
        type_name (str | None): Name of the type to extract, if applicable.
        start_line (int | None): 1-indexed start line number for the snippet.
        end_line (int | None): 1-indexed end line number for the snippet.

    Notes:
        - If `function_name` or `type_name` is provided, the function will try to use
          `get_function` or `get_type` first.
        - Only one of `function_name`, `type_name`, (`start_line` and
          `end_line`) should be provided; do not pass two or more of them.
        - `function_name` must NOT contain the class name if it is a method. Do
           NOT pass `function_name=MyClass::foo`, instead pass `function_name=foo`.

    Example:
        >>> track_snippet(
        ...     file_path="src/utils.c",
        ...     start_line=42,
        ...     end_line=56,
        ...     function_name=None,
        ...     type_name=None,
        ...     code_snippet_description="Buffer overflow check implementation",
        ... )
        >>> track_snippet(
        ...     file_path="src/utils.c",
        ...     start_line=None,
        ...     end_line=None,
        ...     function_name="foo",
        ...     type_name=None,
        ...     code_snippet_description="Implementation of function foo",
        ... )

    """
    if start_line is None and end_line is None and function_name is None and type_name is None:
        raise ValueError("Either (start_line and end_line) or function_name or type_name must be provided")
    if function_name and type_name:
        raise ValueError("Only one of function_name or type_name must be provided")

    path = Path(file_path)
    code_snippets = None
    if function_name:
        code_snippets = get_function_tool_impl(function_name, file_path, state)
    elif type_name:
        code_snippets = get_type_tool_impl(type_name, file_path, state)
    elif start_line and end_line:
        logger.info("Getting lines %d-%d of %s", start_line, end_line, path)
        challenge = get_challenge(state.challenge_task_dir)
        get_lines_res_cmd = challenge.exec_docker_cmd(["cat", str(path)])
        # Get a few lines before and after the requested lines in case the LLM does
        # small mistakes when requesting the lines
        start_line = max(0, start_line - 5)
        end_line = end_line + 5
        get_lines_output = get_lines_res_cmd.output.decode("utf-8").splitlines()[start_line:end_line]
        if not path.is_absolute():
            path = challenge.workdir_from_dockerfile().joinpath(path)

        code_snippet = ContextCodeSnippet(
            key=CodeSnippetKey(
                file_path=path.as_posix(),
            ),
            start_line=start_line,
            end_line=end_line,
            code="\n".join(get_lines_output),
            description=code_snippet_description,
            can_patch=find_file_in_source_dir(challenge, path) is not None,
        )
        code_snippets = [code_snippet]

    if not code_snippets:
        raise ValueError(
            f"No code snippets found for {code_snippet_description} (function_name={function_name}, type_name={type_name}, start_line={start_line}, end_line={end_line}). Make sure the snippet exists before trying to track it.",
        )

    return _return_command_tool_message(
        tool_call_id,
        f"Found {len(code_snippets)} code snippets for {code_snippet_description}",
        code_snippets,
    )


@tool
def sh(
    command: str,
    *,
    state: Annotated[FindTestsState, InjectedState],
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command:
    """Execute a shell command within the project environment and return its output/error.

    Use this tool only for shell commands that are not supported by the more specific tools (e.g., `cat`, `ls`, `head`, `grep`).
    """
    logger.info("Running command: %s", command)

    command_file_path = None
    try:
        with tempfile.NamedTemporaryFile(dir=state.work_dir, delete=False) as f:
            f.write(b"#!/bin/bash\n")
            f.write(command.encode("utf-8"))
            f.write(b"\n")
            f.flush()

            command_file_path = Path(f.name)
            command_file_path.chmod(0o755)

        challenge = get_challenge(state.challenge_task_dir, state.challenge_task_dir_ro)
        sh_cmd_res = challenge.exec_docker_cmd(
            "/tmp/command.sh",
            mount_dirs={
                command_file_path: Path("/tmp/command.sh"),
            },
        )

        message = f"""<command>
{command}
</command>
<return_code>
{sh_cmd_res.returncode}
</return_code>
<output>
{truncate_output(sh_cmd_res.output.decode("utf-8"), MAX_OUTPUT_LENGTH)}
</output>
<error>
{truncate_output(sh_cmd_res.error.decode("utf-8"), MAX_OUTPUT_LENGTH)}
</error>

Remember to call the `test_instructions` tool to log and validate any test commands you find and try.
    """
        return Command(
            update={
                "messages": [ToolMessage(message, tool_call_id=tool_call_id)],
            },
        )
    except Exception as e:
        logger.exception("Error running command: %s", command)
        raise e
    finally:
        if command_file_path:
            command_file_path.unlink()


def _are_test_instructions_valid(instructions: str, output: bytes, error: bytes) -> bool:
    """Validate a set of test instructions by executing them inside the project environment."""
    llm = create_default_llm(
        model_name=ButtercupLLM.OPENAI_GPT_4_1.value,
        fallback_models=[ButtercupLLM.CLAUDE_4_SONNET, ButtercupLLM.GEMINI_PRO],
    )
    chain = ARE_VALID_TEST_INSTRUCTIONS_PROMPT | llm | StrOutputParser()
    res = chain.invoke(
        {
            "TEST_INSTRUCTIONS": instructions,
            "OUTPUT": truncate_output(output.decode("utf-8"), MAX_OUTPUT_LENGTH, TruncatePosition.START),
            "ERROR": truncate_output(error.decode("utf-8"), MAX_OUTPUT_LENGTH, TruncatePosition.START),
        },
    )
    match = re.search(r"<are_valid>(.*?)</are_valid>", res)
    if match:
        return match.group(1).strip().lower() in ["true", "yes"]

    return res.strip().lower() in ["true", "yes"]


@tool
def test_instructions(
    instructions: list[str],
    *,
    state: Annotated[FindTestsState, InjectedState],
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command:
    """Validate a set of test instructions by executing them inside the project environment.

    You MUST call this tool to verify that the provided test instructions work as expected on a clean copy of the project.
    This tool will execute the commands in a shell and check if the test suite runs successfully.
    You must provide the build instructions + test instructions as a list of strings, so that the challenge can be built and tested in a clean environment.

    - If the instructions fail (non-zero exit code or no tests run), analyze the output, correct the commands, and call this tool again with the updated instructions.
    - You can call this tool multiple times during the discovery process, but only the **last successful call** will be recorded and used.
    - Instructions must be based strictly on project files (e.g. README, Makefile, CI configs); do not guess or fabricate commands.
    """
    test_file_path = None
    try:
        instructions_str = "#!/bin/bash\n"
        instructions_str += "\n".join(instructions)
        instructions_str += "\n"

        with tempfile.NamedTemporaryFile(dir=state.work_dir, delete=False) as f:
            f.write(instructions_str.encode("utf-8"))
            f.flush()

            test_file_path = Path(f.name)
            test_file_path.chmod(0o755)

        clean_challenge = ChallengeTask(state.challenge_task_dir_ro)
        with clean_challenge.get_rw_copy(state.work_dir) as challenge:
            challenge.apply_patch_diff()
            sh_cmd_res = challenge.exec_docker_cmd(
                challenge.get_test_sh_script("/tmp/test.sh"),
                mount_dirs={
                    test_file_path: Path("/tmp/test.sh"),
                },
            )

        # We truncate the output at the start so we can see, in the worst case,
        # the last lines of the output, which hopefully contain the test results
        msg = f"""<command>
{instructions}
</command>
<return_code>
{sh_cmd_res.returncode}
</return_code>
<output>
{truncate_output(sh_cmd_res.output.decode("utf-8"), MAX_OUTPUT_LENGTH, TruncatePosition.START)}
</output>
<error>
{truncate_output(sh_cmd_res.error.decode("utf-8"), MAX_OUTPUT_LENGTH, TruncatePosition.START)}
</error>
    """
        if sh_cmd_res.success and _are_test_instructions_valid(instructions_str, sh_cmd_res.output, sh_cmd_res.error):
            res_instructions = instructions_str
            msg = f"""Test instructions passed:
<result>
{msg}
</result>

The last tracked instructions are correct and valid. You can stop here."""
        else:
            res_instructions = None
            msg = f"""Failed to run test instructions:
<result>
{msg}
</result>

Test instructions were NOT run correctly, please analyze the output and correct the commands.
You CANNOT stop here, you MUST fix the test instructions and call this tool again.
"""

        return Command(
            update={
                "tests_instructions": res_instructions,
                "messages": [ToolMessage(msg, tool_call_id=tool_call_id)],
            },
            goto=END,
        )
    except Exception as e:
        logger.exception("Error running test instructions: %s", instructions)
        raise e
    finally:
        if test_file_path:
            test_file_path.unlink()


@dataclass
class ContextRetrieverAgent(PatcherAgentBase):
    """Agent that retrieves code snippets from the project."""

    redis: Redis | None = None
    find_tests: bool = True

    agent: Runnable = field(init=False)
    llm: BaseChatOpenAI = field(init=False)
    cheap_llm: BaseChatOpenAI = field(init=False)
    cheap_fallback_llms: list[BaseChatOpenAI] = field(init=False)
    initial_snippets_chain: Runnable = field(init=False)
    find_tests_agent: Runnable = field(init=False)

    def __post_init__(self) -> None:
        """Initialize a few fields"""
        self.llm = create_default_llm(model_name=ButtercupLLM.OPENAI_GPT_4_1.value)
        self.cheap_llm = create_default_llm(model_name=ButtercupLLM.OPENAI_GPT_4_1_MINI.value)
        self.cheap_fallback_llms = [
            create_default_llm(model_name=ButtercupLLM.CLAUDE_3_7_SONNET.value),
            create_default_llm(model_name=ButtercupLLM.GEMINI_PRO.value),
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
            track_snippet,
            think,
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

        find_tests_tools = [
            ls,
            grep,
            get_lines,
            cat,
            sh,
            test_instructions,
        ]
        find_tests_checkpointer = InMemorySaver()
        default_find_tests_agent = create_react_agent(
            model=self.llm,
            state_schema=FindTestsState,
            tools=find_tests_tools,
            prompt=self._find_tests_prompt,
            checkpointer=find_tests_checkpointer,
        )
        fallback_find_tests_agents = [
            create_react_agent(
                model=llm,
                state_schema=FindTestsState,
                tools=find_tests_tools,
                prompt=self._find_tests_prompt,
                checkpointer=find_tests_checkpointer,
            )
            for llm in [self.cheap_llm, *self.cheap_fallback_llms]
        ]
        self.find_tests_agent = default_find_tests_agent.with_fallbacks(fallback_find_tests_agents)

    def _prompt(self, state: CodeSnippetManagerState) -> list[AnyMessage]:
        challenge = get_challenge(state.challenge_task_dir)
        ls_cwd = challenge.exec_docker_cmd(["ls", "-la"])
        if ls_cwd.success:
            ls_cwd = ls_cwd.output.decode("utf-8")
        else:
            ls_cwd = "ls cwd failed"

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
                        ],
                    ),
                    LS_CWD=ls_cwd,
                    CWD=challenge.workdir_from_dockerfile(),
                ),
            ),
            *state.messages,  # type: ignore[list-item]
        ]

    def _find_tests_prompt(self, state: FindTestsState) -> list[AnyMessage]:
        challenge = get_challenge(state.challenge_task_dir, state.challenge_task_dir_ro)

        ls_cwd = challenge.exec_docker_cmd(["ls", "-la"])
        if ls_cwd.success:
            ls_cwd = ls_cwd.output.decode("utf-8")
        else:
            ls_cwd = "ls cwd failed"

        ls_src = challenge.exec_docker_cmd(["ls", "-la", "/src"])
        if ls_src.success:
            ls_src = ls_src.output.decode("utf-8")
        else:
            ls_src = "ls src failed"

        try:
            dockerfile = challenge.dockerfile_path().read_text()
        except Exception:
            dockerfile = "Dockerfile not found"

        return [
            SystemMessage(content=FIND_TESTS_SYSTEM_TMPL),
            HumanMessage(
                content=FIND_TESTS_USER_MSG.format(
                    PROJECT_NAME=challenge.project_name,
                    CWD=challenge.workdir_from_dockerfile(),
                    DOCKERFILE=dockerfile,
                ),
            ),
            AIMessage(
                content=f"""`ls` / `ls {challenge.workdir_from_dockerfile()}`:
<ls_cwd>
{truncate_output(ls_cwd, MAX_OUTPUT_LENGTH)}
</ls_cwd>""",
            ),
            AIMessage(
                content=f"""`ls /src`:
<ls_src>
{truncate_output(ls_src, MAX_OUTPUT_LENGTH)}
</ls_src>""",
            ),
            *state.messages,  # type: ignore[list-item]
            AIMessage(content="""<project_analysis>"""),
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
            if match.group(1) and match.group(1).strip()
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
        self,
        requests: list[CodeSnippetRequest],
        code_snippet: ContextCodeSnippet,
        config: RunnableConfig,
    ) -> bool:
        """Filter a code snippet based on the request."""
        return self.filter_code_snippets_chain.invoke(
            {
                "REQUESTS": "\n".join(request.request for request in requests),
                "CODE_SNIPPET": code_snippet,
            },
        )

    def _filter_code_snippets(
        self,
        requests: list[CodeSnippetRequest],
        code_snippets: list[ContextCodeSnippet],
        config: RunnableConfig,
    ) -> list[ContextCodeSnippet]:
        """Filter a list of code snippets based on the request."""
        configuration = PatcherConfig.from_configurable(config)
        res = []
        with get_executor_for_config(RunnableConfig(max_concurrency=configuration.max_concurrency)) as executor:
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
        self,
        existing_code_snippets: set[ContextCodeSnippet],
        snippet_request: CodeSnippetRequest,
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
            },
        )
        return res

    def process_request(
        self,
        challenge_task_dir: Path,
        relevant_code_snippets: set[ContextCodeSnippet],
        request: CodeSnippetRequest,
        configuration: PatcherConfig,
    ) -> list[ContextCodeSnippet]:
        """Process a request for a code snippet."""
        if self.is_code_snippet_already_retrieved(relevant_code_snippets, request):
            logger.info("Code snippet for request '%s' is already retrieved", request.request)
            return []

        logger.info("Retrieving code snippet for request '%s'", request.request)
        input_state = {
            "request": request.request,
            "challenge_task_dir": challenge_task_dir,
            "work_dir": configuration.work_dir,
        }
        configuration = configuration.clone()
        try:
            self.agent.invoke(
                input_state,
                config=RunnableConfig(
                    recursion_limit=configuration.ctx_retriever_recursion_limit,
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

        # NOTE: We create a read-write copy of the challenge task directory
        # because the agent's tools use `exec_docker_cmd` which requires write
        # access (marked with `read_write_decorator`).  While these tools only
        # perform read operations (ls, cat, grep), we create the copy to satisfy
        # the decorator's requirements and maintain consistency.
        with self.challenge.get_rw_copy(configuration.work_dir) as challenge_rw:
            res = []
            with get_executor_for_config(RunnableConfig(max_concurrency=configuration.max_concurrency)) as executor:
                futures = [
                    executor.submit(
                        self.process_request,
                        challenge_rw.task_dir,
                        state.relevant_code_snippets,
                        request,
                        configuration,
                    )
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

    def _get_code_requests_from_stacktrace(
        self,
        stacktraces: list[CrashInfo],
        configuration: PatcherConfig,
    ) -> list[CodeSnippetRequest]:
        """Return a list of code snippet requests based on the stacktraces,
        grouping them together by function name and filename.

        This is used to retrieve the initial context for the root cause analysis.
        """
        # Extract stack frames from the various stacktraces we have, but ignore
        # common functions that are not relevant to the challenge (e.g.
        # __libc_start_main, __gmon_start__, _start, etc.)
        stackframes = []
        for stacktrace in stacktraces:
            for frame in stacktrace.frames:
                frames = []
                for stackframe in frame:
                    if (
                        self.challenge.project_name != "llvm-project"
                        and stackframe.filename
                        and stackframe.filename.startswith("/src/llvm-project/compiler-rt")
                    ):
                        continue
                    if (
                        self.challenge.project_name != "glibc"
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

        # We consider only the first `n_initial_stackframes` stackframes for each stacktrace
        stackframes = [
            stackframe for frame in stackframes for stackframe in frame[: configuration.n_initial_stackframes]
        ]

        # Return the code snippet requests, making sure there are no duplicates
        # (e.g. same function name and filename)
        requests_data = sorted(
            [
                (stackframe.function_name, stackframe.filename, stackframe.fileline)
                for stackframe in stackframes
                if stackframe.function_name
            ],
            key=itemgetter(0, 1),
        )

        requests = []
        for (func_name, filename), group in groupby(requests_data, key=itemgetter(0, 1)):
            filelines = sorted(set(line for _, _, line in group))
            requests.append(
                CodeSnippetRequest(
                    request=f"Implementation of `{func_name}` in `{filename}` (around lines {', '.join(map(str, filelines))})",
                ),
            )

        return requests

    def get_initial_context(
        self,
        state: PatcherAgentState,
        config: RunnableConfig,
    ) -> Command[Literal[PatcherAgentName.ROOT_CAUSE_ANALYSIS.value]]:  # type: ignore[name-defined]
        """Get the initial context for the diff analysis."""
        configuration = PatcherConfig.from_configurable(config)
        stacktraces = [parse_stacktrace(pov.sanitizer_output) for pov in state.context.povs]

        # Request code snippet for the first two functions in the stacktrace
        logger.info("[%s] Getting initial context from stacktrace", self.challenge.task_meta.task_id)
        res: list[ContextCodeSnippet] = []

        def process_request(challenge_task_dir: Path, request: CodeSnippetRequest | str) -> list:
            try:
                if isinstance(request, str):
                    request = CodeSnippetRequest(request=request)
                logger.info(
                    "[%s] Processing request %s",
                    self.challenge.task_meta.task_id,
                    request.request,
                )
                return self.process_request(challenge_task_dir, state.relevant_code_snippets, request, configuration)
            except Exception:
                logger.warning(
                    "[%s] Error processing request %s, continuing",
                    self.challenge.task_meta.task_id,
                    request.request if isinstance(request, CodeSnippetRequest) else request,
                )
                return []

        requests = self._get_code_requests_from_stacktrace(stacktraces, configuration)
        # NOTE: We create a read-write copy of the challenge task directory
        # because the agent's tools use `exec_docker_cmd` which requires write
        # access (marked with `read_write_decorator`).  While these tools only
        # perform read operations (ls, cat, grep), we create the copy to satisfy
        # the decorator's requirements and maintain consistency.
        with self.challenge.get_rw_copy(configuration.work_dir) as challenge_rw:
            with get_executor_for_config(RunnableConfig(max_concurrency=configuration.max_concurrency)) as executor:
                futures = [
                    executor.submit(
                        process_request,
                        challenge_rw.task_dir,
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
                    "STACKTRACES": "\n".join(get_stacktraces_from_povs(state.context.povs)),
                    "CODE_SNIPPETS": "\n".join(code_snippet.commented_code(stacktraces) for code_snippet in res),
                },
            )
            with get_executor_for_config(RunnableConfig(max_concurrency=configuration.max_concurrency)) as executor:
                futures = [
                    executor.submit(
                        self.process_request,
                        challenge_rw.task_dir,
                        set(res),
                        request,
                        configuration,
                    )
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
                    self._filter_code_snippets(requests + initial_code_snippet_requests, res, config),
                ),
            },
            goto=PatcherAgentName.ROOT_CAUSE_ANALYSIS.value,
        )

    def _get_custom_test_instructions(self) -> str | None:
        if self.redis is None:
            return None

        return self.redis.hget(CUSTOM_TEST_MAP_NAME, self.challenge.task_meta.task_id)  # type: ignore[return-value]

    def _save_custom_test_instructions(self, instructions: str) -> None:
        if self.redis is None:
            return
        self.redis.hset(CUSTOM_TEST_MAP_NAME, self.challenge.task_meta.task_id, instructions)

    def find_tests_node(
        self,
        state: PatcherAgentState,
        config: RunnableConfig,
    ) -> Command[Literal[PatcherAgentName.ROOT_CAUSE_ANALYSIS.value]]:  # type: ignore[name-defined]
        """Determine instructions to run tests in the challenge task."""
        configuration = PatcherConfig.from_configurable(config)
        logger.info(
            "Determining instructions to run tests in Challenge Task %s/%s",
            self.challenge.task_meta.task_id,
            self.challenge.name,
        )
        challenge_ossfuzz_path = self.challenge.get_oss_fuzz_path().joinpath(f"projects/{self.challenge.project_name}")
        test_sh_path = challenge_ossfuzz_path.joinpath("test.sh")
        if test_sh_path.exists():
            return Command(
                update={
                    "tests_instructions": test_sh_path.read_text(),
                },
                goto=PatcherAgentName.ROOT_CAUSE_ANALYSIS.value,
            )

        custom_test_instructions = self._get_custom_test_instructions()
        if custom_test_instructions:
            return Command(
                update={
                    "tests_instructions": custom_test_instructions,
                },
                goto=PatcherAgentName.ROOT_CAUSE_ANALYSIS.value,
            )

        if not self.find_tests:
            logger.info("Skipping finding tests because disabled by user")
            return Command(
                goto=PatcherAgentName.ROOT_CAUSE_ANALYSIS.value,
            )

        clean_challenge = self.challenge.get_clean_task(configuration.tasks_storage)
        with clean_challenge.get_rw_copy(configuration.work_dir) as clean_challenge_rw:
            clean_challenge_rw.apply_patch_diff()
            input_state = FindTestsState(
                challenge_task_dir_ro=clean_challenge.task_dir,
                challenge_task_dir=clean_challenge_rw.task_dir,
                work_dir=configuration.work_dir,
                messages=[],
            )

            configuration = configuration.clone()

            def run_find_tests_agent() -> FindTestsState | None:
                """Run the find tests agent with timeout protection."""
                try:
                    agent_state = input_state
                    for _ in range(10):
                        self.find_tests_agent.invoke(
                            agent_state,
                            config=RunnableConfig(
                                recursion_limit=configuration.ctx_retriever_recursion_limit,
                                configurable=configuration.model_dump(),
                            ),
                        )
                        agent_state_dict = self.find_tests_agent.get_state(  # type: ignore[attr-defined]
                            RunnableConfig(configurable=configuration.model_dump()),
                        ).values
                        try:
                            agent_state = FindTestsState.model_validate(agent_state_dict)
                        except ValidationError as e:
                            logger.error("Invalid state dict for finding tests: %s", e)
                            return None

                        if agent_state.tests_instructions:
                            return agent_state

                        agent_state.messages = [
                            *agent_state.messages,
                            HumanMessage(
                                content="You did not call `test_instructions` successfully yet. Please try again and harder to find the instructions to build and test the project.",
                            ),
                        ]
                except langgraph.errors.GraphRecursionError:
                    logger.error(
                        "Reached recursion limit for finding tests in Challenge Task %s/%s",
                        self.challenge.task_meta.task_id,
                        self.challenge.name,
                    )
                except Exception as e:
                    logger.exception("Error finding tests: %s", e)

                return None

            # Run the find tests agent with a 30-minute timeout
            start_time = time.time()
            timeout_seconds = 30 * 60  # 30 minutes

            try:
                with get_executor_for_config(RunnableConfig(max_concurrency=1)) as executor:
                    future = executor.submit(run_find_tests_agent)
                    agent_state = future.result(timeout=timeout_seconds)

                    if agent_state and agent_state.tests_instructions:
                        elapsed_time = time.time() - start_time
                        logger.info(
                            "Successfully found test instructions in %.2f seconds for Challenge Task %s/%s",
                            elapsed_time,
                            self.challenge.task_meta.task_id,
                            self.challenge.name,
                        )
                        self._save_custom_test_instructions(agent_state.tests_instructions)

                        return Command(
                            update={
                                "tests_instructions": agent_state.tests_instructions,
                            },
                            goto=PatcherAgentName.ROOT_CAUSE_ANALYSIS.value,
                        )
                    elapsed_time = time.time() - start_time
                    logger.warning(
                        "Failed to find test instructions after %.2f seconds for Challenge Task %s/%s",
                        elapsed_time,
                        self.challenge.task_meta.task_id,
                        self.challenge.name,
                    )
                    return Command(
                        goto=PatcherAgentName.ROOT_CAUSE_ANALYSIS.value,
                    )

            except TimeoutError:
                elapsed_time = time.time() - start_time
                logger.warning(
                    "Timeout after %.2f seconds (30 minutes) while finding tests for Challenge Task %s/%s",
                    elapsed_time,
                    self.challenge.task_meta.task_id,
                    self.challenge.name,
                )
                return Command(
                    goto=PatcherAgentName.ROOT_CAUSE_ANALYSIS.value,
                )
            except Exception as e:
                elapsed_time = time.time() - start_time
                logger.exception(
                    "Unexpected error after %.2f seconds while finding tests for Challenge Task %s/%s: %s",
                    elapsed_time,
                    self.challenge.task_meta.task_id,
                    self.challenge.name,
                    e,
                )
                return Command(
                    goto=PatcherAgentName.ROOT_CAUSE_ANALYSIS.value,
                )
