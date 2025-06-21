import pytest

from buttercup.common.challenge_task import ChallengeTask
from buttercup.program_model.codequery import CodeQuery
from ..common import (
    common_test_get_type_definitions,
    common_test_get_functions,
    common_test_get_callers,
    common_test_get_callees,
    TestCallerInfo,
    TestFunctionInfo,
    TestCalleeInfo,
    TestTypeDefinitionInfo,
)
from buttercup.program_model.utils.common import TypeDefinitionType


# Test searching for functions in codebase where we expect
# only 1 function to be returned. To support multiple matches
# we should make `function_info` a list of expected function results
# instead of one result only
@pytest.mark.parametrize(
    "function_name,file_path,function_info",
    [
        (
            "H5F_addr_decode_len",
            "/src/hdf5/src/H5Fint.c",
            TestFunctionInfo(
                num_bodies=1,
                body_excerpts=[
                    """bool     all_zero = true; /* True if address was all zeroes */
    unsigned u;               /* Local index variable */

    /* Use FUNC_ENTER_NOAPI_NOINIT_NOERR here to avoid performance issues */
    FUNC_ENTER_NOAPI_NOINIT_NOERR

    assert(addr_len);
    assert(pp && *pp);
    assert(addr_p);

    /* Reset value in destination */
    *addr_p = 0;""",
                ],
            ),
        ),
        (
            "H5FL__malloc",
            "/src/hdf5/src/H5FL.c",
            TestFunctionInfo(
                num_bodies=1,
                body_excerpts=[
                    """/* Attempt to allocate the memory requested */
    if (NULL == (ret_value = H5MM_malloc(mem_size))) {
        /* If we can't allocate the memory now, try garbage collecting first */
        if (H5FL_garbage_coll() < 0)
            HGOTO_ERROR(H5E_RESOURCE, H5E_CANTGC, NULL, "garbage collection failed during allocation");

        /* Now try allocating the memory again */
        if (NULL == (ret_value = H5MM_malloc(mem_size)))
            HGOTO_ERROR(H5E_RESOURCE, H5E_NOSPACE, NULL, "memory allocation failed for chunk");
    } /* end if */""",
                ],
            ),
        ),
    ],
)
@pytest.mark.integration
def test_hdf5_get_functions(
    hdf5_oss_fuzz_cq: CodeQuery, function_name, file_path, function_info
):
    """Test that we can get functions in challenge task code"""
    common_test_get_functions(hdf5_oss_fuzz_cq, function_name, file_path, function_info)


@pytest.mark.parametrize(
    "function_name,file_path,line_number,fuzzy,expected_callers,num_callers",
    [
        (
            "H5F_addr_decode_len",
            "src/hdf5/src/H5Fint.c",
            None,
            False,
            [
                TestCallerInfo(
                    name="H5HF__huge_bt2_dir_decode",
                    file_path="/src/hdf5/src/H5HFbtree2.c",
                    start_line=721,
                ),
                TestCallerInfo(
                    name="H5SM__message_decode",
                    file_path="/src/hdf5/src/H5SMmessage.c",
                    start_line=308,
                ),
                TestCallerInfo(
                    name="H5D__bt2_unfilt_decode",
                    file_path="/src/hdf5/src/H5Dbtree2.c",
                    start_line=382,
                ),
                TestCallerInfo(
                    name="H5F_addr_decode",
                    file_path="/src/hdf5/src/H5Fint.c",
                    start_line=3044,
                ),
            ],
            13,
        ),
    ],
)
@pytest.mark.integration
def test_get_callers(
    hdf5_oss_fuzz_task: ChallengeTask,
    hdf5_oss_fuzz_cq: CodeQuery,
    function_name,
    file_path,
    line_number,
    fuzzy,
    expected_callers,
    num_callers,
):
    """Test that we can get function callers"""
    common_test_get_callers(
        hdf5_oss_fuzz_task,
        hdf5_oss_fuzz_cq,
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
            "H5F_addr_decode",
            "src/hdf5/src/H5Fint.c",
            None,
            False,
            [
                TestCalleeInfo(
                    name="H5F_addr_decode_len",
                    file_path="/src/hdf5/src/H5Fint.c",
                    start_line=2975,
                ),
            ],
            None,
        ),
    ],
)
@pytest.mark.integration
def test_get_callees(
    hdf5_oss_fuzz_task: ChallengeTask,
    hdf5_oss_fuzz_cq: CodeQuery,
    function_name,
    file_path,
    line_number,
    fuzzy,
    expected_callees,
    num_callees,
):
    """Test that we can get function callees."""
    common_test_get_callees(
        hdf5_oss_fuzz_task,
        hdf5_oss_fuzz_cq,
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
            "H5VL_connector_prop_t",
            None,
            False,
            TestTypeDefinitionInfo(
                name="H5VL_connector_prop_t",
                type=TypeDefinitionType.TYPEDEF,
                definition="typedef struct H5VL_connector_prop_t {",
                definition_line=49,
                file_path="/src/hdf5/src/H5VLprivate.h",
            ),
        ),
    ],
)
@pytest.mark.integration
def test_get_type_definitions(
    hdf5_oss_fuzz_task: ChallengeTask,
    hdf5_oss_fuzz_cq: CodeQuery,
    type_name,
    file_path,
    fuzzy,
    type_definition_info,
):
    """Test that we can get type defs"""
    common_test_get_type_definitions(
        hdf5_oss_fuzz_task,
        hdf5_oss_fuzz_cq,
        type_name,
        file_path,
        fuzzy,
        type_definition_info,
    )
