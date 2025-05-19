from pathlib import Path
from dataclasses import dataclass
from buttercup.common.challenge_task import ChallengeTask
from buttercup.program_model.codequery import CodeQuery
import pytest
from buttercup.program_model.utils.common import (
    TypeDefinitionType,
    TypeDefinition,
    Function,
    TypeUsageInfo,
)


def filter_project_context(
    focus,
    results: list[Function | TypeDefinition | TypeUsageInfo],
    language: str,
):
    """Some challenge tasks result in multiple instances of the target project to
    be built in the /src/ directory. This in turn causes Codequery to return multiple
    matches for queried context because it gets matches from parallel instances of the
    project.

    This function filters out found functions and types using the target project name.
    It removes all matches that don't directly come from the target project. To identify these,
    it checks whether matches belong to a file that as the proper project_name in their path."""
    if language == "c":
        return [x for x in results if f"/{focus}/" in str(x.file_path)]
    else:
        return results


@dataclass(frozen=True)
class TestFunctionInfo:
    num_bodies: int
    body_excerpts: list[str]


# Prevent pytest from collecting this as a test
TestFunctionInfo.__test__ = False


def common_test_get_functions(
    fuzz_task: ChallengeTask, function_name, file_path, function_info
):
    """Generic function for testing get_functions() in C codebases"""
    codequery = CodeQuery(fuzz_task)
    if file_path:
        file_path = Path(file_path)
    functions = codequery.get_functions(function_name, file_path=file_path)
    assert len(functions) == 1
    assert functions[0].name == function_name
    if file_path:
        assert Path(functions[0].file_path) == file_path
    assert len(functions[0].bodies) == function_info.num_bodies
    for body in function_info.body_excerpts:
        assert any([body in x.body for x in functions[0].bodies])


@dataclass(frozen=True)
class TestCallerInfo:
    name: str
    file_path: Path
    start_line: int


# Prevent pytest from collecting this as a test
TestCallerInfo.__test__ = False


def common_test_get_callers(
    fuzz_task: ChallengeTask,
    function_name,
    file_path,
    line_number,
    fuzzy,
    expected_callers,
    num_callers: int | None = None,
):
    """Test that we can get function callers"""
    codequery = CodeQuery(fuzz_task)
    function = codequery.get_functions(
        function_name=function_name,
        file_path=Path(file_path),
        line_number=line_number,
        fuzzy=fuzzy,
    )[0]

    callers = codequery.get_callers(function)
    callers = filter_project_context(
        fuzz_task.task_meta.focus, callers, codequery._get_project_language()
    )

    # Validate each caller
    for expected_caller in expected_callers:
        caller_info = [
            c
            for c in callers
            if c.name == expected_caller.name
            and c.file_path == Path(expected_caller.file_path)
            and any(
                True
                for b in c.bodies
                if b.start_line <= expected_caller.start_line <= b.end_line
            )
        ]
        if len(caller_info) == 0:
            pytest.fail(f"Couldn't find expected caller: {expected_caller}")
        elif len(caller_info) > 1:
            pytest.fail(f"Found multiple identical callers for: {expected_caller}")

    # Make sure we get the right number of callers
    if num_callers and len(callers) != num_callers:
        pytest.fail(f"Expected {num_callers} callers, got {len(callers)}")


@dataclass(frozen=True)
class TestCalleeInfo:
    name: str
    file_path: Path
    start_line: int


# Prevent pytest from collecting this as a test
TestCalleeInfo.__test__ = False


# NOTE(boyan): this is similar to the common_test_get_callers
# but we don't factorize the code so far in case we need to
# make the tests diverge in the future
def common_test_get_callees(
    fuzz_task: ChallengeTask,
    function_name,
    file_path,
    line_number,
    fuzzy,
    expected_callees,
    num_callees: int | None = None,
):
    """Test that we can get function callees."""
    codequery = CodeQuery(fuzz_task)
    function = codequery.get_functions(
        function_name=function_name,
        file_path=Path(file_path),
        line_number=line_number,
        fuzzy=fuzzy,
    )[0]

    callees = codequery.get_callees(function)
    callees = filter_project_context(
        fuzz_task.task_meta.focus, callees, codequery._get_project_language()
    )

    # Validate each callee
    for expected_callee in expected_callees:
        callee_info = [
            c
            for c in callees
            if c.name == expected_callee.name
            and c.file_path == Path(expected_callee.file_path)
            and any(
                True
                for b in c.bodies
                if b.start_line <= expected_callee.start_line <= b.end_line
            )
        ]
        if len(callee_info) == 0:
            pytest.fail(f"Couldn't find expected callee: {expected_callee}")
        elif len(callee_info) > 1:
            pytest.fail(f"Found multiple identical callees for: {expected_callee}")

    # Make sure we don't get more callees than expected
    if num_callees and len(callees) != num_callees:
        pytest.fail(f"Expected {num_callees} callees, got {len(callees)}")


@dataclass(frozen=True)
class TestTypeDefinitionInfo:
    name: str
    type: TypeDefinitionType
    definition: str
    definition_line: int
    file_path: str


# Prevent pytest from collecting this as a test
TestTypeDefinitionInfo.__test__ = False


def common_test_get_type_definitions(
    fuzz_task: ChallengeTask,
    type_name,
    file_path,
    fuzzy,
    type_definition_info,
):
    """Test that we can get type defs"""
    codequery = CodeQuery(fuzz_task)
    type_definitions = codequery.get_types(
        type_name=type_name,
        file_path=Path(file_path) if file_path else None,
        fuzzy=fuzzy,
    )
    type_definitions = filter_project_context(
        fuzz_task.task_meta.focus, type_definitions, codequery._get_project_language()
    )
    found = [
        c
        for c in type_definitions
        if c.name == type_name
        and c.type == type_definition_info.type
        and type_definition_info.definition in c.definition
        and c.definition_line == type_definition_info.definition_line
        and c.file_path == Path(type_definition_info.file_path)
    ]
    if len(found) == 0:
        pytest.fail(f"Couldn't find expected type definition: {type_definition_info}")
    elif len(found) > 1:
        pytest.fail(
            f"Found multiple identical type definitions for: {type_definition_info}"
        )


@dataclass(frozen=True)
class TestTypeUsageInfo:
    file_path: Path
    line_number: int


# Prevent pytest from collecting this as a test
TestTypeUsageInfo.__test__ = False


def common_test_get_type_usages(
    fuzz_task: ChallengeTask,
    type_name,
    file_path,
    fuzzy,
    type_usage_infos,
    num_type_usages: int | None = None,
):
    """Test that we can get type usages"""
    codequery = CodeQuery(fuzz_task)
    type_definition = codequery.get_types(
        type_name=type_name,
        file_path=Path(file_path) if file_path else None,
        fuzzy=fuzzy,
    )[0]
    call_sites = codequery.get_type_calls(type_definition)
    call_sites = filter_project_context(
        fuzz_task.task_meta.focus, call_sites, codequery._get_project_language()
    )
    if num_type_usages and len(call_sites) != num_type_usages:
        pytest.fail(f"Expected {num_type_usages} type usages, got {len(call_sites)}")

    for type_usage_info in type_usage_infos:
        type_usage = [
            c
            for c in call_sites
            if c.name == type_name
            and c.file_path == Path(type_usage_info.file_path)
            and c.line_number == type_usage_info.line_number
        ]
        if len(type_usage) == 0:
            pytest.fail(f"Couldn't find expected type usage: {type_usage_info}")
        elif len(type_usage) > 1:
            pytest.fail(f"Found multiple identical type usages for: {type_usage_info}")
