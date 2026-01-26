"""CodeQuery primitives testing"""

from pathlib import Path

import pytest
from buttercup.common.challenge_task import ChallengeTask

from buttercup.program_model.codequery import CodeQuery

from ..common import (
    TestCalleeInfo,
    TestFunctionInfo,
    TestTypeDefinitionInfo,
    TestTypeUsageInfo,
    TypeDefinitionType,
    common_test_get_callees,
    common_test_get_callers,
    common_test_get_functions,
    common_test_get_type_definitions,
    common_test_get_type_usages,
)


@pytest.mark.parametrize(
    "function_name,file_path,function_info",
    [
        (
            "getLogger",
            "/src/log4j-core/src/main/java/org/apache/logging/log4j/core/LoggerContext.java",
            TestFunctionInfo(
                num_bodies=2,
                body_excerpts=[
                    """return getLogger(name, DEFAULT_MESSAGE_FACTORY);""",
                    """return loggerRegistry.computeIfAbsent(name, effectiveMessageFactory, this::newInstance);""",
                ],
            ),
        ),
        (
            "addAppender",
            "/src/log4j-1.2-api/src/main/java/org/apache/log4j/Category.java",
            TestFunctionInfo(
                num_bodies=1,
                body_excerpts=[
                    """if (LogManager.isLog4jCorePresent()) {""",
                ],
            ),
        ),
    ],
)
@pytest.mark.skip(reason="Skipping for now, as the image build routine doesn't work with oss-fuzz-aixcc")
@pytest.mark.integration
def test_get_functions(
    log4j2_oss_fuzz_task: ChallengeTask,
    log4j2_oss_fuzz_cq: CodeQuery,
    function_name,
    file_path,
    function_info,
):
    """Test that we can get functions in challenge task code"""
    common_test_get_functions(log4j2_oss_fuzz_cq, function_name, file_path, function_info)


@pytest.mark.parametrize(
    "function_name,file_path,line_number,fuzzy,expected_callers,num_callers",
    [
        (
            "getLogger",
            "/src/log4j-core/src/main/java/org/apache/logging/log4j/core/LoggerContext.java",
            565,
            False,
            [],
            453,
        ),
        (
            "getLogger",
            "/src/log4j-api/src/main/java/org/apache/logging/log4j/LogManager.java",
            597,
            False,
            [],
            453,
        ),
    ],
)
@pytest.mark.skip(reason="Skipping for now, as the image build routine doesn't work with oss-fuzz-aixcc")
@pytest.mark.integration
def test_get_callers(
    log4j2_oss_fuzz_task: ChallengeTask,
    log4j2_oss_fuzz_cq: CodeQuery,
    function_name,
    file_path,
    line_number,
    fuzzy,
    expected_callers,
    num_callers,
):
    """Test that we can get function callers"""
    common_test_get_callers(
        log4j2_oss_fuzz_task,
        log4j2_oss_fuzz_cq,
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
        # TODO(Evan): Re-enable this test after fixing cscope issue which doesn't think getLogger is a function.
        #   (
        #       "getLogger",
        #       "/src/log4j-core/src/main/java/org/apache/logging/log4j/core/LoggerContext.java",
        #       565,
        #       False,
        #       [],
        #       6,
        #   ),
        (
            "getLogger",
            "/src/log4j-1.2-api/src/main/java/org/apache/log4j/bridge/LogEventAdapter.java",
            126,
            False,
            [],
            1,
        ),
        (
            "addAppender",
            "/src/log4j-1.2-api/src/main/java/org/apache/log4j/legacy/core/CategoryUtil.java",
            157,
            False,
            # TODO(Evan): There are more callees than this.
            [
                TestCalleeInfo(
                    name="asCore",
                    file_path="/src/log4j-1.2-api/src/main/java/org/apache/log4j/legacy/core/CategoryUtil.java",
                    start_line=39,
                ),
            ],
            1,
        ),
        #   # TODO(Evan): Figure out why this is failing. Probably because of the @Override?
        #   (
        #       "addAppender",
        #       "/src/log4j-1.2-api/src/main/java/org/apache/log4j/Category.java",
        #       194,
        #       False,
        #       [
        #           # NOTE(boyan): there should be a 6th callee here that is also addAppender
        #           # but called from another class. It is not caugth currently because
        #           # it's called from aai.addAppender where aai is a class field. We don't yet
        #           # support resolving the type of implicit class fields and thus don't get
        #           # this version of the callee.
        #           TestCalleeInfo(
        #               name="addAppender",
        #               file_path="/src/log4j-1.2-api/src/main/java/org/apache/log4j/legacy/core/CategoryUtil.java",
        #               start_line=157,
        #           ),
        #           TestCalleeInfo(
        #               name="adapt",
        #               file_path="/src/log4j-1.2-api/src/main/java/org/apache/log4j/bridge/AppenderAdapter.java",
        #               start_line=45,
        #           ),
        #           TestCalleeInfo(
        #               name="isLog4jCorePresent",
        #               file_path="/src/log4j-1.2-api/src/main/java/org/apache/log4j/LogManager.java",
        #               start_line=193,
        #           ),
        #       ],
        #       3,
        #   ),
    ],
)
@pytest.mark.skip(reason="Skipping for now, as the image build routine doesn't work with oss-fuzz-aixcc")
@pytest.mark.integration
def test_get_callees(
    log4j2_oss_fuzz_task: ChallengeTask,
    log4j2_oss_fuzz_cq: CodeQuery,
    function_name,
    file_path,
    line_number,
    fuzzy,
    expected_callees,
    num_callees,
):
    """Test that we can get function callees."""
    common_test_get_callees(
        log4j2_oss_fuzz_task,
        log4j2_oss_fuzz_cq,
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
            "LoggerContext",
            None,
            False,
            TestTypeDefinitionInfo(
                name="LoggerContext",
                type=TypeDefinitionType.CLASS,
                definition="public class LoggerContext extends AbstractLifeCycle",
                definition_line=71,
                file_path="/src/log4j-core/src/main/java/org/apache/logging/log4j/core/LoggerContext.java",
            ),
        ),
        (
            "NetUtils",
            "/src/log4j-core/src/main/java/org/apache/logging/log4j/core/util/NetUtils.java",
            False,
            TestTypeDefinitionInfo(
                name="NetUtils",
                type=TypeDefinitionType.CLASS,
                definition="public final class NetUtils {",
                definition_line=40,
                file_path="/src/log4j-core/src/main/java/org/apache/logging/log4j/core/util/NetUtils.java",
            ),
        ),
        (
            "LoggerRepository",
            "/src/log4j-1.2-api/src/main/java/org/apache/log4j/spi/LoggerRepository.java",
            False,
            TestTypeDefinitionInfo(
                name="LoggerRepository",
                type=TypeDefinitionType.CLASS,
                definition="public interface LoggerRepository {",
                definition_line=38,
                file_path="/src/log4j-1.2-api/src/main/java/org/apache/log4j/spi/LoggerRepository.java",
            ),
        ),
    ],
)
@pytest.mark.skip(reason="Skipping for now, as the image build routine doesn't work with oss-fuzz-aixcc")
@pytest.mark.integration
def test_get_type_definitions(
    log4j2_oss_fuzz_task: ChallengeTask,
    log4j2_oss_fuzz_cq: CodeQuery,
    type_name,
    file_path,
    fuzzy,
    type_definition_info,
):
    """Test that we can get type defs"""
    common_test_get_type_definitions(
        log4j2_oss_fuzz_task,
        log4j2_oss_fuzz_cq,
        type_name,
        file_path,
        fuzzy,
        type_definition_info,
    )


@pytest.mark.parametrize(
    "type_name,file_path,fuzzy,type_usage_infos,num_type_usages",
    [
        (
            "LoggerContext",
            None,
            False,
            [
                TestTypeUsageInfo(
                    file_path="/src/log4j-core/src/main/java/org/apache/logging/log4j/core/osgi/BundleContextSelector.java",
                    line_number=146,
                ),
            ],
            12,
        ),
    ],
)
@pytest.mark.skip(reason="Skipping for now, as the image build routine doesn't work with oss-fuzz-aixcc")
@pytest.mark.integration
def test_get_type_usages(
    log4j2_oss_fuzz_task: ChallengeTask,
    log4j2_oss_fuzz_cq: CodeQuery,
    type_name,
    file_path,
    fuzzy,
    type_usage_infos,
    num_type_usages,
):
    """Test that we can get type usages"""
    common_test_get_type_usages(
        log4j2_oss_fuzz_task,
        log4j2_oss_fuzz_cq,
        type_name,
        file_path,
        fuzzy,
        type_usage_infos,
        num_type_usages,
    )


@pytest.mark.skip(reason="Skipping for now, as the image build routine doesn't work with oss-fuzz-aixcc")
@pytest.mark.integration
def test_java_resolver(log4j2_oss_fuzz_task: ChallengeTask):
    codequery = CodeQuery(log4j2_oss_fuzz_task)
    resolver = codequery.imports_resolver

    # Simple expr with only one type (no dots)
    t = resolver.get_dotexpr_type(
        "NetUtils",
        Path("/src/log4j-core/src/main/java/org/apache/logging/log4j/core/LoggerContext.java"),
    )
    assert t is not None
    assert t.name == "NetUtils"
    assert t.file_path == Path("/src/log4j-core/src/main/java/org/apache/logging/log4j/core/util/NetUtils.java")

    t = resolver.get_dotexpr_type(
        "Category.aai",
        Path("/src/log4j-1.2-api/src/main/java/org/apache/log4j/bridge/LogEventAdapter.java"),
    )
    assert t is not None
    assert t.name == "AppenderAttachableImpl"
    assert t.file_path == Path("/src/log4j-1.2-api/src/main/java/org/apache/log4j/helpers/AppenderAttachableImpl.java")

    t = resolver.get_dotexpr_type(
        "Category.getDefaultHierarchy()",
        Path("/src/log4j-1.2-api/src/main/java/org/apache/log4j/bridge/LogEventAdapter.java"),
    )
    assert t is not None
    assert t.name == "LoggerRepository"
    assert t.file_path == Path("/src/log4j-1.2-api/src/main/java/org/apache/log4j/spi/LoggerRepository.java")

    t = resolver.get_dotexpr_type(
        "Category.getDefaultHierarchy().getLogger().getRootLogger()",
        Path("/src/log4j-1.2-api/src/main/java/org/apache/log4j/bridge/LogEventAdapter.java"),
    )
    assert t is not None
    assert t.name == "Logger"
    assert t.file_path == Path("/src/log4j-1.2-api/src/main/java/org/apache/log4j/Logger.java")

    t = resolver.get_dotexpr_type(
        "Category.getDefaultHierarchy().exists('test').getRootLogger()",
        Path("/src/log4j-1.2-api/src/main/java/org/apache/log4j/bridge/LogEventAdapter.java"),
    )
    assert t is not None
    assert t.name == "Logger"
    assert t.file_path == Path("/src/log4j-1.2-api/src/main/java/org/apache/log4j/Logger.java")

    t = resolver.get_dotexpr_type(
        "Category.getDefaultHierarchy().getThreshold().TRACE.toLevel(3)",
        Path("/src/log4j-1.2-api/src/main/java/org/apache/log4j/bridge/LogEventAdapter.java"),
    )
    assert t is not None
    assert t.name == "Level"
    assert t.file_path == Path("/src/log4j-1.2-api/src/main/java/org/apache/log4j/Level.java")
