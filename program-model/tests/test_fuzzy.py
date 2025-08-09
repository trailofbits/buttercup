"""Fuzzy matching testing"""

import pytest

from buttercup.common.challenge_task import ChallengeTask
from buttercup.program_model.codequery import CodeQuery


@pytest.mark.parametrize(
    "search_string,match_string,threshold",
    [
        ("png_read_chunk_header", "png_read_chunk_header", 100),
        ("OSS_FUZZ_png_read_chunk_header", "png_read_chunk_header", 80),
        ("OSS_FUZZ_png_reciprocal", "png_reciprocal", 75),
        ("png.c:png_image_free_function", "png_image_free_function", 80),
        ("_Z12default_freeP14png_struct_defPv", "default_free", 50),
        ("_Z14limited_mallocP14png_struct_defm", "limited_malloc", 50),
        ("_Z14user_read_dataP14png_struct_defPhm", "user_read_data", 50),
    ],
)
@pytest.mark.integration
def test_libpng_get_functions_fuzzy(
    libpng_oss_fuzz_task: ChallengeTask, search_string, match_string, threshold
):
    """Test that we can get functions in challenge task code"""
    codequery = CodeQuery(libpng_oss_fuzz_task)
    functions = codequery.get_functions(
        search_string, fuzzy=True, fuzzy_threshold=threshold
    )
    assert len(functions) > 0
    assert any(f.name == match_string for f in functions)
