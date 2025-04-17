"""CodeQuery primitives testing"""

import pytest
from pathlib import Path
from dataclasses import dataclass

from buttercup.common.challenge_task import ChallengeTask
from buttercup.program_model.codequery import CodeQuery
from buttercup.program_model.utils.common import TypeDefinitionType
from ..conftest import oss_fuzz_task

import logging

logger = logging.getLogger(__name__)


@pytest.fixture(scope="module")
def zookeeper_oss_fuzz_task(tmp_path_factory: pytest.TempPathFactory):
    return oss_fuzz_task(
        tmp_path_factory.mktemp("task_dir"),
        "zookeeper",
        "zookeeper",
        "https://github.com/apache/zookeeper",
        "b86ccf19cf6c32f7e58e36754b6f3534be567727",
    )


@dataclass(frozen=True)
class TestFunctionInfo:
    num_bodies: int
    body_excerpts: list[str]


# Prevent pytest from collecting this as a test
TestFunctionInfo.__test__ = False


@pytest.mark.parametrize(
    "function_name,file_path,line_number,fuzzy,function_info",
    [
        (
            "logMessages",
            None,
            None,
            False,
            TestFunctionInfo(
                num_bodies=1,
                body_excerpts=[
                    """String sentOrReceivedText = direction == Direction.SENT ? "sentBuffer to" : "receivedBuffer from";""",
                ],
            ),
        ),
        (
            "logMessages",
            Path(
                "/src/zookeeper/zookeeper-server/src/main/java/org/apache/zookeeper/server/util/MessageTracker.java"
            ),
            None,
            False,
            TestFunctionInfo(
                num_bodies=1,
                body_excerpts=[
                    """String sentOrReceivedText = direction == Direction.SENT ? "sentBuffer to" : "receivedBuffer from";""",
                ],
            ),
        ),
        (
            "logMessages",
            Path(
                "/src/zookeeper/zookeeper-server/src/main/java/org/apache/zookeeper/server/util/MessageTracker.java"
            ),
            103,
            False,
            TestFunctionInfo(
                num_bodies=1,
                body_excerpts=[
                    """String sentOrReceivedText = direction == Direction.SENT ? "sentBuffer to" : "receivedBuffer from";""",
                ],
            ),
        ),
        (
            "logMessages",
            Path(
                "/src/zookeeper/zookeeper-server/src/main/java/org/apache/zookeeper/server/util/MessageTracker.java"
            ),
            102,
            False,
            None,
        ),
        (
            "peekReceived",
            Path(
                "/src/zookeeper/zookeeper-server/src/main/java/org/apache/zookeeper/server/util/MessageTracker.java"
            ),
            None,
            False,
            TestFunctionInfo(
                num_bodies=1,
                body_excerpts=["""return receivedBuffer.peek();"""],
            ),
        ),
    ],
)
@pytest.mark.integration
def test_zookeeper_get_functions(
    zookeeper_oss_fuzz_task: ChallengeTask,
    function_name,
    file_path,
    line_number,
    fuzzy,
    function_info,
):
    """Test that we can get functions from zookeeper"""
    codequery = CodeQuery(zookeeper_oss_fuzz_task)
    functions = codequery.get_functions(
        function_name=function_name,
        file_path=file_path,
        line_number=line_number,
        fuzzy=fuzzy,
    )
    if function_info is None:
        assert len(functions) == 0
    else:
        assert len(functions) == 1
        assert functions[0].name == function_name
        assert len(functions[0].bodies) == function_info.num_bodies
        for body in function_info.body_excerpts:
            assert any([body in x.body for x in functions[0].bodies])
        if line_number is not None:
            assert functions[0].bodies[0].start_line == line_number


@dataclass(frozen=True)
class TestCallerInfo:
    name: str
    file_path: Path
    line_number: int


# Prevent pytest from collecting this as a test
TestCallerInfo.__test__ = False


@pytest.mark.parametrize(
    "function_name,file_path,line_number,fuzzy,function_info",
    [
        (
            "logMessages",
            Path(
                "/src/zookeeper/zookeeper-server/src/main/java/org/apache/zookeeper/server/util/MessageTracker.java"
            ),
            103,
            False,
            TestCallerInfo(
                name="dumpToLog",
                file_path=Path(
                    "/src/zookeeper/zookeeper-server/src/main/java/org/apache/zookeeper/server/util/MessageTracker.java"
                ),
                line_number=95,
            ),
        ),
    ],
)
@pytest.mark.integration
def test_zookeeper_get_callers(
    zookeeper_oss_fuzz_task: ChallengeTask,
    function_name,
    file_path,
    line_number,
    fuzzy,
    function_info,
):
    """Test that we can get function callers from zookeeper"""
    codequery = CodeQuery(zookeeper_oss_fuzz_task)
    function = codequery.get_functions(
        function_name=function_name,
        file_path=file_path,
        line_number=line_number,
        fuzzy=fuzzy,
    )[0]

    callers = codequery.get_callers(function)
    assert len(callers) == 1
    assert callers[0].name == function_info.name
    assert callers[0].file_path == function_info.file_path
    assert callers[0].bodies[0].start_line == function_info.line_number


@dataclass(frozen=True)
class TestCalleeInfo:
    name: str
    file_path: Path
    line_number: int


# Prevent pytest from collecting this as a test
TestCalleeInfo.__test__ = False


@pytest.mark.parametrize(
    "function_name,file_path,line_number,fuzzy,function_info",
    [
        (
            "dumpToLog",
            Path(
                "/src/zookeeper/zookeeper-server/src/main/java/org/apache/zookeeper/server/util/MessageTracker.java"
            ),
            95,
            False,
            TestCalleeInfo(
                name="logMessages",
                file_path=Path(
                    "/src/zookeeper/zookeeper-server/src/main/java/org/apache/zookeeper/server/util/MessageTracker.java"
                ),
                line_number=103,
            ),
        ),
    ],
)
@pytest.mark.integration
def test_zookeeper_get_callees(
    zookeeper_oss_fuzz_task: ChallengeTask,
    function_name,
    file_path,
    line_number,
    fuzzy,
    function_info,
):
    """Test that we can get function callees from zookeeper"""
    codequery = CodeQuery(zookeeper_oss_fuzz_task)
    function = codequery.get_functions(
        function_name=function_name,
        file_path=file_path,
        line_number=line_number,
        fuzzy=fuzzy,
    )[0]

    callees = codequery.get_callees(function)
    assert len(callees) == 1
    assert callees[0].name == function_info.name
    assert callees[0].file_path == function_info.file_path
    assert callees[0].bodies[0].start_line == function_info.line_number


@dataclass(frozen=True)
class TestTypeDefinitionInfo:
    name: str
    type: TypeDefinitionType
    definition: str
    definition_line: int


# Prevent pytest from collecting this as a test
TestTypeDefinitionInfo.__test__ = False


@pytest.mark.parametrize(
    "type_name,file_path,fuzzy,type_definition_info",
    [
        (
            "MessageTracker",
            None,
            False,
            TestTypeDefinitionInfo(
                name="MessageTracker",
                type=TypeDefinitionType.CLASS,
                definition="public class MessageTracker {",
                definition_line=34,
            ),
        ),
        (
            "MessageTracker",
            Path(
                "/src/zookeeper/zookeeper-server/src/main/java/org/apache/zookeeper/server/util/MessageTracker.java"
            ),
            False,
            TestTypeDefinitionInfo(
                name="MessageTracker",
                type=TypeDefinitionType.CLASS,
                definition="public class MessageTracker {",
                definition_line=34,
            ),
        ),
    ],
)
@pytest.mark.integration
def test_zookeeper_get_type_definitions(
    zookeeper_oss_fuzz_task: ChallengeTask,
    type_name,
    file_path,
    fuzzy,
    type_definition_info,
):
    """Test that we can get function callees from zookeeper"""
    codequery = CodeQuery(zookeeper_oss_fuzz_task)
    type_definitions = codequery.get_types(
        type_name=type_name,
        file_path=file_path,
        fuzzy=fuzzy,
    )

    assert len(type_definitions) == 1
    assert type_definitions[0].name == type_definition_info.name
    assert type_definitions[0].type == type_definition_info.type
    assert type_definition_info.definition in type_definitions[0].definition
    assert type_definitions[0].definition_line == type_definition_info.definition_line


@dataclass(frozen=True)
class TestTypeUsageInfo:
    file_path: Path
    line_number: int


# Prevent pytest from collecting this as a test
TestTypeUsageInfo.__test__ = False


@pytest.mark.parametrize(
    "type_name,file_path,fuzzy,type_usage_info",
    [
        (
            "MessageTracker",
            Path(
                "/src/zookeeper/zookeeper-server/src/main/java/org/apache/zookeeper/server/util/MessageTracker.java"
            ),
            False,
            [
                TestTypeUsageInfo(
                    file_path=Path("/src/MessageTrackerPeekReceivedFuzzer.java"),
                    line_number=29,
                ),
                TestTypeUsageInfo(
                    file_path=Path(
                        "/src/zookeeper/zookeeper-server/src/main/java/org/apache/zookeeper/server/quorum/LearnerHandler.java"
                    ),
                    line_number=300,
                ),
                TestTypeUsageInfo(
                    file_path=Path(
                        "/src/zookeeper/zookeeper-server/src/test/java/org/apache/zookeeper/server/util/MessageTrackerTest.java"
                    ),
                    line_number=46,
                ),
                TestTypeUsageInfo(
                    file_path=Path(
                        "/src/zookeeper/zookeeper-server/src/test/java/org/apache/zookeeper/server/util/MessageTrackerTest.java"
                    ),
                    line_number=63,
                ),
                TestTypeUsageInfo(
                    file_path=Path(
                        "/src/zookeeper/zookeeper-server/src/test/java/org/apache/zookeeper/server/util/MessageTrackerTest.java"
                    ),
                    line_number=79,
                ),
                TestTypeUsageInfo(
                    file_path=Path(
                        "/src/zookeeper/zookeeper-server/src/test/java/org/apache/zookeeper/server/util/MessageTrackerTest.java"
                    ),
                    line_number=105,
                ),
            ],
        ),
    ],
)
@pytest.mark.integration
def test_zookeeper_get_type_usages(
    zookeeper_oss_fuzz_task: ChallengeTask,
    type_name,
    file_path,
    fuzzy,
    type_usage_info,
):
    """Test that we can get function callees from zookeeper"""
    codequery = CodeQuery(zookeeper_oss_fuzz_task)
    type_definition = codequery.get_types(
        type_name=type_name,
        file_path=file_path,
        fuzzy=fuzzy,
    )[0]
    call_sites = codequery.get_type_calls(type_definition)
    assert len(call_sites) == len(type_usage_info)

    for found, correct in zip(call_sites, type_usage_info):
        file_path, line_number = found
        assert file_path == correct.file_path
        assert line_number == correct.line_number
