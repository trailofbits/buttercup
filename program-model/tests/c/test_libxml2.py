import pytest

from buttercup.common.challenge_task import ChallengeTask
from ..conftest import oss_fuzz_task
from ..common import (
    common_test_get_callees,
    common_test_get_functions,
    TestFunctionInfo,
    TestCalleeInfo,
)


@pytest.fixture(scope="module")
def libxml2_oss_fuzz_task(tmp_path_factory: pytest.TempPathFactory):
    return oss_fuzz_task(
        tmp_path_factory.mktemp("task_dir"),
        "libxml2",
        "libxml2",
        "https://gitlab.gnome.org/GNOME/libxml2",
        "1c82bca6bd23d0f0858d7fc228ec3a91fda3e0e2",
        # "163da97b1ad4492201149e0234d9db68e2fa245b",
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
    libxml2_oss_fuzz_task: ChallengeTask, function_name, file_path, function_info
):
    """Test that we can get functions in challenge task code"""
    common_test_get_functions(
        libxml2_oss_fuzz_task, function_name, file_path, function_info
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
                    start_line=1611,
                ),
                TestCalleeInfo(
                    name="xmlParse3986DecOctet",
                    file_path="/src/libxml2/uri.c",
                    start_line=419,
                ),
            ],
            2,  # num callees after deduplication
        ),
    ],
)
@pytest.mark.integration
def test_get_callees(
    libxml2_oss_fuzz_task: ChallengeTask,
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
        function_name,
        file_path,
        line_number,
        fuzzy,
        expected_callees,
        num_callees,
    )
