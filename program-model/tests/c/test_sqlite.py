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
    TestTypeDefinitionInfo,
    TestTypeUsageInfo,
    TypeDefinitionType,
)


@pytest.mark.parametrize(
    "function_name,file_path,function_info",
    [
        (
            "genSeqMember",
            "/src/sqlite3/ext/misc/series.c",
            TestFunctionInfo(
                num_bodies=1,
                body_excerpts=[
                    """if( ix>=2 ){
    sqlite3_int64 ix2 = (sqlite3_int64)ix/2;
    smBase += ix2*smStep;
    ix -= ix2;
  }
  return smBase + ((sqlite3_int64)ix)*smStep;""",
                ],
            ),
        ),
        (
            "shell_error_context",
            "/src/sqlite3/src/shell.c.in",
            TestFunctionInfo(
                num_bodies=1,
                body_excerpts=[
                    """  while( iOffset>50 ){
    iOffset--;
    zSql++;
    while( (zSql[0]&0xc0)==0x80 ){ zSql++; iOffset--; }
  }""",
                ],
            ),
        ),
    ],
)
@pytest.mark.integration
def test_get_functions(
    sqlite_oss_fuzz_task: ChallengeTask,
    sqlite_oss_fuzz_cq: CodeQuery,
    function_name,
    file_path,
    function_info,
):
    """Test that we can get functions in challenge task code"""
    common_test_get_functions(
        sqlite_oss_fuzz_cq, function_name, file_path, function_info
    )


@pytest.mark.parametrize(
    "function_name,file_path,line_number,fuzzy,expected_callers,num_callers",
    [
        (
            "genSeqMember",
            "/src/sqlite3/ext/misc/series.c",
            None,
            False,
            [
                TestCallerInfo(
                    name="setupSequence",
                    file_path="/src/sqlite3/ext/misc/series.c",
                    start_line=171,
                ),
            ],
            4,
        ),
    ],
)
@pytest.mark.integration
def test_get_callers(
    sqlite_oss_fuzz_task: ChallengeTask,
    sqlite_oss_fuzz_cq: CodeQuery,
    function_name,
    file_path,
    line_number,
    fuzzy,
    expected_callers,
    num_callers,
):
    """Test that we can get function callers."""
    common_test_get_callers(
        sqlite_oss_fuzz_task,
        sqlite_oss_fuzz_cq,
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
            "genSeqMember",
            "/src/sqlite3/ext/misc/series.c",
            None,
            False,
            [],
            0,
        ),
    ],
)
@pytest.mark.integration
def test_get_callees(
    sqlite_oss_fuzz_task: ChallengeTask,
    sqlite_oss_fuzz_cq: CodeQuery,
    function_name,
    file_path,
    line_number,
    fuzzy,
    expected_callees,
    num_callees,
):
    """Test that we can get function callees."""
    common_test_get_callees(
        sqlite_oss_fuzz_task,
        sqlite_oss_fuzz_cq,
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
            "SequenceSpec",
            None,
            False,
            TestTypeDefinitionInfo(
                name="SequenceSpec",
                type=TypeDefinitionType.TYPEDEF,
                definition="""typedef struct SequenceSpec {
  sqlite3_int64 iOBase;        /* Original starting value ("start") */
  sqlite3_int64 iOTerm;        /* Original terminal value ("stop") */
  sqlite3_int64 iBase;         /* Starting value to actually use */
  sqlite3_int64 iTerm;         /* Terminal value to actually use */
  sqlite3_int64 iStep;         /* Increment ("step") */
  sqlite3_uint64 uSeqIndexMax; /* maximum sequence index (aka "n") */
  sqlite3_uint64 uSeqIndexNow; /* Current index during generation */
  sqlite3_int64 iValueNow;     /* Current value during generation */
  u8 isNotEOF;                 /* Sequence generation not exhausted */
  u8 isReversing;              /* Sequence is being reverse generated */
} SequenceSpec""",
                definition_line=153,
                file_path="/src/sqlite3/ext/misc/series.c",
            ),
        ),
    ],
)
@pytest.mark.integration
def test_get_type_definitions(
    sqlite_oss_fuzz_task: ChallengeTask,
    sqlite_oss_fuzz_cq: CodeQuery,
    type_name,
    file_path,
    fuzzy,
    type_definition_info,
):
    """Test that we can get type defs"""
    common_test_get_type_definitions(
        sqlite_oss_fuzz_task,
        sqlite_oss_fuzz_cq,
        type_name,
        file_path,
        fuzzy,
        type_definition_info,
    )


@pytest.mark.parametrize(
    "type_name,file_path,fuzzy,type_usage_infos,num_type_usages",
    [
        (
            "SequenceSpec",
            None,
            False,
            [
                TestTypeUsageInfo(
                    file_path="/src/sqlite3/ext/misc/series.c",
                    line_number=153,
                ),
            ],
            6,
        ),
    ],
)
@pytest.mark.skip(reason="Issue with codequery not thinking the type is used")
@pytest.mark.integration
def test_get_type_usages(
    sqlite_oss_fuzz_task: ChallengeTask,
    sqlite_oss_fuzz_cq: CodeQuery,
    type_name,
    file_path,
    fuzzy,
    type_usage_infos,
    num_type_usages,
):
    """Test that we can get function callees from zookeeper"""
    common_test_get_type_usages(
        sqlite_oss_fuzz_task,
        sqlite_oss_fuzz_cq,
        type_name,
        file_path,
        fuzzy,
        type_usage_infos,
        num_type_usages,
    )
