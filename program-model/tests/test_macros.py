"""Macros testing"""

import pytest

from buttercup.common.challenge_task import ChallengeTask
from .conftest import oss_fuzz_task
from .common import (
    common_test_get_functions,
    common_test_get_type_definitions,
    TestFunctionInfo,
    TestTypeDefinitionInfo,
    TypeDefinitionType,
)


@pytest.fixture(scope="module")
def libpng_oss_fuzz_task(tmp_path_factory: pytest.TempPathFactory):
    return oss_fuzz_task(
        tmp_path_factory.mktemp("task_dir"),
        "libpng",
        "libpng",
        "https://github.com/pnggroup/libpng",
        "44f97f08d729fcc77ea5d08e02cd538523dd7157",
    )


@pytest.mark.parametrize(
    "function_name,file_path,function_info",
    [
        (
            "png_create_read_struct",
            "/src/libpng/pngread.c",
            TestFunctionInfo(
                num_bodies=2,  # TODO(Evan): This is wrong, the query grabs the next function as well.
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
                num_bodies=2,  # TODO(Evan): This is wrong, the query grabs the next function as well.
                body_excerpts=[
                    """info_ptr = png_voidcast(png_inforp, png_malloc_base(png_ptr,"""
                ],
            ),
        ),
    ],
)
@pytest.mark.integration
def test_libpng_get_functions(
    libpng_oss_fuzz_task: ChallengeTask, function_name, file_path, function_info
):
    """Test that we can get functions in challenge task code"""
    common_test_get_functions(
        libpng_oss_fuzz_task, function_name, file_path, function_info
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
                definition_line=890,  # TODO(Evan): This is wrong, we need to get the correct line number of the macro definition
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
                definition="(( ((size_t)(width) * ((size_t)(pixel_bits))) + 7) >> 3) )",
                definition_line=721,
                file_path="/src/libpng/pngpriv.h",
            ),
        ),
    ],
)
@pytest.mark.integration
def test_get_type_definitions(
    libpng_oss_fuzz_task: ChallengeTask,
    type_name,
    file_path,
    fuzzy,
    type_definition_info,
):
    """Test that we can get type defs"""
    common_test_get_type_definitions(
        libpng_oss_fuzz_task,
        type_name,
        file_path,
        fuzzy,
        type_definition_info,
    )
