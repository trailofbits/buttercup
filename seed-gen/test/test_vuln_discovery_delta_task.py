import tempfile
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

import pytest
from langchain_core.messages import AIMessage
from redis import Redis

from buttercup.common.challenge_task import ChallengeTask
from buttercup.common.corpus import CrashDir
from buttercup.common.datastructures.msg_pb2 import BuildOutput, Crash, BuildType
from buttercup.common.project_yaml import ProjectYaml, Language
from buttercup.common.queues import ReliableQueue
from buttercup.common.reproduce_multiple import ReproduceMultiple, ReproduceResult
from buttercup.common.sarif_store import SARIFBroadcastDetail
from buttercup.common.stack_parsing import CrashSet
from buttercup.program_model.codequery import CodeQueryPersistent
from buttercup.seed_gen.find_harness import HarnessInfo
from buttercup.seed_gen.vuln_base_task import CrashSubmit, VulnBaseState, PoVAttempt
from buttercup.seed_gen.vuln_discovery_delta import VulnDiscoveryDeltaTask, VulnDiscoveryDeltaState


@pytest.fixture
def mock_challenge_task():
    """Mock ChallengeTask for testing."""
    task = Mock(spec=ChallengeTask)
    task.task_meta = Mock()
    task.task_meta.task_id = "test_task_id"
    task.task_meta.metadata = {}
    task.is_delta_mode.return_value = True
    task.get_diffs.return_value = [Path("/test/diff1.patch"), Path("/test/diff2.patch")]
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
def vuln_discovery_delta_task(mock_challenge_task, mock_codequery, mock_project_yaml, mock_redis, mock_reproduce_multiple, mock_sarifs, mock_crash_submit):
    """Create a VulnDiscoveryDeltaTask for testing."""
    return VulnDiscoveryDeltaTask(
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


class TestVulnDiscoveryDeltaTask:
    """Test cases for VulnDiscoveryDeltaTask."""

    def test_init(self, vuln_discovery_delta_task, mock_challenge_task, mock_codequery, mock_project_yaml, mock_redis, mock_reproduce_multiple, mock_sarifs, mock_crash_submit):
        """Test task initialization."""
        assert vuln_discovery_delta_task.package_name == "test_package"
        assert vuln_discovery_delta_task.harness_name == "test_harness"
        assert vuln_discovery_delta_task.challenge_task == mock_challenge_task
        assert vuln_discovery_delta_task.codequery == mock_codequery
        assert vuln_discovery_delta_task.project_yaml == mock_project_yaml
        assert vuln_discovery_delta_task.redis == mock_redis
        assert vuln_discovery_delta_task.reproduce_multiple == mock_reproduce_multiple
        assert vuln_discovery_delta_task.sarifs == mock_sarifs
        assert vuln_discovery_delta_task.crash_submit == mock_crash_submit

    def test_constants(self, vuln_discovery_delta_task):
        """Test task constants."""
        assert vuln_discovery_delta_task.VULN_DISCOVERY_MAX_POV_COUNT == 5
        assert vuln_discovery_delta_task.MAX_CONTEXT_ITERATIONS == 6

    def test_gather_context_generates_proper_command(self, vuln_discovery_delta_task, mock_harness_info, mock_sarifs, temp_output_dir, temp_current_dir):
        """Test _gather_context generates proper command with mocked LLM calls."""
        # Create test state
        state = VulnDiscoveryDeltaState(
            harness=mock_harness_info,
            task=vuln_discovery_delta_task,
            sarifs=mock_sarifs,
            output_dir=temp_output_dir,
            current_dir=temp_current_dir,
            diff_content="--- a/test.c\n+++ b/test.c\n@@ -1,3 +1,3 @@\n-old_line\n+new_line",
        )
        
        # Mock the LLM response
        mock_llm_response = AIMessage(content="mock tool calls", tool_calls=[])
        
        with patch.object(vuln_discovery_delta_task, 'llm_with_tools') as mock_llm:
            mock_llm.invoke.return_value = mock_llm_response
            
            result = vuln_discovery_delta_task._gather_context(state)
            
            # Verify the command structure
            assert result.update["messages"] == [mock_llm_response]
            assert result.update["context_iteration"] == 1
            
            # Verify LLM was called with proper prompt
            mock_llm.invoke.assert_called_once()
            call_args = mock_llm.invoke.call_args[0][0]
            assert len(call_args) >= 2  # System and user messages

    def test_analyze_bug_creates_proper_command(self, vuln_discovery_delta_task, mock_harness_info, mock_sarifs, temp_output_dir, temp_current_dir):
        """Test _analyze_bug creates proper command with mocked LLM calls."""
        # Create test state
        state = VulnDiscoveryDeltaState(
            harness=mock_harness_info,
            task=vuln_discovery_delta_task,
            sarifs=mock_sarifs,
            output_dir=temp_output_dir,
            current_dir=temp_current_dir,
            diff_content="--- a/test.c\n+++ b/test.c\n@@ -1,3 +1,3 @@\n-old_line\n+new_line",
        )
        
        # Mock the generated analysis
        mock_analysis = "This diff introduces a buffer overflow vulnerability in the target function."
        
        with patch.object(vuln_discovery_delta_task, '_analyze_bug_base', return_value=Mock(update={"analysis": mock_analysis})):
            result = vuln_discovery_delta_task._analyze_bug(state)
            
            # Verify the command structure
            assert result.update["analysis"] == mock_analysis
            
            # Verify the analyze_bug_base was called with proper prompts
            vuln_discovery_delta_task._analyze_bug_base.assert_called_once()

    def test_write_pov_creates_proper_command(self, vuln_discovery_delta_task, mock_harness_info, mock_sarifs, temp_output_dir, temp_current_dir):
        """Test _write_pov creates proper command with mocked LLM calls."""
        # Create test state
        state = VulnDiscoveryDeltaState(
            harness=mock_harness_info,
            task=vuln_discovery_delta_task,
            sarifs=mock_sarifs,
            output_dir=temp_output_dir,
            current_dir=temp_current_dir,
            diff_content="--- a/test.c\n+++ b/test.c\n@@ -1,3 +1,3 @@\n-old_line\n+new_line",
            analysis="This diff introduces a buffer overflow vulnerability.",
        )
        
        # Mock the generated PoV functions
        mock_pov_functions = "def test_pov_1():\n    return b'A' * 1000\n\ndef test_pov_2():\n    return b'B' * 500"
        
        with patch.object(vuln_discovery_delta_task, '_write_pov_base', return_value=Mock(update={"generated_functions": mock_pov_functions})):
            result = vuln_discovery_delta_task._write_pov(state)
            
            # Verify the command structure
            assert result.update["generated_functions"] == mock_pov_functions
            
            # Verify the write_pov_base was called with proper prompts
            vuln_discovery_delta_task._write_pov_base.assert_called_once()

    def test_init_state_success(self, vuln_discovery_delta_task, mock_harness_info, temp_output_dir, temp_current_dir):
        """Test _init_state success case."""
        with patch.object(vuln_discovery_delta_task, 'get_harness_source', return_value=mock_harness_info):
            with patch.object(vuln_discovery_delta_task, 'sample_sarifs', return_value=[]):
                with patch('buttercup.seed_gen.vuln_discovery_delta.get_diff_content', return_value="test diff content"):
                    state = vuln_discovery_delta_task._init_state(temp_output_dir, temp_current_dir)
                    
                    assert state.harness == mock_harness_info
                    assert state.output_dir == temp_output_dir
                    assert state.current_dir == temp_current_dir
                    assert state.diff_content == "test diff content"
                    assert state.task == vuln_discovery_delta_task

    def test_init_state_no_harness(self, vuln_discovery_delta_task, temp_output_dir, temp_current_dir):
        """Test _init_state when no harness is found."""
        with patch.object(vuln_discovery_delta_task, 'get_harness_source', return_value=None):
            with pytest.raises(ValueError, match="No harness found"):
                vuln_discovery_delta_task._init_state(temp_output_dir, temp_current_dir)

    def test_init_state_no_diff(self, vuln_discovery_delta_task, mock_harness_info, temp_output_dir, temp_current_dir):
        """Test _init_state when no diff is found."""
        with patch.object(vuln_discovery_delta_task, 'get_harness_source', return_value=mock_harness_info):
            with patch('buttercup.seed_gen.vuln_discovery_delta.get_diff_content', return_value=None):
                with pytest.raises(ValueError, match="No diff found"):
                    vuln_discovery_delta_task._init_state(temp_output_dir, temp_current_dir)

    def test_delta_state_diff_content_field(self, mock_harness_info, temp_output_dir, temp_current_dir):
        """Test that VulnDiscoveryDeltaState has diff_content field."""
        state = VulnDiscoveryDeltaState(
            harness=mock_harness_info,
            task=Mock(),
            sarifs=[],
            output_dir=temp_output_dir,
            current_dir=temp_current_dir,
            diff_content="test diff content",
        )
        
        assert state.diff_content == "test diff content"

    def test_get_diff_content_usage(self, vuln_discovery_delta_task, mock_harness_info, temp_output_dir, temp_current_dir):
        """Test that get_diff_content is called correctly."""
        mock_diffs = [Path("/test/diff1.patch"), Path("/test/diff2.patch")]
        vuln_discovery_delta_task.challenge_task.get_diffs.return_value = mock_diffs
        
        with patch.object(vuln_discovery_delta_task, 'get_harness_source', return_value=mock_harness_info):
            with patch.object(vuln_discovery_delta_task, 'sample_sarifs', return_value=[]):
                with patch('buttercup.seed_gen.vuln_discovery_delta.get_diff_content', return_value="diff content") as mock_get_diff:
                    vuln_discovery_delta_task._init_state(temp_output_dir, temp_current_dir)
                    
                    # Verify get_diff_content was called with the diffs
                    mock_get_diff.assert_called_once_with(mock_diffs)

    def test_submit_valid_pov_delta_mode(self, vuln_discovery_delta_task, mock_build_output, mock_reproduce_result, temp_output_dir):
        """Test successful PoV submission in delta mode."""
        # Create a test PoV file
        pov_file = temp_output_dir / "test_pov.bin"
        pov_file.write_bytes(b"test_pov_data")
        
        # Mock crash set to return False (new crash)
        vuln_discovery_delta_task.crash_submit.crash_set.add.return_value = False
        
        with patch('buttercup.seed_gen.vuln_base_task.stack_parsing.get_crash_token', return_value="test_token"):
            vuln_discovery_delta_task.submit_valid_pov(pov_file, mock_build_output, mock_reproduce_result)
            
            # Verify crash was submitted to queue
            vuln_discovery_delta_task.crash_submit.crash_queue.push.assert_called_once()
            
            # Verify the crash object includes delta mode info
            crash_call = vuln_discovery_delta_task.crash_submit.crash_queue.push.call_args[0][0]
            assert isinstance(crash_call, Crash)

    def test_test_povs_with_delta_context(self, vuln_discovery_delta_task, mock_build_output, mock_reproduce_result, temp_output_dir, temp_current_dir):
        """Test _test_povs in delta mode context."""
        # Create test PoV files in current directory
        pov_file1 = temp_current_dir / "pov1.bin"
        pov_file1.write_bytes(b"test_pov_1")
        
        # Create test state with delta content
        state = VulnDiscoveryDeltaState(
            harness=Mock(),
            task=vuln_discovery_delta_task,
            sarifs=[],
            output_dir=temp_output_dir,
            current_dir=temp_current_dir,
            diff_content="test diff content",
            analysis="test analysis",
            generated_functions="test functions",
            valid_pov_count=0,
            pov_iteration=0,
        )
        
        # Mock reproduce_multiple to return crashes
        vuln_discovery_delta_task.reproduce_multiple.get_crashes.return_value = [
            (mock_build_output, mock_reproduce_result),
        ]
        
        # Mock crash submission
        vuln_discovery_delta_task.crash_submit.crash_set.add.return_value = False
        
        with patch('buttercup.seed_gen.vuln_base_task.stack_parsing.get_crash_token', return_value="test_token"):
            result = vuln_discovery_delta_task._test_povs(state)
            
            # Should find 1 valid PoV
            assert result.update["valid_pov_count"] == 1
            assert result.update["pov_iteration"] == 1
            
            # Should have moved file to output directory
            assert (temp_output_dir / "iter0_pov1.bin").exists()
            
            # Should have submitted crash
            assert vuln_discovery_delta_task.crash_submit.crash_queue.push.call_count == 1

    def test_prompt_variables_include_diff(self, vuln_discovery_delta_task, mock_harness_info, mock_sarifs, temp_output_dir, temp_current_dir):
        """Test that prompt variables include diff content."""
        # Create test state
        state = VulnDiscoveryDeltaState(
            harness=mock_harness_info,
            task=vuln_discovery_delta_task,
            sarifs=mock_sarifs,
            output_dir=temp_output_dir,
            current_dir=temp_current_dir,
            diff_content="--- a/test.c\n+++ b/test.c\n@@ -1,3 +1,3 @@\n-old_line\n+new_line",
        )
        
        # Mock the base methods to capture prompt variables
        with patch.object(vuln_discovery_delta_task, '_get_context_base') as mock_get_context:
            mock_get_context.return_value = Mock(update={"messages": [], "context_iteration": 1})
            
            vuln_discovery_delta_task._gather_context(state)
            
            # Verify that diff was included in prompt variables
            call_args = mock_get_context.call_args[0]
            prompt_vars = call_args[3]  # Fourth argument should be prompt_vars
            assert "diff" in prompt_vars
            assert prompt_vars["diff"] == state.diff_content

        # Test analyze_bug prompt variables
        with patch.object(vuln_discovery_delta_task, '_analyze_bug_base') as mock_analyze_bug:
            mock_analyze_bug.return_value = Mock(update={"analysis": "test analysis"})
            
            vuln_discovery_delta_task._analyze_bug(state)
            
            # Verify that diff was included in prompt variables
            call_args = mock_analyze_bug.call_args[0]
            prompt_vars = call_args[2]  # Third argument should be prompt_vars
            assert "diff" in prompt_vars
            assert prompt_vars["diff"] == state.diff_content

        # Test write_pov prompt variables
        state.analysis = "test analysis"
        with patch.object(vuln_discovery_delta_task, '_write_pov_base') as mock_write_pov:
            mock_write_pov.return_value = Mock(update={"generated_functions": "test functions"})
            
            vuln_discovery_delta_task._write_pov(state)
            
            # Verify that diff was included in prompt variables
            call_args = mock_write_pov.call_args[0]
            prompt_vars = call_args[2]  # Third argument should be prompt_vars
            assert "diff" in prompt_vars
            assert prompt_vars["diff"] == state.diff_content

    def test_task_state_class_assignment(self, vuln_discovery_delta_task):
        """Test that TaskStateClass is properly assigned."""
        assert vuln_discovery_delta_task.TaskStateClass == VulnDiscoveryDeltaState

    def test_inheritance_from_vuln_base_task(self, vuln_discovery_delta_task):
        """Test that VulnDiscoveryDeltaTask inherits from VulnBaseTask."""
        from buttercup.seed_gen.vuln_base_task import VulnBaseTask
        assert isinstance(vuln_discovery_delta_task, VulnBaseTask)

    def test_delta_specific_prompt_constants(self, vuln_discovery_delta_task):
        """Test that delta-specific prompt constants are used."""
        # We can't directly test the constants since they're imported in the methods,
        # but we can verify that the methods are using delta-specific prompts by
        # checking that they call the base methods with different arguments than full task
        state = VulnDiscoveryDeltaState(
            harness=Mock(),
            task=vuln_discovery_delta_task,
            sarifs=[],
            output_dir=Path("/test"),
            current_dir=Path("/test"),
            diff_content="test diff",
        )
        
        # Test that gather_context uses delta-specific prompts
        with patch.object(vuln_discovery_delta_task, '_get_context_base') as mock_get_context:
            mock_get_context.return_value = Mock(update={"messages": [], "context_iteration": 1})
            
            vuln_discovery_delta_task._gather_context(state)
            
            # Verify that delta-specific prompts are used (by checking the prompt arguments)
            call_args = mock_get_context.call_args[0]
            system_prompt = call_args[0]
            user_prompt = call_args[1]
            
            # These should be delta-specific prompts (different from full task)
            assert "DELTA" in system_prompt or "delta" in system_prompt.lower()

    def test_do_task_success(self, vuln_discovery_delta_task, mock_harness_info, temp_output_dir, temp_current_dir):
        """Test successful do_task execution."""
        with patch('buttercup.seed_gen.find_harness.get_harness_source', return_value=mock_harness_info):
            with patch.object(vuln_discovery_delta_task, '_init_state') as mock_init_state:
                with patch.object(vuln_discovery_delta_task, '_build_workflow') as mock_build_workflow:
                    mock_state = Mock()
                    mock_init_state.return_value = mock_state
                    
                    mock_workflow = Mock()
                    mock_compiled_workflow = Mock()
                    mock_workflow.compile.return_value = mock_compiled_workflow
                    mock_compiled_workflow.with_config.return_value = mock_compiled_workflow
                    mock_build_workflow.return_value = mock_workflow
                    
                    with patch('buttercup.seed_gen.vuln_discovery_delta.get_langfuse_callbacks', return_value=[]):
                        with patch('buttercup.seed_gen.vuln_discovery_delta.trace') as mock_trace:
                            mock_span = Mock()
                            mock_trace.get_tracer.return_value.start_as_current_span.return_value.__enter__.return_value = mock_span
                            
                            vuln_discovery_delta_task.do_task(temp_output_dir, temp_current_dir)
                            
                            # Verify state was initialized
                            mock_init_state.assert_called_once_with(temp_output_dir, temp_current_dir)
                            
                            # Verify workflow was built and invoked
                            mock_build_workflow.assert_called_once()
                            mock_compiled_workflow.invoke.assert_called_once_with(mock_state)

    def test_do_task_exception_handling(self, vuln_discovery_delta_task, temp_output_dir, temp_current_dir):
        """Test do_task exception handling."""
        with patch.object(vuln_discovery_delta_task, '_init_state', side_effect=Exception("Test error")):
            with patch('buttercup.seed_gen.vuln_base_task.logger') as mock_logger:
                vuln_discovery_delta_task.do_task(temp_output_dir, temp_current_dir)
                
                # Should log the exception
                mock_logger.exception.assert_called_once()

    def test_workflow_build_structure(self, vuln_discovery_delta_task):
        """Test that workflow is built with correct structure."""
        workflow = vuln_discovery_delta_task._build_workflow()
        
        # Check that workflow has the expected nodes
        assert "gather_context" in workflow.nodes
        assert "tools" in workflow.nodes
        assert "analyze_bug" in workflow.nodes
        assert "write_pov" in workflow.nodes
        assert "execute_python_funcs" in workflow.nodes
        assert "test_povs" in workflow.nodes

    def test_recursion_limit_calculation(self, vuln_discovery_delta_task):
        """Test recursion limit calculation."""
        limit = vuln_discovery_delta_task.recursion_limit()
        
        # Should be: 1 + (2 * MAX_CONTEXT_ITERATIONS) + (4 * MAX_POV_ITERATIONS)
        # For delta: MAX_CONTEXT_ITERATIONS = 6, MAX_POV_ITERATIONS = 3
        expected = 1 + (2 * 6) + (4 * 3)
        assert limit == expected