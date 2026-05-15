"""CodeQuery primitives testing"""

import pytest
from buttercup.common.challenge_task import ChallengeTask

from buttercup.program_model.codequery import CodeQuery

from ..common import (
    TestFunctionInfo,
    TestTypeDefinitionInfo,
    TestTypeUsageInfo,
    TypeDefinitionType,
    common_test_get_callees,
    common_test_get_callers,
    common_test_get_functions,
    common_test_get_type_definitions,
    common_test_get_type_usages,
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
def test_get_functions(
    graphql_oss_fuzz_task: ChallengeTask,
    graphql_oss_fuzz_cq: CodeQuery,
    function_name,
    file_path,
    function_info,
):
    """Test that we can get functions in challenge task code"""
    common_test_get_functions(graphql_oss_fuzz_cq, function_name, file_path, function_info)


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
    graphql_oss_fuzz_cq: CodeQuery,
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
        graphql_oss_fuzz_cq,
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
def test_get_callees(
    graphql_oss_fuzz_task: ChallengeTask,
    graphql_oss_fuzz_cq: CodeQuery,
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
        graphql_oss_fuzz_cq,
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
            "GraphQLTypeUtil",
            None,
            False,
            TestTypeDefinitionInfo(
                name="GraphQLTypeUtil",
                type=TypeDefinitionType.CLASS,
                definition="public class GraphQLTypeUtil {",
                definition_line=18,  # FIXME(Evan): This is wrong. It should be 19. 18 only has @PublicApi.
                file_path="/src/graphql-java/src/main/java/graphql/schema/GraphQLTypeUtil.java",
            ),
        ),
    ],
)
@pytest.mark.integration
def test_get_type_definitions(
    graphql_oss_fuzz_task: ChallengeTask,
    graphql_oss_fuzz_cq: CodeQuery,
    type_name,
    file_path,
    fuzzy,
    type_definition_info,
):
    """Test that we can get type defs"""
    common_test_get_type_definitions(
        graphql_oss_fuzz_task,
        graphql_oss_fuzz_cq,
        type_name,
        file_path,
        fuzzy,
        type_definition_info,
    )


@pytest.mark.parametrize(
    "type_name,file_path,fuzzy,type_usage_infos,num_type_usages",
    [
        (
            "GraphQLTypeUtil",
            None,
            False,
            [
                TestTypeUsageInfo(
                    file_path="/src/graphql-java/src/main/java/graphql/schema/GraphQLTypeUtil.java",
                    line_number=28,
                ),
            ],
            6,
        ),
    ],
)
@pytest.mark.skip(reason="Skipping type usage test for now. Issues with codequery.")
@pytest.mark.integration
def test_get_type_usages(
    graphql_oss_fuzz_task: ChallengeTask,
    graphql_oss_fuzz_cq: CodeQuery,
    type_name,
    file_path,
    fuzzy,
    type_usage_infos,
    num_type_usages,
):
    """Test that we can get type usages"""
    common_test_get_type_usages(
        graphql_oss_fuzz_task,
        graphql_oss_fuzz_cq,
        type_name,
        file_path,
        fuzzy,
        type_usage_infos,
        num_type_usages,
    )
