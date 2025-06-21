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
            "xmlParse3986Host",
            "/src/libxml2/uri.c",
            TestFunctionInfo(
                num_bodies=1,
                body_excerpts=[
                    """xmlParse3986Host(xmlURIPtr uri, const char **str)
{
    const char *cur = *str;
    const char *host;

    host = cur;"""
                ],
            ),
        ),
    ],
)
@pytest.mark.integration
def test_get_functions(
    libxml2_oss_fuzz_task: ChallengeTask,
    libxml2_oss_fuzz_cq: CodeQuery,
    function_name,
    file_path,
    function_info,
):
    """Test that we can get functions in challenge task code"""
    common_test_get_functions(
        libxml2_oss_fuzz_cq, function_name, file_path, function_info
    )


@pytest.mark.parametrize(
    "function_name,file_path,line_number,fuzzy,expected_callers,num_callers",
    [
        (
            "xmlParse3986Host",
            "/src/libxml2/uri.c",
            None,
            False,
            [
                TestCallerInfo(
                    name="xmlParse3986Authority",
                    file_path="/src/libxml2/uri.c",
                    start_line=553,
                ),
            ],
            1,
        ),
    ],
)
@pytest.mark.integration
def test_get_callers(
    libxml2_oss_fuzz_task: ChallengeTask,
    libxml2_oss_fuzz_cq: CodeQuery,
    function_name,
    file_path,
    line_number,
    fuzzy,
    expected_callers,
    num_callers,
):
    """Test that we can get function callers."""
    common_test_get_callers(
        libxml2_oss_fuzz_task,
        libxml2_oss_fuzz_cq,
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
            "xmlParse3986Host",
            "/src/libxml2/uri.c",
            None,
            False,
            [
                TestCalleeInfo(
                    name="xmlURIUnescapeString",
                    file_path="/src/libxml2/uri.c",
                    start_line=1619,
                ),
                TestCalleeInfo(
                    name="xmlParse3986DecOctet",
                    file_path="/src/libxml2/uri.c",
                    start_line=419,
                ),
            ],
            2,
        ),
    ],
)
@pytest.mark.integration
def test_get_callees(
    libxml2_oss_fuzz_task: ChallengeTask,
    libxml2_oss_fuzz_cq: CodeQuery,
    function_name,
    file_path,
    line_number,
    fuzzy,
    expected_callees,
    num_callees,
):
    """Test that we can get function callees."""
    common_test_get_callees(
        libxml2_oss_fuzz_task,
        libxml2_oss_fuzz_cq,
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
            "xmlURI",
            None,
            False,
            TestTypeDefinitionInfo(
                name="xmlURI",
                type=TypeDefinitionType.TYPEDEF,
                definition="typedef struct _xmlURI xmlURI;",
                definition_line=32,
                file_path="/src/libxml2/include/libxml/uri.h",
            ),
        ),
        (
            "xmlURIPtr",
            None,
            False,
            TestTypeDefinitionInfo(
                name="xmlURIPtr",
                type=TypeDefinitionType.TYPEDEF,
                definition="typedef xmlURI *xmlURIPtr;",
                definition_line=33,
                file_path="/src/libxml2/include/libxml/uri.h",
            ),
        ),
        (
            "_xmlURI",
            None,
            False,
            TestTypeDefinitionInfo(
                name="_xmlURI",
                type=TypeDefinitionType.STRUCT,
                definition="""struct _xmlURI {
    char *scheme;	/* the URI scheme */
    char *opaque;	/* opaque part */
    char *authority;	/* the authority part */
    char *server;	/* the server part */
    char *user;		/* the user part */
    int port;		/* the port number */
    char *path;		/* the path string */
    char *query;	/* the query string (deprecated - use with caution) */
    char *fragment;	/* the fragment identifier */
    int  cleanup;	/* parsing potentially unclean URI */
    char *query_raw;	/* the query string (as it appears in the URI) */
}""",
                definition_line=34,
                file_path="/src/libxml2/include/libxml/uri.h",
            ),
        ),
    ],
)
@pytest.mark.integration
def test_get_type_definitions(
    libxml2_oss_fuzz_task: ChallengeTask,
    libxml2_oss_fuzz_cq: CodeQuery,
    type_name,
    file_path,
    fuzzy,
    type_definition_info,
):
    """Test that we can get type defs"""
    common_test_get_type_definitions(
        libxml2_oss_fuzz_task,
        libxml2_oss_fuzz_cq,
        type_name,
        file_path,
        fuzzy,
        type_definition_info,
    )


@pytest.mark.parametrize(
    "type_name,file_path,fuzzy,type_usage_infos,num_type_usages",
    [
        (
            "xmlURIPtr",
            None,
            False,
            [
                TestTypeUsageInfo(
                    file_path="/src/libxml2/uri.c",
                    line_number=1085,
                ),
            ],
            6,
        ),
    ],
)
@pytest.mark.skip(reason="Skipping because codequery doesn't think xmlURIPtr is a type")
@pytest.mark.integration
def test_get_type_usages(
    libxml2_oss_fuzz_task: ChallengeTask,
    libxml2_oss_fuzz_cq: CodeQuery,
    type_name,
    file_path,
    fuzzy,
    type_usage_infos,
    num_type_usages,
):
    """Test that we can get function callees from zookeeper"""
    common_test_get_type_usages(
        libxml2_oss_fuzz_task,
        libxml2_oss_fuzz_cq,
        type_name,
        file_path,
        fuzzy,
        type_usage_infos,
        num_type_usages,
    )
