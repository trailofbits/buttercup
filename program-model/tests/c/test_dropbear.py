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
            "read_packet_init",
            "/src/dropbear/src/packet.c",
            TestFunctionInfo(
                num_bodies=1,
                body_excerpts=[
                    """if (len > ses.readbuf->size) {
		ses.readbuf = buf_resize(ses.readbuf, len);		
	}
	buf_setlen(ses.readbuf, len);
	buf_setpos(ses.readbuf, blocksize);
	return DROPBEAR_SUCCESS;""",
                ],
            ),
        ),
    ],
)
@pytest.mark.integration
def test_get_functions(
    dropbear_oss_fuzz_cq: CodeQuery, function_name, file_path, function_info
):
    """Test that we can get functions in challenge task code"""
    common_test_get_functions(
        dropbear_oss_fuzz_cq, function_name, file_path, function_info
    )


@pytest.mark.parametrize(
    "function_name,file_path,line_number,fuzzy,expected_callers,num_callers",
    [
        (
            "read_packet_init",
            "/src/dropbear/src/packet.c",
            None,
            False,
            [
                TestCallerInfo(
                    name="read_packet",
                    file_path="/src/dropbear/src/packet.c",
                    start_line=150,
                ),
            ],
            1,
        ),
    ],
)
@pytest.mark.integration
def test_get_callers(
    dropbear_oss_fuzz_task: ChallengeTask,
    dropbear_oss_fuzz_cq: CodeQuery,
    function_name,
    file_path,
    line_number,
    fuzzy,
    expected_callers,
    num_callers,
):
    """Test that we can get function callers."""
    common_test_get_callers(
        dropbear_oss_fuzz_task,
        dropbear_oss_fuzz_cq,
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
            "read_packet_init",
            "/src/dropbear/src/packet.c",
            None,
            False,
            [
                TestCalleeInfo(
                    name="buf_incrwritepos",
                    file_path="/src/dropbear/src/buffer.c",
                    start_line=120,
                ),
            ],
            10,
        ),
    ],
)
@pytest.mark.integration
def test_get_callees(
    dropbear_oss_fuzz_task: ChallengeTask,
    dropbear_oss_fuzz_cq: CodeQuery,
    function_name,
    file_path,
    line_number,
    fuzzy,
    expected_callees,
    num_callees,
):
    """Test that we can get function callees."""
    common_test_get_callees(
        dropbear_oss_fuzz_task,
        dropbear_oss_fuzz_cq,
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
            "packetlist",
            None,
            False,
            TestTypeDefinitionInfo(
                name="packetlist",
                type=TypeDefinitionType.STRUCT,
                definition="""struct packetlist {
	struct packetlist *next;
	buffer * payload;
}""",
                definition_line=115,
                file_path="/src/dropbear/src/session.h",
            ),
        ),
    ],
)
@pytest.mark.integration
def test_get_type_definitions(
    dropbear_oss_fuzz_task: ChallengeTask,
    dropbear_oss_fuzz_cq: CodeQuery,
    type_name,
    file_path,
    fuzzy,
    type_definition_info,
):
    """Test that we can get type defs"""
    common_test_get_type_definitions(
        dropbear_oss_fuzz_task,
        dropbear_oss_fuzz_cq,
        type_name,
        file_path,
        fuzzy,
        type_definition_info,
    )


@pytest.mark.parametrize(
    "type_name,file_path,fuzzy,type_usage_infos,num_type_usages",
    [
        (
            "packetlist",
            None,
            False,
            [
                TestTypeUsageInfo(
                    file_path="/src/dropbear/src/packet.c",
                    line_number=479,
                ),
            ],
            7,
        ),
    ],
)
@pytest.mark.integration
def test_get_type_usages(
    dropbear_oss_fuzz_task: ChallengeTask,
    dropbear_oss_fuzz_cq: CodeQuery,
    type_name,
    file_path,
    fuzzy,
    type_usage_infos,
    num_type_usages,
):
    """Test that we can get function callees from zookeeper"""
    common_test_get_type_usages(
        dropbear_oss_fuzz_task,
        dropbear_oss_fuzz_cq,
        type_name,
        file_path,
        fuzzy,
        type_usage_infos,
        num_type_usages,
    )
