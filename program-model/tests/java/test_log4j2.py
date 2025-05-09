"""CodeQuery primitives testing"""

import pytest

from buttercup.common.challenge_task import ChallengeTask
from ..common import (
    common_test_get_functions,
    common_test_get_callers,
    common_test_get_callees,
    TestFunctionInfo,
)


@pytest.mark.parametrize(
    "function_name,file_path,function_info",
    [
        (
            "getLogger",
            "/src/log4j-core/src/main/java/org/apache/logging/log4j/core/LoggerContext.java",
            TestFunctionInfo(
                num_bodies=2,
                body_excerpts=[
                    """return getLogger(name, DEFAULT_MESSAGE_FACTORY);""",
                    """return loggerRegistry.computeIfAbsent(name, effectiveMessageFactory, this::newInstance);""",
                ],
            ),
        ),
    ],
)
@pytest.mark.integration
def test_log4j2_get_functions(
    log4j2_oss_fuzz_task: ChallengeTask, function_name, file_path, function_info
):
    """Test that we can get functions in challenge task code"""
    common_test_get_functions(
        log4j2_oss_fuzz_task, function_name, file_path, function_info
    )


@pytest.mark.parametrize(
    "function_name,file_path,line_number,fuzzy,expected_callers,num_callers",
    [
        (
            "getLogger",
            "/src/log4j-core/src/main/java/org/apache/logging/log4j/core/LoggerContext.java",
            565,
            False,
            [],
            453,
        ),
    ],
)
@pytest.mark.integration
def test_get_callers(
    log4j2_oss_fuzz_task: ChallengeTask,
    function_name,
    file_path,
    line_number,
    fuzzy,
    expected_callers,
    num_callers,
):
    """Test that we can get function callers"""
    common_test_get_callers(
        log4j2_oss_fuzz_task,
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
            "getLogger",
            "/src/log4j-core/src/main/java/org/apache/logging/log4j/core/LoggerContext.java",
            565,
            False,
            [],
            6,
        ),
        (
            "getLogger",
            "/src/log4j-1.2-api/src/main/java/org/apache/log4j/bridge/LogEventAdapter.java",
            126,
            False,
            [],
            21,
        ),
    ],
)
@pytest.mark.integration
def test_log4j2_get_callees(
    log4j2_oss_fuzz_task: ChallengeTask,
    function_name,
    file_path,
    line_number,
    fuzzy,
    expected_callees,
    num_callees,
):
    """Test that we can get function callees."""
    common_test_get_callees(
        log4j2_oss_fuzz_task,
        function_name,
        file_path,
        line_number,
        fuzzy,
        expected_callees,
        num_callees,
    )
