"""CodeQuery primitives testing"""

import pytest

from buttercup.common.challenge_task import ChallengeTask
from ..conftest import oss_fuzz_task
from ..common import (
    common_test_get_functions,
    TestFunctionInfo,
)


@pytest.fixture(scope="module")
def bc_oss_fuzz_task(tmp_path_factory: pytest.TempPathFactory):
    return oss_fuzz_task(
        tmp_path_factory.mktemp("task_dir"),
        "bc-java",
        "bc-java",
        "https://github.com/bcgit/bc-java",
        "8b4326f24738ad6f6ab360089436a8a93c6a5424",
    )


@pytest.mark.parametrize(
    "function_name,file_path,function_info",
    [
        (
            "JavaLanguageParser",
            None,
            TestFunctionInfo(
                num_bodies=2,
                body_excerpts=[
                    """return "[" + simplePrint(unwrapOne(type)) + "]";""",
                    """return ((bcNamedSchemaElement) schemaElement).getName();""",
                ],
            ),
        ),
    ],
)
@pytest.mark.skip("Figure out where this function is located within the source repo")
@pytest.mark.integration
def test_bc_get_functions(
    bc_oss_fuzz_task: ChallengeTask, function_name, file_path, function_info
):
    """Test that we can get functions in challenge task code"""
    common_test_get_functions(bc_oss_fuzz_task, function_name, file_path, function_info)
