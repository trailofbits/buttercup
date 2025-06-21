import pytest

from buttercup.common.challenge_task import ChallengeTask
from buttercup.program_model.codequery import CodeQuery
from ..common import (
    common_test_get_callers,
    common_test_get_callees,
    common_test_get_functions,
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
            "createHuffmanDecodingTables",
            "/src/commons-compress/src/main/java/org/apache/commons/compress/compressors/bzip2/BZip2CompressorInputStream.java",
            TestFunctionInfo(
                num_bodies=1,
                body_excerpts=[
                    """int minLen = 32;
            int maxLen = 0;
            final char[] len_t = len[t];
            for (int i = alphaSize; --i >= 0;) {
                final char lent = len_t[i];
                if (lent > maxLen) {
                    maxLen = lent;
                }
                if (lent < minLen) {
                    minLen = lent;
                }
            }""",
                ],
            ),
        ),
    ],
)
@pytest.mark.integration
def test_get_functions(
    commons_compress_oss_fuzz_task: ChallengeTask,
    commons_compress_oss_fuzz_cq: CodeQuery,
    function_name,
    file_path,
    function_info,
):
    """Test that we can get functions in challenge task code"""
    common_test_get_functions(
        commons_compress_oss_fuzz_cq, function_name, file_path, function_info
    )


@pytest.mark.parametrize(
    "function_name,file_path,line_number,fuzzy,expected_callers,num_callers",
    [
        (
            "createHuffmanDecodingTables",
            "/src/commons-compress/src/main/java/org/apache/commons/compress/compressors/bzip2/BZip2CompressorInputStream.java",
            None,
            False,
            [
                TestCallerInfo(
                    name="recvDecodingTables",
                    file_path="/src/src/main/java/org/apache/commons/compress/compressors/bzip2/BZip2CompressorInputStream.java",
                    start_line=698,
                ),
            ],
            1,
        ),
    ],
)
@pytest.mark.skip(
    reason="Issue with codequery thinking the caller is bsGetBit on line 778"
)
@pytest.mark.integration
def test_get_callers(
    commons_compress_oss_fuzz_task: ChallengeTask,
    commons_compress_oss_fuzz_cq: CodeQuery,
    function_name,
    file_path,
    line_number,
    fuzzy,
    expected_callers,
    num_callers,
):
    """Test that we can get function callers."""
    common_test_get_callers(
        commons_compress_oss_fuzz_task,
        commons_compress_oss_fuzz_cq,
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
            "createHuffmanDecodingTables",
            "/src/commons-compress/src/main/java/org/apache/commons/compress/compressors/bzip2/BZip2CompressorInputStream.java",
            None,
            False,
            [
                TestCalleeInfo(
                    name="hbCreateDecodeTables",
                    file_path="/src/commons-compress/src/main/java/org/apache/commons/compress/compressors/bzip2/BZip2CompressorInputStream.java",
                    start_line=158,
                ),
            ],
            1,
        ),
    ],
)
@pytest.mark.integration
def test_get_callees(
    commons_compress_oss_fuzz_task: ChallengeTask,
    commons_compress_oss_fuzz_cq: CodeQuery,
    function_name,
    file_path,
    line_number,
    fuzzy,
    expected_callees,
    num_callees,
):
    """Test that we can get function callees."""
    common_test_get_callees(
        commons_compress_oss_fuzz_task,
        commons_compress_oss_fuzz_cq,
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
            "Data",
            None,
            False,
            TestTypeDefinitionInfo(
                name="Data",
                type=TypeDefinitionType.CLASS,
                definition="private static final class Data {",
                definition_line=44,
                file_path="/src/commons-compress/src/main/java/org/apache/commons/compress/compressors/bzip2/BZip2CompressorInputStream.java",
            ),
        ),
    ],
)
@pytest.mark.integration
def test_get_type_definitions(
    commons_compress_oss_fuzz_task: ChallengeTask,
    commons_compress_oss_fuzz_cq: CodeQuery,
    type_name,
    file_path,
    fuzzy,
    type_definition_info,
):
    """Test that we can get type defs"""
    common_test_get_type_definitions(
        commons_compress_oss_fuzz_task,
        commons_compress_oss_fuzz_cq,
        type_name,
        file_path,
        fuzzy,
        type_definition_info,
    )


@pytest.mark.parametrize(
    "type_name,file_path,fuzzy,type_usage_infos,num_type_usages",
    [
        (
            "Data",
            None,
            False,
            [
                TestTypeUsageInfo(
                    file_path="/src/commons-compress/src/main/java/org/apache/commons/compress/compressors/bzip2/BZip2CompressorInputStream.java",
                    line_number=593,
                ),
            ],
            31,
        ),
    ],
)
@pytest.mark.integration
def test_get_type_usages(
    commons_compress_oss_fuzz_task: ChallengeTask,
    commons_compress_oss_fuzz_cq: CodeQuery,
    type_name,
    file_path,
    fuzzy,
    type_usage_infos,
    num_type_usages,
):
    """Test that we can get function callees from zookeeper"""
    common_test_get_type_usages(
        commons_compress_oss_fuzz_task,
        commons_compress_oss_fuzz_cq,
        type_name,
        file_path,
        fuzzy,
        type_usage_infos,
        num_type_usages,
    )
