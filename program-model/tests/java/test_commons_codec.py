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
            "apply",
            "/src/commons-codec/src/main/java/org/apache/commons/codec/language/bm/PhoneticEngine.java",
            TestFunctionInfo(
                num_bodies=1,
                body_excerpts=[
                    "final LanguageSet languages = left.getLanguages().restrictTo(right.getLanguages());",
                ],
            ),
        ),
        (
            "invoke",
            "/src/commons-codec/src/main/java/org/apache/commons/codec/language/bm/PhoneticEngine.java",
            TestFunctionInfo(
                num_bodies=1,
                body_excerpts=[
                    "final List<Rule> rules = this.finalRules.get(input.subSequence(i, i+patternLength));",
                ],
            ),
        ),
    ],
)
@pytest.mark.integration
def test_commons_codec_get_functions(
    commons_codec_oss_fuzz_task: ChallengeTask, function_name, file_path, function_info
):
    """Test that we can get functions in challenge task code"""
    common_test_get_functions(
        commons_codec_oss_fuzz_task, function_name, file_path, function_info
    )
