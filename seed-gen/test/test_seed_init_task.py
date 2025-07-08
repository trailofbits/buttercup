import tempfile
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

import pytest
from langchain_core.messages import AIMessage
from redis import Redis

from buttercup.common.challenge_task import ChallengeTask
from buttercup.common.project_yaml import ProjectYaml
from buttercup.program_model.codequery import CodeQueryPersistent
from buttercup.seed_gen.find_harness import HarnessInfo
from buttercup.seed_gen.seed_init import SeedInitTask
from buttercup.seed_gen.task import BaseTaskState


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
    return Mock(spec=ProjectYaml)


@pytest.fixture
def mock_redis():
    """Mock Redis for testing."""
    return Mock(spec=Redis)


@pytest.fixture
def seed_init_task(mock_challenge_task, mock_codequery, mock_project_yaml, mock_redis):
    """Create a SeedInitTask for testing."""
    return SeedInitTask(
        package_name="test_package",
        harness_name="test_harness",
        challenge_task=mock_challenge_task,
        codequery=mock_codequery,
        project_yaml=mock_project_yaml,
        redis=mock_redis,
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


class TestSeedInitTask:
    """Test cases for SeedInitTask."""

    def test_init(self, seed_init_task, mock_challenge_task, mock_codequery, mock_project_yaml, mock_redis):
        """Test task initialization."""
        assert seed_init_task.package_name == "test_package"
        assert seed_init_task.harness_name == "test_harness"
        assert seed_init_task.challenge_task == mock_challenge_task
        assert seed_init_task.codequery == mock_codequery
        assert seed_init_task.project_yaml == mock_project_yaml
        assert seed_init_task.redis == mock_redis

    def test_get_harness_source(self, seed_init_task, mock_harness_info):
        """Test getting harness source."""
        with patch('buttercup.seed_gen.find_harness.get_harness_source', return_value=mock_harness_info) as mock_get_harness_source:
            result = seed_init_task.get_harness_source()
            
            assert result == mock_harness_info
            mock_get_harness_source.assert_called_once_with(
                seed_init_task.redis, seed_init_task.codequery, seed_init_task.harness_name
            )

    def test_get_harness_source_none(self, seed_init_task):
        """Test getting harness source when none is found."""
        with patch('buttercup.seed_gen.find_harness.get_harness_source', return_value=None):
            result = seed_init_task.get_harness_source()
            
            assert result is None

    def test_generate_seeds_context_call(self, seed_init_task, mock_harness_info, temp_output_dir):
        """Test that _get_context is called with proper parameters."""
        # Mock the workflow and LLM
        mock_workflow = Mock()
        mock_compiled_workflow = Mock()
        mock_workflow.compile.return_value = mock_compiled_workflow
        mock_compiled_workflow.with_config.return_value = mock_compiled_workflow
        
        with patch.object(seed_init_task, '_build_workflow', return_value=mock_workflow):
            with patch('buttercup.seed_gen.seed_init.get_langfuse_callbacks', return_value=[]):
                with patch('buttercup.seed_gen.seed_init.trace') as mock_trace:
                    mock_span = Mock()
                    mock_trace.get_tracer.return_value.start_as_current_span.return_value.__enter__.return_value = mock_span
                    
                    seed_init_task.generate_seeds(mock_harness_info, temp_output_dir)
                    
                    # Verify workflow was built and invoked
                    mock_workflow.compile.assert_called_once()
                    mock_compiled_workflow.with_config.assert_called_once()
                    mock_compiled_workflow.invoke.assert_called_once()
                    
                    # Verify the state passed to invoke
                    invoke_args = mock_compiled_workflow.invoke.call_args[0][0]
                    assert invoke_args.harness == mock_harness_info
                    assert invoke_args.output_dir == temp_output_dir

    def test_get_context_generates_proper_command(self, seed_init_task, mock_harness_info, temp_output_dir):
        """Test _get_context generates proper command with mocked LLM calls."""
        # Create test state
        state = BaseTaskState(
            harness=mock_harness_info,
            task=seed_init_task,
            output_dir=temp_output_dir,
        )
        
        # Mock the LLM response
        mock_llm_response = AIMessage(content="mock tool calls", tool_calls=[])
        
        with patch.object(seed_init_task, 'llm_with_tools') as mock_llm:
            mock_llm.invoke.return_value = mock_llm_response
            
            result = seed_init_task._get_context(state)
            
            # Verify the command structure
            assert result.update["messages"] == [mock_llm_response]
            assert result.update["context_iteration"] == 1
            
            # Verify LLM was called with proper prompt
            mock_llm.invoke.assert_called_once()
            call_args = mock_llm.invoke.call_args[0][0]
            assert len(call_args) >= 2  # System and user messages

    def test_generate_seeds_creates_proper_command(self, seed_init_task, mock_harness_info, temp_output_dir):
        """Test _generate_seeds creates proper command with mocked LLM calls."""
        # Create test state with retrieved context
        state = BaseTaskState(
            harness=mock_harness_info,
            task=seed_init_task,
            output_dir=temp_output_dir,
        )
        
        # Mock the generated functions
        mock_generated_functions = "def test_seed_1():\n    return b'test_data_1'\n\ndef test_seed_2():\n    return b'test_data_2'"
        
        with patch.object(seed_init_task, '_generate_python_funcs_base', return_value=mock_generated_functions):
            result = seed_init_task._generate_seeds(state)
            
            # Verify the command structure
            assert result.update["generated_functions"] == mock_generated_functions
            
            # Verify the prompt variables passed to LLM
            seed_init_task._generate_python_funcs_base.assert_called_once()
            call_args = seed_init_task._generate_python_funcs_base.call_args
            prompt_vars = call_args[0][2]  # Third argument should be prompt_vars
            assert prompt_vars["count"] == SeedInitTask.SEED_INIT_SEED_COUNT
            assert prompt_vars["harness"] == str(mock_harness_info)

    def test_do_task_success(self, seed_init_task, mock_harness_info, temp_output_dir):
        """Test successful do_task execution."""
        with patch('buttercup.seed_gen.find_harness.get_harness_source', return_value=mock_harness_info):
            with patch.object(seed_init_task, 'generate_seeds') as mock_generate_seeds:
                seed_init_task.do_task(temp_output_dir)
                
                mock_generate_seeds.assert_called_once_with(mock_harness_info, temp_output_dir)

    def test_do_task_no_harness(self, seed_init_task, temp_output_dir):
        """Test do_task when no harness is found."""
        with patch('buttercup.seed_gen.find_harness.get_harness_source', return_value=None):
            with patch.object(seed_init_task, 'generate_seeds') as mock_generate_seeds:
                seed_init_task.do_task(temp_output_dir)
                
                # Should not call generate_seeds if no harness
                mock_generate_seeds.assert_not_called()

    def test_do_task_exception_handling(self, seed_init_task, mock_harness_info, temp_output_dir):
        """Test do_task exception handling."""
        with patch('buttercup.seed_gen.find_harness.get_harness_source', return_value=mock_harness_info):
            with patch.object(seed_init_task, 'generate_seeds', side_effect=Exception("Test error")):
                with patch('buttercup.seed_gen.seed_init.logger') as mock_logger:
                    seed_init_task.do_task(temp_output_dir)
                    
                    # Should log the exception
                    mock_logger.exception.assert_called_once()

    def test_max_context_iterations_constant(self, seed_init_task):
        """Test MAX_CONTEXT_ITERATIONS constant."""
        assert seed_init_task.MAX_CONTEXT_ITERATIONS == 4

    def test_seed_count_constant(self, seed_init_task):
        """Test SEED_INIT_SEED_COUNT constant."""
        assert seed_init_task.SEED_INIT_SEED_COUNT == 8

    def test_continue_context_retrieval(self, seed_init_task, mock_harness_info, temp_output_dir):
        """Test context retrieval continuation logic."""
        # Test when should continue (iteration < max)
        state = BaseTaskState(
            harness=mock_harness_info,
            task=seed_init_task,
            output_dir=temp_output_dir,
            context_iteration=2,
        )
        
        assert seed_init_task._continue_context_retrieval(state) is True
        
        # Test when should stop (iteration >= max)
        state.context_iteration = 4
        assert seed_init_task._continue_context_retrieval(state) is False

    def test_workflow_build_structure(self, seed_init_task):
        """Test that workflow is built with correct structure."""
        workflow = seed_init_task._build_workflow(BaseTaskState)
        
        # Check that workflow has the expected nodes
        assert "get_context" in workflow.nodes
        assert "tools" in workflow.nodes
        assert "generate_seeds" in workflow.nodes
        assert "execute_python_funcs" in workflow.nodes