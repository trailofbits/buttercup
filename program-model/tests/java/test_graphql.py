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
            "simplePrint",
            "/src/graphql-java/src/main/java/graphql/schema/GraphQLTypeUtil.java",
            TestFunctionInfo(
                num_bodies=2,
                body_excerpts=[
                    """return "[" + simplePrint(unwrapOne(type)) + "]";""",
                    """return ((GraphQLNamedSchemaElement) schemaElement).getName();""",
                ],
            ),
        ),
    ],
)
@pytest.mark.integration
def test_graphql_get_functions(
    graphql_oss_fuzz_task: ChallengeTask, function_name, file_path, function_info
):
    """Test that we can get functions in challenge task code"""
    common_test_get_functions(
        graphql_oss_fuzz_task, function_name, file_path, function_info
    )


@pytest.mark.parametrize(
    "function_name,file_path,line_number,fuzzy,expected_callers,num_callers",
    [
        (
            "simplePrint",
            "/src/graphql-java/src/main/java/graphql/schema/GraphQLTypeUtil.java",
            28,
            False,
            [],
            None,  # FIXME(Evan): Too many to verify. Need to add a test for this.
        ),
    ],
)
@pytest.mark.integration
def test_get_callers(
    graphql_oss_fuzz_task: ChallengeTask,
    function_name,
    file_path,
    line_number,
    fuzzy,
    expected_callers,
    num_callers,
):
    """Test that we can get function callers"""
    common_test_get_callers(
        graphql_oss_fuzz_task,
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
            "simplePrint",
            "/src/graphql-java/src/main/java/graphql/schema/GraphQLTypeUtil.java",
            28,
            False,
            [],
            None,  # FIXME(Evan): Too many to verify. Need to add a test for this.
        ),
    ],
)
@pytest.mark.integration
def test_graphql_get_callees(
    graphql_oss_fuzz_task: ChallengeTask,
    function_name,
    file_path,
    line_number,
    fuzzy,
    expected_callees,
    num_callees,
):
    """Test that we can get function callees."""
    common_test_get_callees(
        graphql_oss_fuzz_task,
        function_name,
        file_path,
        line_number,
        fuzzy,
        expected_callees,
        num_callees,
    )
