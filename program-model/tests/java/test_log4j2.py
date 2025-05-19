"""CodeQuery primitives testing"""

import pytest

from buttercup.common.challenge_task import ChallengeTask
from ..common import (
    common_test_get_functions,
    common_test_get_callers,
    common_test_get_callees,
    common_test_get_type_definitions,
    common_test_get_type_usages,
    TestFunctionInfo,
    TestTypeDefinitionInfo,
    TestTypeUsageInfo,
    TypeDefinitionType,
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
def test_get_functions(
    log4j2_oss_fuzz_task: ChallengeTask, function_name, file_path, function_info
):
    """Test that we can get functions in challenge task code"""
    common_test_get_functions(
        log4j2_oss_fuzz_task, function_name, file_path, function_info
    )


@pytest.mark.parametrize(
    "function_name,file_path,line_number,fuzzy,expected_callers,num_callers",
    [
        # TODO(Evan): Re-enable this test after fixing cscope issue which doesn't think getLogger is a function.
        #   (
        #       "getLogger",
        #       "/src/log4j-core/src/main/java/org/apache/logging/log4j/core/LoggerContext.java",
        #       565,
        #       False,
        #       [],
        #       453,
        #   ),
        (
            "getLogger",
            "/src/log4j-api/src/main/java/org/apache/logging/log4j/LogManager.java",
            597,
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
        # TODO(Evan): Re-enable these two tests after fixing cscope issue which doesn't think getLogger is a function.
        #   (
        #       "getLogger",
        #       "/src/log4j-core/src/main/java/org/apache/logging/log4j/core/LoggerContext.java",
        #       565,
        #       False,
        #       [],
        #       6,
        #   ),
        #   (
        #       "getLogger",
        #       "/src/log4j-1.2-api/src/main/java/org/apache/log4j/bridge/LogEventAdapter.java",
        #       126,
        #       False,
        #       [],
        #       21,
        #   ),
        (
            "getLogger",
            "/src/log4j-api/src/main/java/org/apache/logging/log4j/LogManager.java",
            597,
            False,
            [],
            3,
        ),
    ],
)
@pytest.mark.integration
def test_get_callees(
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


@pytest.mark.parametrize(
    "type_name,file_path,fuzzy,type_definition_info",
    [
        (
            "LoggerContext",
            None,
            False,
            TestTypeDefinitionInfo(
                name="LoggerContext",
                type=TypeDefinitionType.CLASS,
                definition="public class LoggerContext extends AbstractLifeCycle",
                definition_line=71,
                file_path="/src/log4j-core/src/main/java/org/apache/logging/log4j/core/LoggerContext.java",
            ),
        ),
    ],
)
@pytest.mark.integration
def test_get_type_definitions(
    log4j2_oss_fuzz_task: ChallengeTask,
    type_name,
    file_path,
    fuzzy,
    type_definition_info,
):
    """Test that we can get type defs"""
    common_test_get_type_definitions(
        log4j2_oss_fuzz_task,
        type_name,
        file_path,
        fuzzy,
        type_definition_info,
    )


@pytest.mark.parametrize(
    "type_name,file_path,fuzzy,type_usage_infos,num_type_usages",
    [
        (
            "LoggerContext",
            None,
            False,
            [
                TestTypeUsageInfo(
                    file_path="/src/log4j-core/src/main/java/org/apache/logging/log4j/core/osgi/BundleContextSelector.java",
                    line_number=146,
                ),
            ],
            12,
        ),
    ],
)
@pytest.mark.integration
def test_get_type_usages(
    log4j2_oss_fuzz_task: ChallengeTask,
    type_name,
    file_path,
    fuzzy,
    type_usage_infos,
    num_type_usages,
):
    """Test that we can get type usages"""
    common_test_get_type_usages(
        log4j2_oss_fuzz_task,
        type_name,
        file_path,
        fuzzy,
        type_usage_infos,
        num_type_usages,
    )
