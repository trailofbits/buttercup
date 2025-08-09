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
    TestCalleeInfo,
    TestTypeDefinitionInfo,
    TestTypeUsageInfo,
    TypeDefinitionType,
)


@pytest.mark.parametrize(
    "function_name,file_path,function_info",
    [
        (
            "png_handle_iCCP",
            "/src/libpng/pngrutil.c",
            TestFunctionInfo(
                num_bodies=1,
                body_excerpts=[
                    """png_const_charp errmsg = NULL; /* error message output, or no error */
   int finished = 0; /* crc checked */

   png_debug(1, "in png_handle_iCCP");

   if ((png_ptr->mode & PNG_HAVE_IHDR) == 0)
      png_chunk_error(png_ptr, "missing IHDR");

   else if ((png_ptr->mode & (PNG_HAVE_IDAT|PNG_HAVE_PLTE)) != 0)
   {
      png_crc_finish(png_ptr, length);
      png_chunk_benign_error(png_ptr, "out of place");
      return;
   }""",
                ],
            ),
        ),
    ],
)
@pytest.mark.integration
def test_get_functions(
    libpng_oss_fuzz_task: ChallengeTask,
    libpng_oss_fuzz_cq: CodeQuery,
    function_name,
    file_path,
    function_info,
):
    """Test that we can get functions in challenge task code"""
    common_test_get_functions(
        libpng_oss_fuzz_cq, function_name, file_path, function_info
    )


@pytest.mark.parametrize(
    "function_name,file_path,line_number,fuzzy,expected_callers,num_callers",
    [
        (
            "png_handle_iCCP",
            "/src/libpng/pngrutil.c",
            None,
            False,
            [],
            0,
        ),
    ],
)
@pytest.mark.integration
def test_get_callers(
    libpng_oss_fuzz_task: ChallengeTask,
    libpng_oss_fuzz_cq: CodeQuery,
    function_name,
    file_path,
    line_number,
    fuzzy,
    expected_callers,
    num_callers,
):
    """Test that we can get function callers."""
    common_test_get_callers(
        libpng_oss_fuzz_task,
        libpng_oss_fuzz_cq,
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
            "png_handle_iCCP",
            "/src/libpng/pngrutil.c",
            None,
            False,
            [
                TestCalleeInfo(
                    name="png_crc_finish",
                    file_path="/src/libpng/pngrutil.c",
                    start_line=225,
                ),
                TestCalleeInfo(
                    name="png_icc_check_tag_table",
                    file_path="/src/libpng/png.c",
                    start_line=2274,
                ),
            ],
            14,
        ),
    ],
)
@pytest.mark.integration
def test_get_callees(
    libpng_oss_fuzz_task: ChallengeTask,
    libpng_oss_fuzz_cq: CodeQuery,
    function_name,
    file_path,
    line_number,
    fuzzy,
    expected_callees,
    num_callees,
):
    """Test that we can get function callees."""
    common_test_get_callees(
        libpng_oss_fuzz_task,
        libpng_oss_fuzz_cq,
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
            "png_structrp",
            None,
            False,
            TestTypeDefinitionInfo(
                name="png_structrp",
                type=TypeDefinitionType.TYPEDEF,
                definition="typedef png_struct * PNG_RESTRICT png_structrp;",
                definition_line=467,
                file_path="/src/libpng/png.h",
            ),
        ),
    ],
)
@pytest.mark.skip(reason="Test fails because it doesn't know png_structrp is a type.")
@pytest.mark.integration
def test_get_type_definitions(
    libpng_oss_fuzz_task: ChallengeTask,
    libpng_oss_fuzz_cq: CodeQuery,
    type_name,
    file_path,
    fuzzy,
    type_definition_info,
):
    """Test that we can get type defs"""
    common_test_get_type_definitions(
        libpng_oss_fuzz_task,
        libpng_oss_fuzz_cq,
        type_name,
        file_path,
        fuzzy,
        type_definition_info,
    )


@pytest.mark.parametrize(
    "type_name,file_path,fuzzy,type_usage_infos,num_type_usages",
    [
        (
            "png_structrp",
            None,
            False,
            [
                TestTypeUsageInfo(
                    file_path="/src/libpng/png.c",
                    line_number=1085,
                ),
            ],
            6,
        ),
    ],
)
@pytest.mark.skip(reason="Test fails because it doesn't know png_structrp is a type.")
@pytest.mark.integration
def test_get_type_usages(
    libpng_oss_fuzz_task: ChallengeTask,
    libpng_oss_fuzz_cq: CodeQuery,
    type_name,
    file_path,
    fuzzy,
    type_usage_infos,
    num_type_usages,
):
    """Test that we can get function callees from zookeeper"""
    common_test_get_type_usages(
        libpng_oss_fuzz_task,
        libpng_oss_fuzz_cq,
        type_name,
        file_path,
        fuzzy,
        type_usage_infos,
        num_type_usages,
    )
