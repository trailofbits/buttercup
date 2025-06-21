"""Macros testing"""

import pytest

from buttercup.common.challenge_task import ChallengeTask
from buttercup.program_model.codequery import CodeQuery
from .common import (
    common_test_get_functions,
    common_test_get_type_definitions,
    TestFunctionInfo,
    TestTypeDefinitionInfo,
    TypeDefinitionType,
)


@pytest.mark.parametrize(
    "function_name,file_path,function_info",
    [
        (
            "png_create_read_struct",
            "/src/libpng/pngread.c",
            TestFunctionInfo(
                num_bodies=1,
                body_excerpts=[
                    """#ifndef PNG_USER_MEM_SUPPORTED
   png_structp png_ptr = png_create_png_struct(user_png_ver, error_ptr,
        error_fn, warn_fn, NULL, NULL, NULL);
#else
   return png_create_read_struct_2(user_png_ver, error_ptr, error_fn,
        warn_fn, NULL, NULL, NULL);
"""
                ],
            ),
        ),
        (
            "png_create_info_struct",
            "/src/libpng/png.c",
            TestFunctionInfo(
                num_bodies=1,
                body_excerpts=[
                    """info_ptr = png_voidcast(png_inforp, png_malloc_base(png_ptr,"""
                ],
            ),
        ),
    ],
)
@pytest.mark.integration
def test_libpng_get_functions(
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
    "type_name,file_path,fuzzy,type_definition_info",
    [
        (
            "PNG_CHUNK_FROM_STRING",
            "/src/libpng/pngpriv.h",
            False,
            TestTypeDefinitionInfo(
                name="PNG_CHUNK_FROM_STRING",
                type=TypeDefinitionType.PREPROC_FUNCTION,
                definition="PNG_U32(0xff & (s)[0], 0xff & (s)[1], 0xff & (s)[2], 0xff & (s)[3])",
                definition_line=863,
                file_path="/src/libpng/pngpriv.h",
            ),
        ),
        (
            "PNG_ROWBYTES",
            "/src/libpng/pngpriv.h",
            False,
            TestTypeDefinitionInfo(
                name="PNG_ROWBYTES",
                type=TypeDefinitionType.PREPROC_FUNCTION,
                definition="""((pixel_bits) >= 8 ? \\
    ((size_t)(width) * (((size_t)(pixel_bits)) >> 3)) : \\
    (( ((size_t)(width) * ((size_t)(pixel_bits))) + 7) >> 3) )""",
                definition_line=721,
                file_path="/src/libpng/pngpriv.h",
            ),
        ),
    ],
)
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
