"""CodeQuery primitives testing"""

import pytest

from buttercup.common.challenge_task import ChallengeTask
from ..conftest import oss_fuzz_task
from ..common import (
    common_test_get_functions,
    common_test_get_callers,
    common_test_get_callees,
    TestFunctionInfo,
)


@pytest.fixture(scope="module")
def log4j2_oss_fuzz_task(tmp_path_factory: pytest.TempPathFactory):
    return oss_fuzz_task(
        tmp_path_factory.mktemp("task_dir"),
        "log4j2",
        "logging-log4j2",
        "https://github.com/apache/logging-log4j2",
        "1b544d38c9238a0039a99e296fe93da43b8f7ace",
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
@pytest.mark.skip("Doesn't find getLogger() in LoggerContext.java")
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
            490,
        ),
    ],
)
@pytest.mark.skip("Doesn't find getLogger() in LoggerContext.java")
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
        # (
        #     "getLogger",
        #     "/src/log4j-core/src/main/java/org/apache/logging/log4j/core/LoggerContext.java",
        #     565,
        #     False,
        #     [],
        #     13,
        # ),
        (
            "getLogger",
            "/src/log4j-1.2-api/src/main/java/org/apache/log4j/bridge/LogEventAdapter.java",
            126,
            False,
            [],
            21,
        )
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
