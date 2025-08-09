"""Tools for the patcher agents."""

from __future__ import annotations

import logging
from buttercup.common.challenge_task import CommandResult, ChallengeTask
from buttercup.program_model.codequery import CodeQueryPersistent
from buttercup.program_model.utils.common import Function, TypeDefinition
from typing import Annotated
from pathlib import Path
from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState
from buttercup.patcher.utils import truncate_output, get_challenge, get_codequery, find_file_in_source_dir
from buttercup.patcher.agents.common import BaseCtxState, ContextCodeSnippet, CodeSnippetKey

logger = logging.getLogger(__name__)

MAX_OUTPUT_LENGTH = 10000


def _wrap_command_output(command: str | list[str], cmd_res: CommandResult, output: str | None = None) -> str:
    if output is None:
        output = cmd_res.output.decode("utf-8")

    if isinstance(command, list):
        command = " ".join(command)

    return f"""<command_output>
<command>{command}</command>
<returncode>{cmd_res.returncode}</returncode>
<stdout>
{truncate_output(output, MAX_OUTPUT_LENGTH)}
</stdout>
<stderr>
{truncate_output(cmd_res.error, MAX_OUTPUT_LENGTH)}
</stderr>
</command_output>"""


@tool
def ls(
    file_path: str,
    *,
    state: Annotated[BaseCtxState, InjectedState],
) -> str:
    """List the files in the given file_path in the project's source directory."""
    path = Path(file_path)
    logger.info("Listing files in %s", path)
    args = ["ls", "-la"]
    if path:
        args.append(str(path))
    challenge = get_challenge(state.challenge_task_dir)
    ls_cmd_res = challenge.exec_docker_cmd(args)
    return _wrap_command_output(args, ls_cmd_res)


@tool
def grep(
    pattern: str,
    file_path: str | None,
    state: Annotated[BaseCtxState, InjectedState],
) -> str:
    """Grep for a string and return a 5-line context around the match, together \
    with line numbers. If no file_path is provided, search the entire project. \
    Prefer using this tool over cat. If you need to search several files, just \
    call call this tool without any file_path."""
    path = Path(file_path) if file_path else None
    logger.info("Searching for %s in %s", pattern, path)
    args = ["grep", "-C", "5", "-nHrE", pattern]
    if path:
        args.append(str(path))
    challenge = get_challenge(state.challenge_task_dir)
    grep_cmd_res = challenge.exec_docker_cmd(args)
    return _wrap_command_output(args, grep_cmd_res)


@tool
def cat(file_path: str, state: Annotated[BaseCtxState, InjectedState]) -> str:
    """Read the contents of a file. Use this tool only if grep and get_lines do not work as it might return a large amount of text."""
    path = Path(file_path)
    logger.info("Reading contents of %s", path)
    challenge = get_challenge(state.challenge_task_dir)
    args = ["cat", str(path)]
    cat_cmd_res = challenge.exec_docker_cmd(args)
    return _wrap_command_output(args, cat_cmd_res)


@tool
def get_lines(
    file_path: str,
    start: int,
    end: int,
    state: Annotated[BaseCtxState, InjectedState],
) -> str:
    """Get a range of lines from a file. Prefer using this tool over cat."""
    path = Path(file_path)
    logger.info("Getting lines %d-%d of %s", start, end, path)
    challenge = get_challenge(state.challenge_task_dir)
    get_lines_res_cmd = challenge.exec_docker_cmd(["cat", str(path)])
    get_lines_output = get_lines_res_cmd.output.decode("utf-8").splitlines()[start:end]
    return _wrap_command_output(f"get_lines {path} {start} {end}", get_lines_res_cmd, "\n".join(get_lines_output))


def _get_codequery_function(codequery: CodeQueryPersistent, name: str, path: Path | None) -> Function:
    functions = codequery.get_functions(name, path)
    if not functions:
        raise ValueError(f"No definition found for function {name} in {path}")

    return functions[0]


def _add_functions_code_snippets(
    challenge: ChallengeTask, functions: list[Function], suffix: str = ""
) -> list[ContextCodeSnippet]:
    return [
        ContextCodeSnippet(
            key=CodeSnippetKey(
                file_path=function.file_path.as_posix(),
            ),
            start_line=body.start_line,
            end_line=body.end_line,
            code=body.body,
            description=f"Implementation of function {function.name}{suffix} in {function.file_path.as_posix()}",
            can_patch=find_file_in_source_dir(challenge, function.file_path) is not None,
        )
        for function in functions
        for body in function.bodies
    ]


def _add_type_definitions_code_snippets(
    challenge: ChallengeTask, type_definitions: list[TypeDefinition]
) -> list[ContextCodeSnippet]:
    return [
        ContextCodeSnippet(
            key=CodeSnippetKey(
                file_path=type_def.file_path.as_posix(),
            ),
            code=type_def.definition,
            start_line=type_def.definition_line,
            end_line=type_def.definition_line + len(type_def.definition.splitlines()),
            description=f"Definition of type {type_def.name}",
            can_patch=find_file_in_source_dir(challenge, type_def.file_path) is not None,
        )
        for type_def in type_definitions
    ]


def _clean_function_name(function_name: str) -> str:
    if function_name.startswith("OSS_FUZZ_"):
        return function_name[len("OSS_FUZZ_") :]
    return function_name


def get_function_tool_impl(function_name: str, file_path: str | None, state: BaseCtxState) -> list[ContextCodeSnippet]:
    path = Path(file_path) if file_path else None
    challenge = get_challenge(state.challenge_task_dir)
    if path and not path.is_absolute():
        # If the path is not absolute, it is relative to the container workdir
        path = challenge.workdir_from_dockerfile().joinpath(path)

    logger.info("Getting function definition of %s in %s", function_name, path)
    function_name = _clean_function_name(function_name)
    codequery = get_codequery(state.challenge_task_dir, state.work_dir)
    functions = codequery.get_functions(function_name, path)
    if not functions:
        functions = codequery.get_functions(function_name, None)
        if not functions:
            functions = codequery.get_functions(function_name, None, fuzzy=True)
            if not functions:
                raise ValueError(f"No definition found for function {function_name} in {path}")

    return _add_functions_code_snippets(challenge, functions)


@tool
def get_function(function_name: str, file_path: str | None, *, state: Annotated[BaseCtxState, InjectedState]) -> str:
    """Get a function's definition. If available, pass a file_path, \
    otherwise pass None. Use this when you want to get information about a \
    function. If not sure about the file path, pass None. Prefer using this \
    tool over any other and rely on others only if this tool fails or does \
    not work."""
    code_snippets = get_function_tool_impl(function_name, file_path, state)
    output_str = "\n".join(str(code_snippet) for code_snippet in code_snippets)
    return output_str


@tool
def get_callers(function_name: str, file_path: str | None, *, state: Annotated[BaseCtxState, InjectedState]) -> str:
    """Get the callers of a function."""
    path = Path(file_path) if file_path else None
    logger.info("Getting callers of %s in %s", function_name, path)
    codequery = get_codequery(state.challenge_task_dir, state.work_dir)
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
def get_callees(function_name: str, file_path: str | None, *, state: Annotated[BaseCtxState, InjectedState]) -> str:
    """Get the callees of a function."""
    path = Path(file_path) if file_path else None
    logger.info("Getting callees of %s in %s", function_name, path)
    codequery = get_codequery(state.challenge_task_dir, state.work_dir)
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


def get_type_tool_impl(type_name: str, file_path: str | None, state: BaseCtxState) -> list[ContextCodeSnippet]:
    path = Path(file_path) if file_path else None

    logger.info("Getting type definition of %s in %s", type_name, path)
    challenge = get_challenge(state.challenge_task_dir)
    codequery = get_codequery(state.challenge_task_dir, state.work_dir)
    types = codequery.get_types(type_name, path)
    if not types:
        types = codequery.get_types(type_name, None)
        if not types:
            types = codequery.get_types(type_name, None, fuzzy=True)
            if not types:
                raise ValueError(f"No definition found for type {type_name} in {path}")

    return _add_type_definitions_code_snippets(challenge, types)


@tool
def get_type(type_name: str, file_path: str | None, *, state: Annotated[BaseCtxState, InjectedState]) -> str:
    """Get a type/class/typedef/struct/enum/macro's definition. If available, pass a file_path, \
    otherwise pass None. Use this when you want to get information about a type. \
    If not sure about the file path, pass None. Prefer using this tool over any \
    other and rely on others only if this tool fails or does not work."""
    code_snippets = get_type_tool_impl(type_name, file_path, state)
    output_str = "\n".join(str(code_snippet) for code_snippet in code_snippets)
    return output_str
