import tempfile
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

import pytest
from langchain_core.messages import AIMessage
from redis import Redis

from buttercup.common.challenge_task import ChallengeTask
from buttercup.common.project_yaml import ProjectYaml
from buttercup.program_model.codequery import CodeQueryPersistent
from buttercup.program_model.utils.common import Function, FunctionBody
from buttercup.seed_gen.find_harness import HarnessInfo
from buttercup.seed_gen.seed_explore import SeedExploreTask, SeedExploreState
from buttercup.seed_gen.task import BaseTaskState, CodeSnippet


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
def seed_explore_task(mock_challenge_task, mock_codequery, mock_project_yaml, mock_redis):
    """Create a SeedExploreTask for testing."""
    return SeedExploreTask(
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
def mock_target_function():
    """Mock target function for testing."""
    body = FunctionBody(body="int target_function(int x) {\n    return x * 2;\n}")
    return Function(
        name="target_function",
        file_path=Path("/test/target.c"),
        line_number=10,
        bodies=[body],
    )


@pytest.fixture
def mock_code_snippet():
    """Mock CodeSnippet for testing."""
    return CodeSnippet(
        file_path=Path("/test/target.c"),
        code="int target_function(int x) {\n    return x * 2;\n}",
    )


@pytest.fixture
def temp_output_dir():
    """Create a temporary output directory for testing."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        yield Path(tmp_dir)


class TestSeedExploreTask:
    """Test cases for SeedExploreTask."""

    def test_init(self, seed_explore_task, mock_challenge_task, mock_codequery, mock_project_yaml, mock_redis):
        """Test task initialization."""
        assert seed_explore_task.package_name == "test_package"
        assert seed_explore_task.harness_name == "test_harness"
        assert seed_explore_task.challenge_task == mock_challenge_task
        assert seed_explore_task.codequery == mock_codequery
        assert seed_explore_task.project_yaml == mock_project_yaml
        assert seed_explore_task.redis == mock_redis

    def test_constants(self, seed_explore_task):
        """Test task constants."""
        assert seed_explore_task.SEED_EXPLORE_SEED_COUNT == 8
        assert seed_explore_task.MAX_CONTEXT_ITERATIONS == 4
        assert seed_explore_task.TARGET_FUNCTION_FUZZY_THRESHOLD == 50

    def test_get_context_generates_proper_command(self, seed_explore_task, mock_harness_info, mock_code_snippet, temp_output_dir):
        """Test _get_context generates proper command with mocked LLM calls."""
        # Create test state
        state = SeedExploreState(
            harness=mock_harness_info,
            target_function=mock_code_snippet,
            task=seed_explore_task,
            output_dir=temp_output_dir,
        )
        
        # Mock the LLM response
        mock_llm_response = AIMessage(content="mock tool calls", tool_calls=[])
        
        with patch.object(seed_explore_task, 'llm_with_tools') as mock_llm:
            mock_llm.invoke.return_value = mock_llm_response
            
            result = seed_explore_task._get_context(state)
            
            # Verify the command structure
            assert result.update["messages"] == [mock_llm_response]
            assert result.update["context_iteration"] == 1
            
            # Verify LLM was called with proper prompt
            mock_llm.invoke.assert_called_once()
            call_args = mock_llm.invoke.call_args[0][0]
            assert len(call_args) >= 2  # System and user messages

    def test_generate_seeds_creates_proper_command(self, seed_explore_task, mock_harness_info, mock_code_snippet, temp_output_dir):
        """Test _generate_seeds creates proper command with mocked LLM calls."""
        # Create test state with retrieved context
        state = SeedExploreState(
            harness=mock_harness_info,
            target_function=mock_code_snippet,
            task=seed_explore_task,
            output_dir=temp_output_dir,
        )
        
        # Mock the generated functions
        mock_generated_functions = "def test_seed_1():\n    return b'test_data_1'\n\ndef test_seed_2():\n    return b'test_data_2'"
        
        with patch.object(seed_explore_task, '_generate_python_funcs_base', return_value=mock_generated_functions):
            result = seed_explore_task._generate_seeds(state)
            
            # Verify the command structure
            assert result.update["generated_functions"] == mock_generated_functions
            
            # Verify the prompt variables passed to LLM
            seed_explore_task._generate_python_funcs_base.assert_called_once()
            call_args = seed_explore_task._generate_python_funcs_base.call_args
            prompt_vars = call_args[0][2]  # Third argument should be prompt_vars
            assert prompt_vars["count"] == SeedExploreTask.SEED_EXPLORE_SEED_COUNT
            assert prompt_vars["harness"] == str(mock_harness_info)
            assert prompt_vars["target_function"] == str(mock_code_snippet)

    def test_generate_seeds_workflow_execution(self, seed_explore_task, mock_harness_info, mock_code_snippet, temp_output_dir):
        """Test that generate_seeds executes the workflow properly."""
        # Mock the workflow and LLM
        mock_workflow = Mock()
        mock_compiled_workflow = Mock()
        mock_workflow.compile.return_value = mock_compiled_workflow
        mock_compiled_workflow.with_config.return_value = mock_compiled_workflow
        
        with patch.object(seed_explore_task, '_build_workflow', return_value=mock_workflow):
            with patch('buttercup.seed_gen.seed_explore.get_langfuse_callbacks', return_value=[]):
                with patch('buttercup.seed_gen.seed_explore.trace') as mock_trace:
                    mock_span = Mock()
                    mock_trace.get_tracer.return_value.start_as_current_span.return_value.__enter__.return_value = mock_span
                    
                    seed_explore_task.generate_seeds(mock_harness_info, mock_code_snippet, temp_output_dir)
                    
                    # Verify workflow was built and invoked
                    mock_workflow.compile.assert_called_once()
                    mock_compiled_workflow.with_config.assert_called_once()
                    mock_compiled_workflow.invoke.assert_called_once()
                    
                    # Verify the state passed to invoke
                    invoke_args = mock_compiled_workflow.invoke.call_args[0][0]
                    assert invoke_args.harness == mock_harness_info
                    assert invoke_args.target_function == mock_code_snippet
                    assert invoke_args.output_dir == temp_output_dir

    def test_clean_func_name(self, seed_explore_task):
        """Test function name cleaning."""
        # Test OSS_FUZZ_ prefix removal
        assert seed_explore_task.clean_func_name("OSS_FUZZ_target_function") == "target_function"
        
        # Test file path prefix removal
        assert seed_explore_task.clean_func_name("target.c:target_function") == "target_function"
        
        # Test normal function name
        assert seed_explore_task.clean_func_name("target_function") == "target_function"

    def test_get_function_def_success(self, seed_explore_task, mock_target_function):
        """Test successful function definition retrieval."""
        with patch.object(seed_explore_task, '_do_get_function_def', return_value=mock_target_function):
            result = seed_explore_task.get_function_def("target_function", [Path("/test/target.c")])
            assert result == mock_target_function

    def test_get_function_def_failure(self, seed_explore_task):
        """Test function definition retrieval failure."""
        with patch.object(seed_explore_task, '_do_get_function_def', return_value=None):
            result = seed_explore_task.get_function_def("nonexistent_function", [Path("/test/target.c")])
            assert result is None

    def test_do_task_success(self, seed_explore_task, mock_harness_info, mock_target_function, temp_output_dir):
        """Test successful do_task execution."""
        with patch('buttercup.seed_gen.find_harness.get_harness_source', return_value=mock_harness_info):
            with patch.object(seed_explore_task, 'get_function_def', return_value=mock_target_function):
                with patch.object(seed_explore_task, 'generate_seeds') as mock_generate_seeds:
                    seed_explore_task.do_task("target_function", [Path("/test/target.c")], temp_output_dir)
                    
                    mock_generate_seeds.assert_called_once()
                    # Check that the function snippet is created correctly
                    call_args = mock_generate_seeds.call_args[0]
                    assert call_args[0] == mock_harness_info  # harness
                    assert call_args[1].file_path == mock_target_function.file_path
                    assert call_args[1].code == mock_target_function.bodies[0].body
                    assert call_args[2] == temp_output_dir

    def test_do_task_no_harness(self, seed_explore_task, temp_output_dir):
        """Test do_task when no harness is found."""
        with patch('buttercup.seed_gen.find_harness.get_harness_source', return_value=None):
            with patch.object(seed_explore_task, 'generate_seeds') as mock_generate_seeds:
                seed_explore_task.do_task("target_function", [Path("/test/target.c")], temp_output_dir)
                
                # Should not call generate_seeds if no harness
                mock_generate_seeds.assert_not_called()

    def test_do_task_no_function_def(self, seed_explore_task, mock_harness_info, temp_output_dir):
        """Test do_task when no function definition is found."""
        with patch('buttercup.seed_gen.find_harness.get_harness_source', return_value=mock_harness_info):
            with patch.object(seed_explore_task, 'get_function_def', return_value=None):
                with patch.object(seed_explore_task, 'generate_seeds') as mock_generate_seeds:
                    with patch('buttercup.seed_gen.seed_explore.logger') as mock_logger:
                        seed_explore_task.do_task("nonexistent_function", [Path("/test/target.c")], temp_output_dir)
                        
                        # Should log error and not call generate_seeds
                        mock_logger.error.assert_called_once()
                        mock_generate_seeds.assert_not_called()

    def test_do_task_exception_handling(self, seed_explore_task, mock_harness_info, mock_target_function, temp_output_dir):
        """Test do_task exception handling."""
        with patch('buttercup.seed_gen.find_harness.get_harness_source', return_value=mock_harness_info):
            with patch.object(seed_explore_task, 'get_function_def', return_value=mock_target_function):
                with patch.object(seed_explore_task, 'generate_seeds', side_effect=Exception("Test error")):
                    with patch('buttercup.seed_gen.seed_explore.logger') as mock_logger:
                        seed_explore_task.do_task("target_function", [Path("/test/target.c")], temp_output_dir)
                        
                        # Should log the exception
                        mock_logger.exception.assert_called_once()

    def test_seed_explore_state_creation(self, mock_harness_info, mock_code_snippet, seed_explore_task, temp_output_dir):
        """Test SeedExploreState creation and field access."""
        state = SeedExploreState(
            harness=mock_harness_info,
            target_function=mock_code_snippet,
            task=seed_explore_task,
            output_dir=temp_output_dir,
        )
        
        assert state.harness == mock_harness_info
        assert state.target_function == mock_code_snippet
        assert state.task == seed_explore_task
        assert state.output_dir == temp_output_dir

    def test_continue_context_retrieval(self, seed_explore_task, mock_harness_info, mock_code_snippet, temp_output_dir):
        """Test context retrieval continuation logic."""
        # Test when should continue (iteration < max)
        state = SeedExploreState(
            harness=mock_harness_info,
            target_function=mock_code_snippet,
            task=seed_explore_task,
            output_dir=temp_output_dir,
            context_iteration=2,
        )
        
        assert seed_explore_task._continue_context_retrieval(state) is True
        
        # Test when should stop (iteration >= max)
        state.context_iteration = 4
        assert seed_explore_task._continue_context_retrieval(state) is False

    def test_workflow_build_structure(self, seed_explore_task):
        """Test that workflow is built with correct structure."""
        workflow = seed_explore_task._build_workflow(SeedExploreState)
        
        # Check that workflow has the expected nodes
        assert "get_context" in workflow.nodes
        assert "tools" in workflow.nodes
        assert "generate_seeds" in workflow.nodes
        assert "execute_python_funcs" in workflow.nodes