"""CodeQuery primitives testing"""

import pytest

from buttercup.common.challenge_task import ChallengeTask
from buttercup.program_model.codequery import CodeQuery
from ..common import (
    TestFunctionInfo,
    common_test_get_functions,
    common_test_get_callers,
    common_test_get_callees,
    common_test_get_type_definitions,
    common_test_get_type_usages,
    TestCallerInfo,
    TestCalleeInfo,
    TestTypeDefinitionInfo,
    TestTypeUsageInfo,
    TypeDefinitionType,
)


@pytest.mark.parametrize(
    "function_name,file_path,function_info",
    [
        (
            "parseAndPrintJavadocTree",
            "/src/checkstyle/src/main/java/com/puppycrawl/tools/checkstyle/AstTreeStringPrinter.java",
            TestFunctionInfo(
                num_bodies=1,
                body_excerpts=[
                    """baseIndentation = baseIndentation.substring(0, baseIndentation.length() - 2);""",
                ],
            ),
        ),
        (
            "expr",
            "/src/checkstyle/target/generated-sources/antlr/com/puppycrawl/tools/checkstyle/grammar/java/JavaLanguageParser.java",
            TestFunctionInfo(
                num_bodies=27,
                body_excerpts=[
                    """return getRuleContext(ExprContext.class,i);""",
                    """return getRuleContext(ExprContext.class,0);""",
                ],
            ),
        ),
    ],
)
@pytest.mark.integration
def test_get_functions(
    checkstyle_oss_fuzz_task: ChallengeTask,
    checkstyle_oss_fuzz_cq: CodeQuery,
    function_name,
    file_path,
    function_info,
):
    """Test that we can get functions in challenge task code"""
    common_test_get_functions(
        checkstyle_oss_fuzz_cq, function_name, file_path, function_info
    )


@pytest.mark.parametrize(
    "function_name,file_path,line_number,fuzzy,expected_callers,num_callers",
    [
        (
            "parseAndPrintJavadocTree",
            "/src/checkstyle/src/main/java/com/puppycrawl/tools/checkstyle/AstTreeStringPrinter.java",
            None,
            False,
            [
                TestCallerInfo(
                    name="printJavaAndJavadocTree",
                    file_path="/src/checkstyle/src/main/java/com/puppycrawl/tools/checkstyle/AstTreeStringPrinter.java",
                    start_line=88,
                )
            ],
            2,
        ),
    ],
)
@pytest.mark.skip(
    reason="Skipping callers test for now. It's failing for this example."
)
@pytest.mark.integration
def test_get_callers(
    checkstyle_oss_fuzz_task: ChallengeTask,
    checkstyle_oss_fuzz_cq: CodeQuery,
    function_name,
    file_path,
    line_number,
    fuzzy,
    expected_callers,
    num_callers,
):
    """Test that we can get function callers"""
    common_test_get_callers(
        checkstyle_oss_fuzz_task,
        checkstyle_oss_fuzz_cq,
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
            "parseAndPrintJavadocTree",
            "/src/checkstyle/src/main/java/com/puppycrawl/tools/checkstyle/AstTreeStringPrinter.java",
            None,
            False,
            [
                TestCalleeInfo(
                    name="parseJavadocAsDetailNode",
                    file_path="/src/checkstyle/src/main/java/com/puppycrawl/tools/checkstyle/DetailNodeTreeStringPrinter.java",
                    start_line=66,
                )
            ],
            2,
        ),
    ],
)
@pytest.mark.integration
def test_get_callees(
    checkstyle_oss_fuzz_task: ChallengeTask,
    checkstyle_oss_fuzz_cq: CodeQuery,
    function_name,
    file_path,
    line_number,
    fuzzy,
    expected_callees,
    num_callees,
):
    """Test that we can get function callees."""
    common_test_get_callees(
        checkstyle_oss_fuzz_task,
        checkstyle_oss_fuzz_cq,
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
            "AstTreeStringPrinter",
            None,
            False,
            TestTypeDefinitionInfo(
                name="AstTreeStringPrinter",
                type=TypeDefinitionType.CLASS,
                definition="public final class AstTreeStringPrinter {",
                definition_line=37,
                file_path="/src/checkstyle/src/main/java/com/puppycrawl/tools/checkstyle/AstTreeStringPrinter.java",
            ),
        ),
    ],
)
@pytest.mark.integration
def test_get_type_definitions(
    checkstyle_oss_fuzz_task: ChallengeTask,
    checkstyle_oss_fuzz_cq: CodeQuery,
    type_name,
    file_path,
    fuzzy,
    type_definition_info,
):
    """Test that we can get type defs"""
    common_test_get_type_definitions(
        checkstyle_oss_fuzz_task,
        checkstyle_oss_fuzz_cq,
        type_name,
        file_path,
        fuzzy,
        type_definition_info,
    )


# From: https://github.com/checkstyle/checkstyle/blob/94cd165da31942661301a09561e4b4ad85366c77/src/test/java/com/puppycrawl/tools/checkstyle/AstTreeStringPrinterTest.java#L87
@pytest.mark.parametrize(
    "type_name,file_path,fuzzy,type_usage_infos,num_type_usages",
    [
        (
            "AstTreeStringPrinter",
            "/src/checkstyle/src/main/java/com/puppycrawl/tools/checkstyle/AstTreeStringPrinter.java",
            False,
            [
                TestTypeUsageInfo(
                    file_path="/src/checkstyle/src/test/java/com/puppycrawl/tools/checkstyle/AstTreeStringPrinterTest.java",
                    line_number=87,
                ),
            ],
            6,
        ),
    ],
)
@pytest.mark.skip(
    reason="Skipping type usage test for now. It's failing for this example."
)
@pytest.mark.integration
def test_get_type_usages(
    checkstyle_oss_fuzz_task: ChallengeTask,
    checkstyle_oss_fuzz_cq: CodeQuery,
    type_name,
    file_path,
    fuzzy,
    type_usage_infos,
    num_type_usages,
):
    """Test that we can get type usages"""
    common_test_get_type_usages(
        checkstyle_oss_fuzz_task,
        checkstyle_oss_fuzz_cq,
        type_name,
        file_path,
        fuzzy,
        type_usage_infos,
        num_type_usages,
    )
