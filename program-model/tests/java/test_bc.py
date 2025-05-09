"""CodeQuery primitives testing"""

import pytest

from buttercup.common.challenge_task import ChallengeTask
from ..common import (
    common_test_get_functions,
    TestFunctionInfo,
)


@pytest.mark.parametrize(
    "function_name,file_path,function_info",
    [
        (
            "doGenerate",
            "/src/bc-java/pkix/src/main/java/org/bouncycastle/cms/CMSAuthEnvelopedDataGenerator.java",
            TestFunctionInfo(
                num_bodies=1,
                body_excerpts=[
                    """authenticatedAttrSet = CMSUtils.processAuthAttrSet(authAttrsGenerator, contentEncryptor);""",
                ],
            ),
        ),
    ],
)
@pytest.mark.integration
def test_bc_get_functions(
    bc_oss_fuzz_task: ChallengeTask, function_name, file_path, function_info
):
    """Test that we can get functions in challenge task code"""
    common_test_get_functions(bc_oss_fuzz_task, function_name, file_path, function_info)
