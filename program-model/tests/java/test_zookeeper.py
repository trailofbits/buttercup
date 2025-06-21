"""CodeQuery primitives testing"""

import pytest

from buttercup.common.challenge_task import ChallengeTask
from buttercup.program_model.codequery import CodeQuery
from buttercup.program_model.utils.common import TypeDefinitionType
from ..common import (
    common_test_get_type_definitions,
    common_test_get_functions,
    common_test_get_callers,
    common_test_get_callees,
    common_test_get_type_usages,
    TestCallerInfo,
    TestFunctionInfo,
    TestCalleeInfo,
    TestTypeDefinitionInfo,
    TestTypeUsageInfo,
)


@pytest.mark.parametrize(
    "function_name,file_path,function_info",
    [
        (
            "logMessages",
            "/src/zookeeper/zookeeper-server/src/main/java/org/apache/zookeeper/server/util/MessageTracker.java",
            TestFunctionInfo(
                num_bodies=1,
                body_excerpts=[
                    """String sentOrReceivedText = direction == Direction.SENT ? "sentBuffer to" : "receivedBuffer from";""",
                ],
            ),
        ),
        (
            "peekReceived",
            "/src/zookeeper/zookeeper-server/src/main/java/org/apache/zookeeper/server/util/MessageTracker.java",
            TestFunctionInfo(
                num_bodies=1,
                body_excerpts=["""return receivedBuffer.peek();"""],
            ),
        ),
    ],
)
@pytest.mark.integration
def test_get_functions(
    zookeeper_oss_fuzz_task: ChallengeTask,
    zookeeper_oss_fuzz_cq: CodeQuery,
    function_name,
    file_path,
    function_info,
):
    """Test that we can get functions in challenge task code"""
    common_test_get_functions(
        zookeeper_oss_fuzz_cq, function_name, file_path, function_info
    )


@pytest.mark.parametrize(
    "function_name,file_path,line_number,fuzzy,expected_callers,num_callers",
    [
        (
            "logMessages",
            "/src/zookeeper/zookeeper-server/src/main/java/org/apache/zookeeper/server/util/MessageTracker.java",
            None,
            False,
            [
                TestCallerInfo(
                    name="dumpToLog",
                    file_path="/src/zookeeper/zookeeper-server/src/main/java/org/apache/zookeeper/server/util/MessageTracker.java",
                    start_line=95,
                )
            ],
            1,
        ),
    ],
)
@pytest.mark.integration
def test_get_callers(
    zookeeper_oss_fuzz_task: ChallengeTask,
    zookeeper_oss_fuzz_cq: CodeQuery,
    function_name,
    file_path,
    line_number,
    fuzzy,
    expected_callers,
    num_callers,
):
    """Test that we can get function callers"""
    common_test_get_callers(
        zookeeper_oss_fuzz_task,
        zookeeper_oss_fuzz_cq,
        function_name,
        file_path,
        line_number,
        fuzzy,
        expected_callers,
        num_callers,
    )


@pytest.mark.parametrize(
    "function_name,file_path,line_number,fuzzy,expected_callees,num_callees",
    [
        (
            "dumpToLog",
            "/src/zookeeper/zookeeper-server/src/main/java/org/apache/zookeeper/server/util/MessageTracker.java",
            95,
            False,
            [
                TestCalleeInfo(
                    name="logMessages",
                    file_path="/src/zookeeper/zookeeper-server/src/main/java/org/apache/zookeeper/server/util/MessageTracker.java",
                    start_line=103,
                )
            ],
            1,
        ),
    ],
)
@pytest.mark.integration
def test_get_callees(
    zookeeper_oss_fuzz_task: ChallengeTask,
    zookeeper_oss_fuzz_cq: CodeQuery,
    function_name,
    file_path,
    line_number,
    fuzzy,
    expected_callees,
    num_callees,
):
    """Test that we can get function callees."""
    common_test_get_callees(
        zookeeper_oss_fuzz_task,
        zookeeper_oss_fuzz_cq,
        function_name,
        file_path,
        line_number,
        fuzzy,
        expected_callees,
        num_callees,
    )


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
                file_path="/src/zookeeper/zookeeper-server/src/main/java/org/apache/zookeeper/server/util/MessageTracker.java",
            ),
        ),
    ],
)
@pytest.mark.integration
def test_get_type_definitions(
    zookeeper_oss_fuzz_task: ChallengeTask,
    zookeeper_oss_fuzz_cq: CodeQuery,
    type_name,
    file_path,
    fuzzy,
    type_definition_info,
):
    """Test that we can get type defs"""
    common_test_get_type_definitions(
        zookeeper_oss_fuzz_task,
        zookeeper_oss_fuzz_cq,
        type_name,
        file_path,
        fuzzy,
        type_definition_info,
    )


@pytest.mark.parametrize(
    "type_name,file_path,fuzzy,type_usage_infos,num_type_usages",
    [
        (
            "MessageTracker",
            "/src/zookeeper/zookeeper-server/src/main/java/org/apache/zookeeper/server/util/MessageTracker.java",
            False,
            [
                TestTypeUsageInfo(
                    file_path="/src/zookeeper/zookeeper-server/src/main/java/org/apache/zookeeper/server/quorum/LearnerHandler.java",
                    line_number=300,
                ),
                TestTypeUsageInfo(
                    file_path="/src/zookeeper/zookeeper-server/src/test/java/org/apache/zookeeper/server/util/MessageTrackerTest.java",
                    line_number=46,
                ),
                TestTypeUsageInfo(
                    file_path="/src/zookeeper/zookeeper-server/src/test/java/org/apache/zookeeper/server/util/MessageTrackerTest.java",
                    line_number=63,
                ),
                TestTypeUsageInfo(
                    file_path="/src/zookeeper/zookeeper-server/src/test/java/org/apache/zookeeper/server/util/MessageTrackerTest.java",
                    line_number=79,
                ),
                TestTypeUsageInfo(
                    file_path="/src/zookeeper/zookeeper-server/src/test/java/org/apache/zookeeper/server/util/MessageTrackerTest.java",
                    line_number=105,
                ),
                # This one is not present in the source but created in the ossfuzz container source dir
                TestTypeUsageInfo(
                    file_path="/src/MessageTrackerPeekReceivedFuzzer.java",
                    line_number=30,
                ),
            ],
            17,
        ),
    ],
)
@pytest.mark.integration
def test_get_type_usages(
    zookeeper_oss_fuzz_task: ChallengeTask,
    zookeeper_oss_fuzz_cq: CodeQuery,
    type_name,
    file_path,
    fuzzy,
    type_usage_infos,
    num_type_usages,
):
    """Test that we can get type usages"""
    common_test_get_type_usages(
        zookeeper_oss_fuzz_task,
        zookeeper_oss_fuzz_cq,
        type_name,
        file_path,
        fuzzy,
        type_usage_infos,
        num_type_usages,
    )
