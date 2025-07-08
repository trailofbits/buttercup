import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from langchain_core.messages import AIMessage
from redis import Redis

from buttercup.common.challenge_task import ChallengeTask
from buttercup.common.corpus import CrashDir
from buttercup.common.datastructures.msg_pb2 import BuildOutput
from buttercup.common.project_yaml import Language, ProjectYaml
from buttercup.common.queues import ReliableQueue
from buttercup.common.reproduce_multiple import ReproduceMultiple, ReproduceResult
from buttercup.common.sarif_store import SARIFBroadcastDetail
from buttercup.common.stack_parsing import CrashSet
from buttercup.program_model.codequery import CodeQueryPersistent
from buttercup.seed_gen.find_harness import HarnessInfo
from buttercup.seed_gen.vuln_base_task import CrashSubmit, PoVAttempt, VulnBaseState
from buttercup.seed_gen.vuln_discovery_full import VulnDiscoveryFullTask


@pytest.fixture
def mock_challenge_task():
    """Mock ChallengeTask for testing."""
    task = Mock(spec=ChallengeTask)
    task.task_meta = Mock()
    task.task_meta.task_id = "test_task_id"
    task.task_meta.metadata = {}
    task.is_delta_mode.return_value = False
    return task


@pytest.fixture
def mock_codequery():
    """Mock CodeQueryPersistent for testing."""
    return Mock(spec=CodeQueryPersistent)


@pytest.fixture
def mock_project_yaml():
    """Mock ProjectYaml for testing."""
    project_yaml = Mock(spec=ProjectYaml)
    project_yaml.unified_language = Language.C
    return project_yaml


@pytest.fixture
def mock_redis():
    """Mock Redis for testing."""
    return Mock(spec=Redis)


@pytest.fixture
def mock_reproduce_multiple():
    """Mock ReproduceMultiple for testing."""
    return Mock(spec=ReproduceMultiple)


@pytest.fixture
def mock_sarifs():
    """Mock SARIFBroadcastDetail list for testing."""
    sarif = Mock(spec=SARIFBroadcastDetail)
    sarif.sarif = {"tool": {"driver": {"name": "test_tool"}}}
    return [sarif]


@pytest.fixture
def mock_crash_queue():
    """Mock crash queue for testing."""
    return Mock(spec=ReliableQueue)


@pytest.fixture
def mock_crash_set():
    """Mock crash set for testing."""
    return Mock(spec=CrashSet)


@pytest.fixture
def mock_crash_dir():
    """Mock crash directory for testing."""
    return Mock(spec=CrashDir)


@pytest.fixture
def mock_crash_submit(mock_crash_queue, mock_crash_set, mock_crash_dir):
    """Mock CrashSubmit for testing."""
    return CrashSubmit(
        crash_queue=mock_crash_queue,
        crash_set=mock_crash_set,
        crash_dir=mock_crash_dir,
        max_pov_size=1024,
    )


@pytest.fixture
def vuln_discovery_full_task(
    mock_challenge_task,
    mock_codequery,
    mock_project_yaml,
    mock_redis,
    mock_reproduce_multiple,
    mock_sarifs,
    mock_crash_submit,
):
    """Create a VulnDiscoveryFullTask for testing."""
    return VulnDiscoveryFullTask(
        package_name="test_package",
        harness_name="test_harness",
        challenge_task=mock_challenge_task,
        codequery=mock_codequery,
        project_yaml=mock_project_yaml,
        redis=mock_redis,
        reproduce_multiple=mock_reproduce_multiple,
        sarifs=mock_sarifs,
        crash_submit=mock_crash_submit,
    )


@pytest.fixture
def mock_harness_info():
    """Mock HarnessInfo for testing."""
    return HarnessInfo(
        harness_name="test_harness",
        code="void test_harness(const uint8_t* data, size_t size) { /* test code */ }",
        file_path=Path("/test/harness.c"),
    )


@pytest.fixture
def temp_output_dir():
    """Create a temporary output directory for testing."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        yield Path(tmp_dir)


@pytest.fixture
def temp_current_dir():
    """Create a temporary current directory for testing."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        yield Path(tmp_dir)


@pytest.fixture
def mock_build_output():
    """Mock BuildOutput for testing."""
    build = Mock(spec=BuildOutput)
    build.sanitizer = "address"
    build.task_dir = "/test/task_dir"
    return build


@pytest.fixture
def mock_reproduce_result():
    """Mock ReproduceResult for testing."""
    result = Mock(spec=ReproduceResult)
    result.did_crash.return_value = True
    result.stacktrace.return_value = "test_stacktrace"
    result.command_result = Mock()
    result.command_result.output = "test_output"
    result.command_result.error = "test_error"
    return result


class TestVulnDiscoveryFullTask:
    """Test cases for VulnDiscoveryFullTask."""

    def test_init(
        self,
        vuln_discovery_full_task,
        mock_challenge_task,
        mock_codequery,
        mock_project_yaml,
        mock_redis,
        mock_reproduce_multiple,
        mock_sarifs,
        mock_crash_submit,
    ):
        """Test task initialization."""
        assert vuln_discovery_full_task.package_name == "test_package"
        assert vuln_discovery_full_task.harness_name == "test_harness"
        assert vuln_discovery_full_task.challenge_task == mock_challenge_task
        assert vuln_discovery_full_task.codequery == mock_codequery
        assert vuln_discovery_full_task.project_yaml == mock_project_yaml
        assert vuln_discovery_full_task.redis == mock_redis
        assert vuln_discovery_full_task.reproduce_multiple == mock_reproduce_multiple
        assert vuln_discovery_full_task.sarifs == mock_sarifs
        assert vuln_discovery_full_task.crash_submit == mock_crash_submit

    def test_constants(self, vuln_discovery_full_task):
        """Test task constants."""
        assert vuln_discovery_full_task.VULN_DISCOVERY_MAX_POV_COUNT == 5
        assert vuln_discovery_full_task.MAX_CONTEXT_ITERATIONS == 8

    def test_gather_context_generates_proper_command(
        self,
        vuln_discovery_full_task,
        mock_harness_info,
        mock_sarifs,
        temp_output_dir,
        temp_current_dir,
    ):
        """Test _gather_context generates proper command with mocked LLM calls."""
        # Create test state
        state = VulnBaseState(
            harness=mock_harness_info,
            task=vuln_discovery_full_task,
            sarifs=mock_sarifs,
            output_dir=temp_output_dir,
            current_dir=temp_current_dir,
        )

        # Mock the LLM response
        mock_llm_response = AIMessage(content="mock tool calls", tool_calls=[])

        with patch.object(vuln_discovery_full_task, "llm_with_tools") as mock_llm:
            mock_llm.invoke.return_value = mock_llm_response

            result = vuln_discovery_full_task._gather_context(state)

            # Verify the command structure
            assert result.update["messages"] == [mock_llm_response]
            assert result.update["context_iteration"] == 1

            # Verify LLM was called with proper prompt
            mock_llm.invoke.assert_called_once()
            call_args = mock_llm.invoke.call_args[0][0]
            assert len(call_args) >= 2  # System and user messages

    def test_analyze_bug_creates_proper_command(
        self,
        vuln_discovery_full_task,
        mock_harness_info,
        mock_sarifs,
        temp_output_dir,
        temp_current_dir,
    ):
        """Test _analyze_bug creates proper command with mocked LLM calls."""
        # Create test state
        state = VulnBaseState(
            harness=mock_harness_info,
            task=vuln_discovery_full_task,
            sarifs=mock_sarifs,
            output_dir=temp_output_dir,
            current_dir=temp_current_dir,
        )

        # Mock the generated analysis
        mock_analysis = "This is a buffer overflow vulnerability in the target function."

        with patch.object(
            vuln_discovery_full_task,
            "_analyze_bug_base",
            return_value=Mock(update={"analysis": mock_analysis}),
        ):
            result = vuln_discovery_full_task._analyze_bug(state)

            # Verify the command structure
            assert result.update["analysis"] == mock_analysis

            # Verify the analyze_bug_base was called with proper prompts
            vuln_discovery_full_task._analyze_bug_base.assert_called_once()

    def test_write_pov_creates_proper_command(
        self,
        vuln_discovery_full_task,
        mock_harness_info,
        mock_sarifs,
        temp_output_dir,
        temp_current_dir,
    ):
        """Test _write_pov creates proper command with mocked LLM calls."""
        # Create test state
        state = VulnBaseState(
            harness=mock_harness_info,
            task=vuln_discovery_full_task,
            sarifs=mock_sarifs,
            output_dir=temp_output_dir,
            current_dir=temp_current_dir,
            analysis="This is a buffer overflow vulnerability.",
        )

        # Mock the generated PoV functions
        mock_pov_functions = (
            "def test_pov_1():\n    return b'A' * 1000\n\ndef test_pov_2():\n    return b'B' * 500"
        )

        with patch.object(
            vuln_discovery_full_task,
            "_write_pov_base",
            return_value=Mock(update={"generated_functions": mock_pov_functions}),
        ):
            result = vuln_discovery_full_task._write_pov(state)

            # Verify the command structure
            assert result.update["generated_functions"] == mock_pov_functions

            # Verify the write_pov_base was called with proper prompts
            vuln_discovery_full_task._write_pov_base.assert_called_once()

    def test_init_state_success(
        self, vuln_discovery_full_task, mock_harness_info, temp_output_dir, temp_current_dir
    ):
        """Test _init_state success case."""
        with patch.object(
            vuln_discovery_full_task, "get_harness_source", return_value=mock_harness_info
        ):
            with patch.object(vuln_discovery_full_task, "sample_sarifs", return_value=[]):
                state = vuln_discovery_full_task._init_state(temp_output_dir, temp_current_dir)

                assert state.harness == mock_harness_info
                assert state.output_dir == temp_output_dir
                assert state.current_dir == temp_current_dir
                assert state.task == vuln_discovery_full_task

    def test_init_state_no_harness(
        self, vuln_discovery_full_task, temp_output_dir, temp_current_dir
    ):
        """Test _init_state when no harness is found."""
        with patch.object(vuln_discovery_full_task, "get_harness_source", return_value=None):
            with pytest.raises(ValueError, match="No harness found"):
                vuln_discovery_full_task._init_state(temp_output_dir, temp_current_dir)

    def test_sample_sarifs_with_probability(self, vuln_discovery_full_task, mock_sarifs):
        """Test sample_sarifs with different probabilities."""
        # Test when probability hits (should return sarifs)
        with patch("buttercup.seed_gen.vuln_base_task.random.random", return_value=0.3):
            result = vuln_discovery_full_task.sample_sarifs()
            assert result == mock_sarifs

        # Test when probability misses (should return empty list)
        with patch("buttercup.seed_gen.vuln_base_task.random.random", return_value=0.7):
            result = vuln_discovery_full_task.sample_sarifs()
            assert result == []

    def test_get_pov_examples_c_language(self, vuln_discovery_full_task):
        """Test get_pov_examples for C language."""
        vuln_discovery_full_task.project_yaml.unified_language = Language.C

        result = vuln_discovery_full_task.get_pov_examples()

        # Should return C PoV examples
        assert "libfuzzer" in result or "C" in result

    def test_get_pov_examples_java_language(self, vuln_discovery_full_task):
        """Test get_pov_examples for Java language."""
        vuln_discovery_full_task.project_yaml.unified_language = Language.JAVA

        result = vuln_discovery_full_task.get_pov_examples()

        # Should return Java PoV examples
        assert "jazzer" in result or "Java" in result

    def test_get_cwe_list_c_language(self, vuln_discovery_full_task):
        """Test get_cwe_list for C language."""
        vuln_discovery_full_task.project_yaml.unified_language = Language.C

        result = vuln_discovery_full_task.get_cwe_list()

        # Should include C-specific CWEs
        assert "CWE-" in result

    def test_get_cwe_list_java_language(self, vuln_discovery_full_task):
        """Test get_cwe_list for Java language."""
        vuln_discovery_full_task.project_yaml.unified_language = Language.JAVA

        result = vuln_discovery_full_task.get_cwe_list()

        # Should include Java-specific CWEs
        assert "CWE-" in result

    def test_submit_valid_pov_success(
        self, vuln_discovery_full_task, mock_build_output, mock_reproduce_result, temp_output_dir
    ):
        """Test successful PoV submission."""
        # Create a test PoV file
        pov_file = temp_output_dir / "test_pov.bin"
        pov_file.write_bytes(b"test_pov_data")

        # Mock crash set to return False (new crash)
        vuln_discovery_full_task.crash_submit.crash_set.add.return_value = False

        with patch(
            "buttercup.seed_gen.vuln_base_task.stack_parsing.get_crash_token",
            return_value="test_token",
        ):
            vuln_discovery_full_task.submit_valid_pov(
                pov_file, mock_build_output, mock_reproduce_result
            )

            # Verify crash was submitted to queue
            vuln_discovery_full_task.crash_submit.crash_queue.push.assert_called_once()

            # Verify crash set was checked
            vuln_discovery_full_task.crash_submit.crash_set.add.assert_called_once()

            # Verify file was copied to crash dir
            vuln_discovery_full_task.crash_submit.crash_dir.copy_file.assert_called_once()

    def test_submit_valid_pov_already_in_set(
        self, vuln_discovery_full_task, mock_build_output, mock_reproduce_result, temp_output_dir
    ):
        """Test PoV submission when crash is already in set."""
        # Create a test PoV file
        pov_file = temp_output_dir / "test_pov.bin"
        pov_file.write_bytes(b"test_pov_data")

        # Mock crash set to return True (already exists)
        vuln_discovery_full_task.crash_submit.crash_set.add.return_value = True

        with patch(
            "buttercup.seed_gen.vuln_base_task.stack_parsing.get_crash_token",
            return_value="test_token",
        ):
            vuln_discovery_full_task.submit_valid_pov(
                pov_file, mock_build_output, mock_reproduce_result
            )

            # Verify crash was NOT submitted to queue
            vuln_discovery_full_task.crash_submit.crash_queue.push.assert_not_called()

    def test_submit_valid_pov_no_crash_submit(
        self, vuln_discovery_full_task, mock_build_output, mock_reproduce_result, temp_output_dir
    ):
        """Test PoV submission when crash_submit is None."""
        # Remove crash_submit
        vuln_discovery_full_task.crash_submit = None

        # Create a test PoV file
        pov_file = temp_output_dir / "test_pov.bin"
        pov_file.write_bytes(b"test_pov_data")

        with patch("buttercup.seed_gen.vuln_base_task.logger") as mock_logger:
            vuln_discovery_full_task.submit_valid_pov(
                pov_file, mock_build_output, mock_reproduce_result
            )

            # Should log error about missing crash submission
            mock_logger.error.assert_called_once()

    def test_submit_valid_pov_no_crash(
        self, vuln_discovery_full_task, mock_build_output, temp_output_dir
    ):
        """Test PoV submission when result didn't crash."""
        # Create a test PoV file
        pov_file = temp_output_dir / "test_pov.bin"
        pov_file.write_bytes(b"test_pov_data")

        # Mock result to not crash
        mock_result = Mock()
        mock_result.did_crash.return_value = False

        with patch("buttercup.seed_gen.vuln_base_task.logger") as mock_logger:
            vuln_discovery_full_task.submit_valid_pov(pov_file, mock_build_output, mock_result)

            # Should log error about invalid PoV
            mock_logger.error.assert_called_once()

            # Should not submit to queue
            vuln_discovery_full_task.crash_submit.crash_queue.push.assert_not_called()

    def test_submit_valid_pov_size_limit(
        self, vuln_discovery_full_task, mock_build_output, mock_reproduce_result, temp_output_dir
    ):
        """Test PoV submission when file exceeds size limit."""
        # Create a test PoV file larger than limit
        pov_file = temp_output_dir / "test_pov.bin"
        pov_file.write_bytes(b"x" * 2000)  # Larger than max_pov_size=1024

        with patch("buttercup.seed_gen.vuln_base_task.logger") as mock_logger:
            vuln_discovery_full_task.submit_valid_pov(
                pov_file, mock_build_output, mock_reproduce_result
            )

            # Should log warning about size limit
            mock_logger.warning.assert_called_once()

            # Should not submit to queue
            vuln_discovery_full_task.crash_submit.crash_queue.push.assert_not_called()

    def test_test_povs_with_valid_crashes(
        self,
        vuln_discovery_full_task,
        mock_build_output,
        mock_reproduce_result,
        temp_output_dir,
        temp_current_dir,
    ):
        """Test _test_povs with valid crashes."""
        # Create test PoV files in current directory
        pov_file1 = temp_current_dir / "pov1.bin"
        pov_file1.write_bytes(b"test_pov_1")
        pov_file2 = temp_current_dir / "pov2.bin"
        pov_file2.write_bytes(b"test_pov_2")

        # Create test state
        state = VulnBaseState(
            harness=Mock(),
            task=vuln_discovery_full_task,
            sarifs=[],
            output_dir=temp_output_dir,
            current_dir=temp_current_dir,
            analysis="test analysis",
            generated_functions="test functions",
            valid_pov_count=0,
            pov_iteration=0,
        )

        # Mock reproduce_multiple to return crashes
        vuln_discovery_full_task.reproduce_multiple.get_crashes.return_value = [
            (mock_build_output, mock_reproduce_result),
            (mock_build_output, mock_reproduce_result),
        ]

        # Mock crash submission
        vuln_discovery_full_task.crash_submit.crash_set.add.return_value = False

        with patch(
            "buttercup.seed_gen.vuln_base_task.stack_parsing.get_crash_token",
            return_value="test_token",
        ):
            result = vuln_discovery_full_task._test_povs(state)

            # Should find 2 valid PoVs (one for each file)
            assert result.update["valid_pov_count"] == 2
            assert result.update["pov_iteration"] == 1

            # Should have moved files to output directory
            assert (temp_output_dir / "iter0_pov1.bin").exists()
            assert (temp_output_dir / "iter0_pov2.bin").exists()

            # Should have submitted crashes
            assert vuln_discovery_full_task.crash_submit.crash_queue.push.call_count == 2

    def test_continue_pov_write_logic(
        self, vuln_discovery_full_task, temp_output_dir, temp_current_dir
    ):
        """Test _continue_pov_write continuation logic."""
        # Create test state with no valid PoVs and low iteration count
        state = VulnBaseState(
            harness=Mock(),
            task=vuln_discovery_full_task,
            sarifs=[],
            output_dir=temp_output_dir,
            current_dir=temp_current_dir,
            valid_pov_count=0,
            pov_iteration=1,
        )

        # Should continue (no valid PoVs and under max iterations)
        assert vuln_discovery_full_task._continue_pov_write(state) is True

        # Should not continue if valid PoVs found
        state.valid_pov_count = 1
        assert vuln_discovery_full_task._continue_pov_write(state) is False

        # Should not continue if max iterations reached
        state.valid_pov_count = 0
        state.pov_iteration = 3
        assert vuln_discovery_full_task._continue_pov_write(state) is False

    def test_pov_attempt_formatting(self):
        """Test PoVAttempt string formatting."""
        attempt = PoVAttempt(
            analysis="This is a buffer overflow",
            pov_functions="def test_pov():\n    return b'A' * 100",
        )

        result = str(attempt)
        assert "<test_case_attempt>" in result
        assert "<analysis>" in result
        assert "This is a buffer overflow" in result
        assert "<test_cases>" in result
        assert "def test_pov():" in result

    def test_vuln_base_state_format_methods(self, mock_sarifs):
        """Test VulnBaseState formatting methods."""
        state = VulnBaseState(
            harness=Mock(),
            task=Mock(),
            sarifs=mock_sarifs,
            output_dir=Path("/test"),
            current_dir=Path("/test"),
        )

        # Test SARIF formatting
        sarif_hints = state.format_sarif_hints()
        assert "test_tool" in sarif_hints

        # Test PoV attempts formatting
        attempt = PoVAttempt(analysis="test", pov_functions="test")
        state.pov_attempts = [attempt]
        pov_attempts = state.format_pov_attempts()
        assert "test_case_attempt" in pov_attempts

    def test_do_task_success(
        self, vuln_discovery_full_task, mock_harness_info, temp_output_dir, temp_current_dir
    ):
        """Test successful do_task execution."""
        with patch(
            "buttercup.seed_gen.find_harness.get_harness_source", return_value=mock_harness_info
        ):
            with patch.object(vuln_discovery_full_task, "_init_state") as mock_init_state:
                with patch.object(
                    vuln_discovery_full_task, "_build_workflow"
                ) as mock_build_workflow:
                    mock_state = Mock()
                    mock_init_state.return_value = mock_state

                    mock_workflow = Mock()
                    mock_compiled_workflow = Mock()
                    mock_workflow.compile.return_value = mock_compiled_workflow
                    mock_compiled_workflow.with_config.return_value = mock_compiled_workflow
                    mock_build_workflow.return_value = mock_workflow

                    with patch(
                        "buttercup.seed_gen.vuln_discovery_full.get_langfuse_callbacks",
                        return_value=[],
                    ):
                        with patch("buttercup.seed_gen.vuln_discovery_full.trace") as mock_trace:
                            mock_span = Mock()
                            tracer = mock_trace.get_tracer.return_value
                            span_ctx = tracer.start_as_current_span.return_value
                            enter_ctx = span_ctx.__enter__
                            enter_ctx.return_value = mock_span

                            vuln_discovery_full_task.do_task(temp_output_dir, temp_current_dir)

                            # Verify state was initialized
                            mock_init_state.assert_called_once_with(
                                temp_output_dir, temp_current_dir
                            )

                            # Verify workflow was built and invoked
                            mock_build_workflow.assert_called_once()
                            mock_compiled_workflow.invoke.assert_called_once_with(mock_state)

    def test_do_task_exception_handling(
        self, vuln_discovery_full_task, temp_output_dir, temp_current_dir
    ):
        """Test do_task exception handling."""
        with patch.object(
            vuln_discovery_full_task, "_init_state", side_effect=Exception("Test error")
        ):
            with patch("buttercup.seed_gen.vuln_discovery_full.logger") as mock_logger:
                vuln_discovery_full_task.do_task(temp_output_dir, temp_current_dir)

                # Should log the exception
                mock_logger.exception.assert_called_once()

    def test_recursion_limit_calculation(self, vuln_discovery_full_task):
        """Test recursion limit calculation."""
        limit = vuln_discovery_full_task.recursion_limit()

        # Should be: 1 + (2 * MAX_CONTEXT_ITERATIONS) + (4 * MAX_POV_ITERATIONS)
        expected = 1 + (2 * 8) + (4 * 3)
        assert limit == expected

    def test_workflow_build_structure(self, vuln_discovery_full_task):
        """Test that workflow is built with correct structure."""
        workflow = vuln_discovery_full_task._build_workflow()

        # Check that workflow has the expected nodes
        assert "gather_context" in workflow.nodes
        assert "tools" in workflow.nodes
        assert "analyze_bug" in workflow.nodes
        assert "write_pov" in workflow.nodes
        assert "execute_python_funcs" in workflow.nodes
        assert "test_povs" in workflow.nodes
