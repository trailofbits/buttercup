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
    TestCallerInfo,
    TestTypeDefinitionInfo,
    TestTypeUsageInfo,
    TypeDefinitionType,
)


@pytest.mark.parametrize(
    "function_name,file_path,function_info",
    [
        (
            "freerdp_assistance_parse_file_buffer",
            "/src/FreeRDP/libfreerdp/common/assistance.c",
            TestFunctionInfo(
                num_bodies=1,
                body_excerpts=[
                    """const size_t len = strnlen(cbuffer, size);
	if (len == size)
		WLog_WARN(TAG, "Input data not '\\0' terminated");

	if (!abuffer)
		return -1;

	const int rc = freerdp_assistance_parse_file_buffer_int(file, abuffer, len + 1, password);
	free(abuffer);
	return rc;""",
                ],
            ),
        ),
    ],
)
@pytest.mark.integration
def test_get_functions(
    freerdp_oss_fuzz_task: ChallengeTask,
    freerdp_oss_fuzz_cq: CodeQuery,
    function_name,
    file_path,
    function_info,
):
    """Test that we can get functions in challenge task code"""
    common_test_get_functions(
        freerdp_oss_fuzz_cq, function_name, file_path, function_info
    )


@pytest.mark.parametrize(
    "function_name,file_path,line_number,fuzzy,expected_callers,num_callers",
    [
        (
            "freerdp_assistance_parse_file_buffer",
            "/src/FreeRDP/libfreerdp/common/assistance.c",
            None,
            False,
            [
                TestCallerInfo(
                    name="parse_file_buffer",
                    file_path="/src/FreeRDP/libfreerdp/common/test/TestFuzzCommonAssistanceParseFileBuffer.c",
                    start_line=3,
                ),
            ],
            4,
        ),
    ],
)
@pytest.mark.integration
def test_get_callers(
    freerdp_oss_fuzz_task: ChallengeTask,
    freerdp_oss_fuzz_cq: CodeQuery,
    function_name,
    file_path,
    line_number,
    fuzzy,
    expected_callers,
    num_callers,
):
    """Test that we can get function callers."""
    common_test_get_callers(
        freerdp_oss_fuzz_task,
        freerdp_oss_fuzz_cq,
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
            "freerdp_assistance_parse_file_buffer",
            "/src/FreeRDP/libfreerdp/common/assistance.c",
            None,
            False,
            [
                TestCalleeInfo(
                    name="freerdp_assistance_parse_file_buffer_int",
                    file_path="/src/FreeRDP/libfreerdp/common/assistance.c",
                    start_line=1152,
                ),
            ],
            2,
        ),
    ],
)
@pytest.mark.integration
def test_get_callees(
    freerdp_oss_fuzz_task: ChallengeTask,
    freerdp_oss_fuzz_cq: CodeQuery,
    function_name,
    file_path,
    line_number,
    fuzzy,
    expected_callees,
    num_callees,
):
    """Test that we can get function callees."""
    common_test_get_callees(
        freerdp_oss_fuzz_task,
        freerdp_oss_fuzz_cq,
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
            "rdp_assistance_file",
            None,
            False,
            TestTypeDefinitionInfo(
                name="rdp_assistance_file",
                type=TypeDefinitionType.STRUCT,
                definition="""struct rdp_assistance_file
{
	UINT32 Type;

	char* Username;
	char* LHTicket;
	char* RCTicket;
	char* PassStub;
	UINT32 DtStart;
	UINT32 DtLength;
	BOOL LowSpeed;
	BOOL RCTicketEncrypted;

	char* ConnectionString1;
	char* ConnectionString2;

	BYTE* EncryptedPassStub;
	size_t EncryptedPassStubLength;

	BYTE* EncryptedLHTicket;
	size_t EncryptedLHTicketLength;

	wArrayList* MachineAddresses;
	wArrayList* MachinePorts;
	wArrayList* MachineUris;

	char* RASessionId;
	char* RASpecificParams;
	char* RASpecificParams2;

	char* filename;
	char* password;
}""",
                definition_line=44,
                file_path="/src/FreeRDP/libfreerdp/common/assistance.c",
            ),
        ),
        (
            "rdpAssistanceFile",
            None,
            False,
            TestTypeDefinitionInfo(
                name="rdpAssistanceFile",
                type=TypeDefinitionType.TYPEDEF,
                definition="""typedef struct rdp_assistance_file rdpAssistanceFile;""",
                definition_line=32,
                file_path="/src/FreeRDP/include/freerdp/assistance.h",
            ),
        ),
    ],
)
@pytest.mark.integration
def test_get_type_definitions(
    freerdp_oss_fuzz_task: ChallengeTask,
    freerdp_oss_fuzz_cq: CodeQuery,
    type_name,
    file_path,
    fuzzy,
    type_definition_info,
):
    """Test that we can get type defs"""
    common_test_get_type_definitions(
        freerdp_oss_fuzz_task,
        freerdp_oss_fuzz_cq,
        type_name,
        file_path,
        fuzzy,
        type_definition_info,
    )


@pytest.mark.parametrize(
    "type_name,file_path,fuzzy,type_usage_infos,num_type_usages",
    [
        (
            "rdpAssistanceFile",
            None,
            False,
            [
                TestTypeUsageInfo(
                    file_path="/src/FreeRDP/server/shadow/Win/win_wds.c",
                    line_number=531,
                ),
            ],
            6,
        ),
    ],
)
@pytest.mark.skip(
    reason="Problem with codequery. Doesn't consider rdpAssistanceFile as being used"
)
@pytest.mark.integration
def test_get_type_usages(
    freerdp_oss_fuzz_task: ChallengeTask,
    freerdp_oss_fuzz_cq: CodeQuery,
    type_name,
    file_path,
    fuzzy,
    type_usage_infos,
    num_type_usages,
):
    """Test that we can get function callees from zookeeper"""
    common_test_get_type_usages(
        freerdp_oss_fuzz_task,
        freerdp_oss_fuzz_cq,
        type_name,
        file_path,
        fuzzy,
        type_usage_infos,
        num_type_usages,
    )
