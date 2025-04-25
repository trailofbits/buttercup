"""CodeQuery primitives testing"""

import pytest

from buttercup.common.challenge_task import ChallengeTask
from ..conftest import oss_fuzz_task
from ..common import (
    common_test_get_functions,
    TestFunctionInfo,
)


@pytest.fixture(scope="module")
def checkstyle_oss_fuzz_task(tmp_path_factory: pytest.TempPathFactory):
    return oss_fuzz_task(
        tmp_path_factory.mktemp("task_dir"),
        "checkstyle",
        "checkstyle",
        "https://github.com/checkstyle/checkstyle",
        "94cd165da31942661301a09561e4b4ad85366c77",
    )


@pytest.mark.parametrize(
    "function_name,file_path,function_info",
    [
        (
            "JavaLanguageParser",
            "/src/checkstyle/src/main/java/com/puppycrawl/tools/checkstyle/JavaLanguageParser.java",
            TestFunctionInfo(
                num_bodies=2,
                body_excerpts=[
                    """return "[" + simplePrint(unwrapOne(type)) + "]";""",
                    """return ((checkstyleNamedSchemaElement) schemaElement).getName();""",
                ],
            ),
        ),
    ],
)
@pytest.mark.skip("Figure out where this function is located within the source repo")
@pytest.mark.integration
def test_checkstyle_get_functions(
    checkstyle_oss_fuzz_task: ChallengeTask, function_name, file_path, function_info
):
    """Test that we can get functions in challenge task code"""
    common_test_get_functions(
        checkstyle_oss_fuzz_task, function_name, file_path, function_info
    )
