"""CodeQuery primitives testing"""

import pytest

from buttercup.common.challenge_task import ChallengeTask
from buttercup.program_model.codequery import CodeQuery
from ..common import (
    common_test_get_functions,
    common_test_get_callers,
    common_test_get_callees,
    common_test_get_type_definitions,
    common_test_get_type_usages,
    TestFunctionInfo,
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
            "apply",
            "/src/commons-codec/src/main/java/org/apache/commons/codec/language/bm/PhoneticEngine.java",
            TestFunctionInfo(
                num_bodies=1,
                body_excerpts=[
                    "final LanguageSet languages = left.getLanguages().restrictTo(right.getLanguages());",
                ],
            ),
        ),
        (
            "invoke",
            "/src/commons-codec/src/main/java/org/apache/commons/codec/language/bm/PhoneticEngine.java",
            TestFunctionInfo(
                num_bodies=1,
                body_excerpts=[
                    "final List<Rule> rules = this.finalRules.get(input.subSequence(i, i+patternLength));",
                ],
            ),
        ),
    ],
)
@pytest.mark.integration
def test_get_functions(
    commons_codec_oss_fuzz_task: ChallengeTask,
    commons_codec_oss_fuzz_cq: CodeQuery,
    function_name,
    file_path,
    function_info,
):
    """Test that we can get functions"""
    common_test_get_functions(
        commons_codec_oss_fuzz_cq, function_name, file_path, function_info
    )


# From: https://github.com/apache/commons-codec/blob/44e4c4d778c3ab87db09c00e9d1c3260fd42dad5/src/main/java/org/apache/commons/codec/language/bm/PhoneticEngine.java#L206
@pytest.mark.parametrize(
    "function_name,file_path,line_number,fuzzy,expected_callers,num_callers",
    [
        (
            "apply",
            "/src/commons-codec/src/main/java/org/apache/commons/codec/language/bm/PhoneticEngine.java",
            None,
            False,
            [
                TestCallerInfo(
                    name="invoke",
                    file_path="/src/commons-codec/src/main/java/org/apache/commons/codec/language/bm/PhoneticEngine.java",
                    start_line=206,
                )
            ],
            1,
        ),
    ],
)
@pytest.mark.skip(reason="Skipping test due to codequery issue")
@pytest.mark.integration
def test_get_callers(
    commons_codec_oss_fuzz_task: ChallengeTask,
    commons_codec_oss_fuzz_cq: CodeQuery,
    function_name,
    file_path,
    line_number,
    fuzzy,
    expected_callers,
    num_callers,
):
    """Test that we can get function callers"""
    common_test_get_callers(
        commons_codec_oss_fuzz_task,
        commons_codec_oss_fuzz_cq,
        function_name,
        file_path,
        line_number,
        fuzzy,
        expected_callers,
        num_callers,
    )


# From: https://github.com/apache/commons-codec/blob/44e4c4d778c3ab87db09c00e9d1c3260fd42dad5/src/main/java/org/apache/commons/codec/language/bm/PhoneticEngine.java#L206
@pytest.mark.parametrize(
    "function_name,file_path,line_number,fuzzy,expected_callees,num_callees",
    [
        (
            "invoke",
            "/src/commons-codec/src/main/java/org/apache/commons/codec/language/bm/PhoneticEngine.java",
            None,
            False,
            [
                TestCalleeInfo(
                    name="apply",
                    file_path="/src/commons-codec/src/main/java/org/apache/commons/codec/language/bm/PhoneticEngine.java",
                    start_line=206,
                )
            ],
            5,
        ),
    ],
)
@pytest.mark.skip(reason="Skipping test due to codequery issue")
@pytest.mark.integration
def test_get_callees(
    commons_codec_oss_fuzz_task: ChallengeTask,
    commons_codec_oss_fuzz_cq: CodeQuery,
    function_name,
    file_path,
    line_number,
    fuzzy,
    expected_callees,
    num_callees,
):
    """Test that we can get function callees."""
    common_test_get_callees(
        commons_codec_oss_fuzz_task,
        commons_codec_oss_fuzz_cq,
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
            "PhonemeBuilder",
            None,
            False,
            TestTypeDefinitionInfo(
                name="PhonemeBuilder",
                type=TypeDefinitionType.CLASS,
                definition="static final class PhonemeBuilder {",
                definition_line=64,
                file_path="/src/commons-codec/src/main/java/org/apache/commons/codec/language/bm/PhoneticEngine.java",
            ),
        ),
    ],
)
@pytest.mark.integration
def test_get_type_definitions(
    commons_codec_oss_fuzz_task: ChallengeTask,
    commons_codec_oss_fuzz_cq: CodeQuery,
    type_name,
    file_path,
    fuzzy,
    type_definition_info,
):
    """Test that we can get type defs"""
    common_test_get_type_definitions(
        commons_codec_oss_fuzz_task,
        commons_codec_oss_fuzz_cq,
        type_name,
        file_path,
        fuzzy,
        type_definition_info,
    )


@pytest.mark.parametrize(
    "type_name,file_path,fuzzy,type_usage_infos,num_type_usages",
    [
        (
            "PhonemeBuilder",
            "/src/commons-codec/src/main/java/org/apache/commons/codec/language/bm/PhoneticEngine.java",
            False,
            [
                TestTypeUsageInfo(
                    file_path="/src/commons-codec/src/main/java/org/apache/commons/codec/language/bm/PhoneticEngine.java",
                    line_number=75,
                ),
            ],
            12,
        ),
    ],
)
@pytest.mark.integration
def test_get_type_usages(
    commons_codec_oss_fuzz_task: ChallengeTask,
    commons_codec_oss_fuzz_cq: CodeQuery,
    type_name,
    file_path,
    fuzzy,
    type_usage_infos,
    num_type_usages,
):
    """Test that we can get type usages"""
    common_test_get_type_usages(
        commons_codec_oss_fuzz_task,
        commons_codec_oss_fuzz_cq,
        type_name,
        file_path,
        fuzzy,
        type_usage_infos,
        num_type_usages,
    )
