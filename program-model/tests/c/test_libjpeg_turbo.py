"""CodeQuery primitives testing"""

import pytest
from pathlib import Path
from dataclasses import dataclass

from buttercup.common.challenge_task import ChallengeTask
from buttercup.program_model.codequery import CodeQuery
from ..conftest import oss_fuzz_task


@dataclass(frozen=True)
class TestFunctionInfo:
    num_bodies: int
    body_excerpts: list[str]


# Prevent pytest from collecting this as a test
TestFunctionInfo.__test__ = False


@pytest.fixture
def libjpeg_oss_fuzz_task(tmp_path: Path):
    return oss_fuzz_task(
        tmp_path,
        "libjpeg-turbo",
        "libjpeg-turbo",
        "https://github.com/libjpeg-turbo/libjpeg-turbo",
        "6d91e950c871103a11bac2f10c63bf998796c719",
    )


# Test searching for functions in codebase where we expect
# only 1 function to be returned. To support multiple matches
# we should make `function_info` a list of expected function results
# instead of one result only
@pytest.mark.parametrize(
    "function_name,file_path,function_info",
    [
        (
            "process_data_context_main",
            "jdmainct.c",
            TestFunctionInfo(
                num_bodies=1,
                body_excerpts=[
                    """process_data_context_main(j_decompress_ptr cinfo, JSAMPARRAY output_buf,
                          JDIMENSION *out_row_ctr, JDIMENSION out_rows_avail)
{
  my_main_ptr main_ptr = (my_main_ptr)cinfo->main;

  /* Read input data if we haven't filled the main buffer yet */
  if (!main_ptr->buffer_full) {""",
                    """/* Still need to process last row group of this iMCU row, */
    /* which is saved at index M+1 of the other xbuffer */
    main_ptr->rowgroup_ctr = (JDIMENSION)(cinfo->_min_DCT_scaled_size + 1);
    main_ptr->rowgroups_avail = (JDIMENSION)(cinfo->_min_DCT_scaled_size + 2);
    main_ptr->context_state = CTX_POSTPONED_ROW;
  }
}""",
                ],
            ),
        ),
        (
            "decompress_smooth_data",
            "jdcoefct.c",
            TestFunctionInfo(
                num_bodies=1,
                body_excerpts=[
                    """decompress_smooth_data(j_decompress_ptr cinfo, JSAMPIMAGE output_buf)
{
  my_coef_ptr coef = (my_coef_ptr)cinfo->coef;
  JDIMENSION last_iMCU_row = cinfo->total_iMCU_rows - 1;
  JDIMENSION block_num, last_block_column;
  int ci, block_row, block_rows, access_rows;""",
                    """if (++(cinfo->output_iMCU_row) < cinfo->total_iMCU_rows)
    return JPEG_ROW_COMPLETED;
  return JPEG_SCAN_COMPLETED;""",
                ],
            ),
        ),
        (
            "jpeg_read_scanlines",
            "jdapistd.c",
            TestFunctionInfo(
                num_bodies=1,
                body_excerpts=[
                    """jpeg_read_scanlines(j_decompress_ptr cinfo, JSAMPARRAY scanlines,
                    JDIMENSION max_lines)
{
  JDIMENSION row_ctr;

  if (cinfo->global_state != DSTATE_SCANNING)""",
                    """/* Process some data */
  row_ctr = 0;
  (*cinfo->main->process_data) (cinfo, scanlines, &row_ctr, max_lines);
  cinfo->output_scanline += row_ctr;
  return row_ctr;
}""",
                ],
            ),
        ),
    ],
)
@pytest.mark.integration
def test_libjpeg_indexing(
    libjpeg_oss_fuzz_task: ChallengeTask, function_name, file_path, function_info
):
    """Test that we can index libjpeg"""
    codequery = CodeQuery(libjpeg_oss_fuzz_task)
    functions = codequery.get_functions(function_name, file_path=Path(file_path))
    assert len(functions) == 1
    assert functions[0].name == function_name
    assert len(functions[0].bodies) == function_info.num_bodies
    for body in function_info.body_excerpts:
        assert any([body in x.body for x in functions[0].bodies])
