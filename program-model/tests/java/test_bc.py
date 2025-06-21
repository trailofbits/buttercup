"""CodeQuery primitives testing"""

import pytest

from buttercup.common.challenge_task import ChallengeTask
from buttercup.program_model.codequery import CodeQuery
from ..common import (
    common_test_get_functions,
    common_test_get_callers,
    common_test_get_callees,
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
            "doGenerate",
            "/src/bc-java/pkix/src/main/java/org/bouncycastle/cms/CMSAuthEnvelopedDataGenerator.java",
            TestFunctionInfo(
                num_bodies=1,
                body_excerpts=[
                    """ASN1EncodableVector recipientInfos = new ASN1EncodableVector();
        AlgorithmIdentifier encAlgId;
        ASN1OctetString encContent;

        ByteArrayOutputStream bOut = new ByteArrayOutputStream();
        ASN1Set authenticatedAttrSet = null;""",
                ],
            ),
        ),
    ],
)
@pytest.mark.integration
def test_get_functions(
    bc_oss_fuzz_task: ChallengeTask,
    bc_oss_fuzz_cq: CodeQuery,
    function_name,
    file_path,
    function_info,
):
    """Test that we can get functions in challenge task code"""
    common_test_get_functions(bc_oss_fuzz_cq, function_name, file_path, function_info)


@pytest.mark.parametrize(
    "function_name,file_path,line_number,fuzzy,expected_callers,num_callers",
    [
        (
            "doGenerate",
            "/src/bc-java/pkix/src/main/java/org/bouncycastle/cms/CMSAuthEnvelopedDataGenerator.java",
            None,
            False,
            [
                TestCallerInfo(
                    name="generate",
                    file_path="/src/bc-java/pkix/src/main/java/org/bouncycastle/cms/CMSAuthEnvelopedDataGenerator.java",
                    start_line=117,
                )
            ],
            5,
        ),
    ],
)
@pytest.mark.integration
def test_get_callers(
    bc_oss_fuzz_task: ChallengeTask,
    bc_oss_fuzz_cq: CodeQuery,
    function_name,
    file_path,
    line_number,
    fuzzy,
    expected_callers,
    num_callers,
):
    """Test that we can get function callers"""
    common_test_get_callers(
        bc_oss_fuzz_task,
        bc_oss_fuzz_cq,
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
            "doGenerate",
            "/src/bc-java/pkix/src/main/java/org/bouncycastle/cms/CMSAuthEnvelopedDataGenerator.java",
            None,
            False,
            [
                TestCalleeInfo(
                    name="getAttributes",
                    file_path="/src/bc-java/pkix/src/main/java/org/bouncycastle/cms/CMSAuthEnvelopedDataGenerator.java",
                    start_line=55,
                )
            ],
            2,
        ),
    ],
)
@pytest.mark.skip(
    reason="Skipping callee test for now. It's not working because it gets filtered out from imports."
)
@pytest.mark.integration
def test_get_callees(
    bc_oss_fuzz_task: ChallengeTask,
    bc_oss_fuzz_cq: CodeQuery,
    function_name,
    file_path,
    line_number,
    fuzzy,
    expected_callees,
    num_callees,
):
    """Test that we can get function callees."""
    common_test_get_callees(
        bc_oss_fuzz_task,
        bc_oss_fuzz_cq,
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
            "CMSAuthEnvelopedDataGenerator",
            None,
            False,
            TestTypeDefinitionInfo(
                name="CMSAuthEnvelopedDataGenerator",
                type=TypeDefinitionType.CLASS,
                definition="public class CMSAuthEnvelopedDataGenerator",
                definition_line=26,
                file_path="/src/bc-java/pkix/src/main/java/org/bouncycastle/cms/CMSAuthEnvelopedDataGenerator.java",
            ),
        ),
    ],
)
@pytest.mark.integration
def test_get_type_definitions(
    bc_oss_fuzz_task: ChallengeTask,
    bc_oss_fuzz_cq: CodeQuery,
    type_name,
    file_path,
    fuzzy,
    type_definition_info,
):
    """Test that we can get type defs"""
    common_test_get_type_definitions(
        bc_oss_fuzz_task,
        bc_oss_fuzz_cq,
        type_name,
        file_path,
        fuzzy,
        type_definition_info,
    )


# From: https://github.com/bcgit/bc-java/blob/8b4326f24738ad6f6ab360089436a8a93c6a5424/mail/src/main/java/org/bouncycastle/mail/smime/SMIMEAuthEnvelopedGenerator.java#L41
@pytest.mark.parametrize(
    "type_name,file_path,fuzzy,type_usage_infos,num_type_usages",
    [
        (
            "CMSAuthEnvelopedDataGenerator",
            "/src/bc-java/pkix/src/main/java/org/bouncycastle/cms/CMSAuthEnvelopedDataGenerator.java",
            False,
            [
                TestTypeUsageInfo(
                    file_path="/src/bc-java/mail/src/main/java/org/bouncycastle/mail/smime/SMIMEAuthEnvelopedGenerator.java",
                    line_number=41,
                ),
            ],
            6,
        ),
    ],
)
@pytest.mark.skip(
    reason="Skipping type usage test for now. Class is directly imported and used."
)
@pytest.mark.integration
def test_get_type_usages(
    bc_oss_fuzz_task: ChallengeTask,
    bc_oss_fuzz_cq: CodeQuery,
    type_name,
    file_path,
    fuzzy,
    type_usage_infos,
    num_type_usages,
):
    """Test that we can get type usages"""
    common_test_get_type_usages(
        bc_oss_fuzz_task,
        bc_oss_fuzz_cq,
        type_name,
        file_path,
        fuzzy,
        type_usage_infos,
        num_type_usages,
    )
