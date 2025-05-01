"""CodeQuery primitives testing"""

import pytest

from buttercup.common.challenge_task import ChallengeTask
from ..conftest import oss_fuzz_task
from ..common import (
    TestFunctionInfo,
    common_test_get_functions,
)
import logging

logger = logging.getLogger(__name__)


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
            "parseAndPrintJavadocTree",
            "/src/checkstyle/src/main/java/com/puppycrawl/tools/checkstyle/AstTreeStringPrinter.java",
            TestFunctionInfo(
                num_bodies=1,
                body_excerpts=[
                    """baseIndentation = baseIndentation.substring(0, baseIndentation.length() - 2);""",
                ],
            ),
        ),
        (
            "expr",
            "/src/checkstyle/target/generated-sources/antlr/com/puppycrawl/tools/checkstyle/grammar/java/JavaLanguageParser.java",
            TestFunctionInfo(
                num_bodies=27,
                body_excerpts=[
                    """return getRuleContext(ExprContext.class,i);""",
                    """return getRuleContext(ExprContext.class,0);""",
                ],
            ),
        ),
    ],
)
@pytest.mark.integration
def test_checkstyle_get_functions(
    checkstyle_oss_fuzz_task: ChallengeTask, function_name, file_path, function_info
):
    """Test that we can get functions in challenge task code"""
    common_test_get_functions(
        checkstyle_oss_fuzz_task, function_name, file_path, function_info
    )
