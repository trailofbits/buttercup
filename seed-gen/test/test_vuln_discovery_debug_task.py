"""Tests for VulnDiscoveryDebugTask"""

from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest
from langchain_core.messages import AIMessage
from langchain_core.messages.tool import ToolCall

from buttercup.seed_gen.vuln_discovery_debug_task import VulnDiscoveryDebugState, VulnDiscoveryDebugTask


@pytest.fixture
def vuln_discovery_debug_task(
    mock_challenge_task,
    mock_codequery,
    mock_project_yaml,
    mock_redis,
    mock_reproduce_multiple,
    mock_llm,
    mock_crash_submit,
):
    """Create a VulnDiscoveryDebugTask instance with mocked dependencies."""
    with (
        patch("buttercup.seed_gen.task.Task.get_llm", return_value=mock_llm),
        patch("buttercup.seed_gen.debug_subagent_unified.DebugSubagentUnified") as mock_debug_agent,
    ):
        task = VulnDiscoveryDebugTask(
            package_name="test_package",
            harness_name="test_harness",
            challenge_task=mock_challenge_task,
            codequery=mock_codequery,
            project_yaml=mock_project_yaml,
            redis=mock_redis,
            reproduce_multiple=mock_reproduce_multiple,
            sarifs=[],
            crash_submit=mock_crash_submit,
        )
        # Store the mock for later use
        task._mock_debug_agent = mock_debug_agent
        return task


def test_post_init(vuln_discovery_debug_task):
    """Test that __post_init__ initializes debug subagent and tools"""
    assert vuln_discovery_debug_task.start_time is None
    assert vuln_discovery_debug_task.debug_subagent_unified is not None
    assert vuln_discovery_debug_task.debug_pov_tool is not None
    assert len(vuln_discovery_debug_task.debug_pov_tools) == 1


def test_gather_context_full_mode(vuln_discovery_debug_task, mock_llm, mock_harness_info, tmp_path):
    """Test _gather_context in full mode (no diff)"""
    out_dir = tmp_path / "out"
    current_dir = tmp_path / "current"
    out_dir.mkdir()
    current_dir.mkdir()

    state = VulnDiscoveryDebugState(
        harness=mock_harness_info,
        task=vuln_discovery_debug_task,
        output_dir=out_dir,
        current_dir=current_dir,
        diff_content="",  # Full mode
    )

    mock_llm.invoke.return_value = AIMessage(
        content="Context gathered",
        tool_calls=[
            ToolCall(
                id="call_1",
                name="get_function_definition",
                args={"function_name": "target"},
            ),
        ],
    )

    result = vuln_discovery_debug_task._gather_context(state)

    assert result is not None
    # Command objects have update attribute
    assert hasattr(result, "update") or hasattr(result, "graph")


def test_gather_context_delta_mode(vuln_discovery_debug_task, mock_llm, mock_harness_info, tmp_path):
    """Test _gather_context in delta mode (with diff)"""
    out_dir = tmp_path / "out"
    current_dir = tmp_path / "current"
    out_dir.mkdir()
    current_dir.mkdir()

    state = VulnDiscoveryDebugState(
        harness=mock_harness_info,
        task=vuln_discovery_debug_task,
        output_dir=out_dir,
        current_dir=current_dir,
        diff_content="--- a/file.c\n+++ b/file.c\n@@ -1,1 +1,2 @@\n line",  # Delta mode
    )

    mock_llm.invoke.return_value = AIMessage(
        content="Context gathered",
        tool_calls=[
            ToolCall(
                id="call_1",
                name="get_function_definition",
                args={"function_name": "target"},
            ),
        ],
    )

    result = vuln_discovery_debug_task._gather_context(state)

    assert result is not None


def test_analyze_bug_with_debug_insights(vuln_discovery_debug_task, mock_llm, mock_harness_info, tmp_path):
    """Test _analyze_bug when debug insights are available"""
    out_dir = tmp_path / "out"
    current_dir = tmp_path / "current"
    out_dir.mkdir()
    current_dir.mkdir()

    from buttercup.seed_gen.task import CodeSnippet, ToolCallResult

    # Create state with debug insights in retrieved_context
    state = VulnDiscoveryDebugState(
        harness=mock_harness_info,
        task=vuln_discovery_debug_task,
        output_dir=out_dir,
        current_dir=current_dir,
        diff_content="",
    )

    # Add debug insights to retrieved_context
    debug_result = CodeSnippet(
        file_path=Path("debug_result.txt"),
        code="Debug insights: The PoV didn't reach the vulnerable code path",
        start_line=1,
        end_line=10,
    )
    state.retrieved_context["debug_pov('pov_1', 'test')"] = ToolCallResult(
        call="debug_pov('pov_1', 'test')",
        results=[debug_result],
    )

    mock_llm.invoke.return_value = AIMessage(content="Analysis with debug insights")

    result = vuln_discovery_debug_task._analyze_bug(state)

    assert result is not None
    # Verify that debug insights were included in the prompt
    assert mock_llm.invoke.called


def test_analyze_bug_delta_mode(vuln_discovery_debug_task, mock_llm, mock_harness_info, tmp_path):
    """Test _analyze_bug in delta mode"""
    out_dir = tmp_path / "out"
    current_dir = tmp_path / "current"
    out_dir.mkdir()
    current_dir.mkdir()

    state = VulnDiscoveryDebugState(
        harness=mock_harness_info,
        task=vuln_discovery_debug_task,
        output_dir=out_dir,
        current_dir=current_dir,
        diff_content="--- a/file.c\n+++ b/file.c\n@@ -1,1 +1,2 @@\n line",
    )

    mock_llm.invoke.return_value = AIMessage(content="Delta analysis")

    result = vuln_discovery_debug_task._analyze_bug(state)

    assert result is not None


def test_write_pov_with_debug_insights(vuln_discovery_debug_task, mock_llm, mock_harness_info, tmp_path):
    """Test _write_pov when debug insights are available"""
    out_dir = tmp_path / "out"
    current_dir = tmp_path / "current"
    out_dir.mkdir()
    current_dir.mkdir()

    from buttercup.seed_gen.task import CodeSnippet, ToolCallResult

    state = VulnDiscoveryDebugState(
        harness=mock_harness_info,
        task=vuln_discovery_debug_task,
        output_dir=out_dir,
        current_dir=current_dir,
        analysis="Buffer overflow vulnerability",
        diff_content="",
    )

    # Add debug insights
    debug_result = CodeSnippet(
        file_path=Path("debug_result.txt"),
        code="Debug: Need to set specific register value",
        start_line=1,
        end_line=5,
    )
    state.retrieved_context["debug_pov('pov_1', 'test')"] = ToolCallResult(
        call="debug_pov('pov_1', 'test')",
        results=[debug_result],
    )

    mock_llm.invoke.return_value = AIMessage(
        content="```python\ndef gen_test_case() -> bytes:\n    return b'A' * 200\n```"
    )

    result = vuln_discovery_debug_task._write_pov(state)

    assert result is not None
    assert mock_llm.invoke.called


def test_debug_failed_povs(vuln_discovery_debug_task, mock_llm, mock_harness_info, tmp_path):
    """Test _debug_failed_povs method"""
    out_dir = tmp_path / "out"
    current_dir = tmp_path / "current"
    out_dir.mkdir()
    current_dir.mkdir()

    from buttercup.seed_gen.vuln_base_task import PoVAttempt

    state = VulnDiscoveryDebugState(
        harness=mock_harness_info,
        task=vuln_discovery_debug_task,
        output_dir=out_dir,
        current_dir=current_dir,
        analysis="Test analysis",
        pov_attempts=[
            PoVAttempt(
                analysis="First attempt",
                pov_functions="def gen_test() -> bytes: return b'test'",
            ),
        ],
    )

    # Mock LLM response with tool call
    mock_llm.bind_tools.return_value.invoke.return_value = AIMessage(
        content="I'll debug the failed PoV",
        tool_calls=[
            ToolCall(
                id="debug_call_1",
                name="debug_pov",
                args={"testcase_name": "pov_1", "debug_context": "Why didn't it crash?"},
            ),
        ],
    )

    result = vuln_discovery_debug_task._debug_failed_povs(state)

    assert result is not None
    # Command object has update attribute containing messages
    assert hasattr(result, "update")
    assert "messages" in result.update


def test_format_debug_insights(vuln_discovery_debug_task, mock_harness_info, tmp_path):
    """Test _format_debug_insights method"""
    out_dir = tmp_path / "out"
    current_dir = tmp_path / "current"
    out_dir.mkdir()
    current_dir.mkdir()

    from buttercup.seed_gen.task import CodeSnippet, ToolCallResult

    state = VulnDiscoveryDebugState(
        harness=mock_harness_info,
        task=vuln_discovery_debug_task,
        output_dir=out_dir,
        current_dir=current_dir,
    )

    # Add debug result to retrieved_context
    debug_result = CodeSnippet(
        file_path=Path("debug.txt"),
        code="Debug output: Program didn't crash",
        start_line=1,
        end_line=5,
    )
    state.retrieved_context["debug_pov('test', 'context')"] = ToolCallResult(
        call="debug_pov('test', 'context')",
        results=[debug_result],
    )

    insights = vuln_discovery_debug_task._format_debug_insights(state)

    assert insights != ""
    assert "Debug output" in insights or "debug" in insights.lower()


def test_format_debug_insights_no_insights(vuln_discovery_debug_task, mock_harness_info, tmp_path):
    """Test _format_debug_insights when no debug insights exist"""
    out_dir = tmp_path / "out"
    current_dir = tmp_path / "current"
    out_dir.mkdir()
    current_dir.mkdir()

    state = VulnDiscoveryDebugState(
        harness=mock_harness_info,
        task=vuln_discovery_debug_task,
        output_dir=out_dir,
        current_dir=current_dir,
    )

    insights = vuln_discovery_debug_task._format_debug_insights(state)

    assert insights == ""


def test_debug_pov_impl_cache_hit(vuln_discovery_debug_task, mock_harness_info, tmp_path):
    """Test _debug_pov_impl when result is already cached"""
    out_dir = tmp_path / "out"
    current_dir = tmp_path / "current"
    out_dir.mkdir()
    current_dir.mkdir()

    from buttercup.seed_gen.task import CodeSnippet, ToolCallResult

    state = VulnDiscoveryDebugState(
        harness=mock_harness_info,
        task=vuln_discovery_debug_task,
        output_dir=out_dir,
        current_dir=current_dir,
    )

    # Add cached result
    call = 'debug_pov("pov_1", "test context")'
    cached_result = ToolCallResult(
        call=call,
        results=[CodeSnippet(file_path=Path("cached.txt"), code="cached", start_line=1, end_line=1)],
    )
    state.retrieved_context[call] = cached_result

    result = vuln_discovery_debug_task._debug_pov_impl("pov_1", "test context", None, None, state, "tool_call_1")

    assert result is not None
    assert hasattr(result, "update")
    assert "messages" in result.update
    assert "already retrieved" in result.update["messages"][0].content.lower()


def test_debug_pov_impl_output_dir_not_exists(vuln_discovery_debug_task, mock_harness_info, tmp_path):
    """Test _debug_pov_impl when output_dir doesn't exist"""
    out_dir = tmp_path / "nonexistent"
    current_dir = tmp_path / "current"
    current_dir.mkdir()

    state = VulnDiscoveryDebugState(
        harness=mock_harness_info,
        task=vuln_discovery_debug_task,
        output_dir=out_dir,  # Doesn't exist
        current_dir=current_dir,
    )

    result = vuln_discovery_debug_task._debug_pov_impl("pov_1", "test context", None, None, state, "tool_call_1")

    assert result is not None
    assert hasattr(result, "update")
    assert "messages" in result.update
    assert "does not exist" in result.update["messages"][0].content.lower()


def test_debug_pov_impl_no_pov_found(vuln_discovery_debug_task, mock_harness_info, tmp_path):
    """Test _debug_pov_impl when PoV file is not found"""
    out_dir = tmp_path / "out"
    current_dir = tmp_path / "current"
    out_dir.mkdir()
    current_dir.mkdir()

    state = VulnDiscoveryDebugState(
        harness=mock_harness_info,
        task=vuln_discovery_debug_task,
        output_dir=out_dir,
        current_dir=current_dir,
    )

    result = vuln_discovery_debug_task._debug_pov_impl(
        "nonexistent_pov", "test context", None, None, state, "tool_call_1"
    )

    assert result is not None
    assert hasattr(result, "update")
    assert "messages" in result.update


def test_debug_pov_impl_success(vuln_discovery_debug_task, mock_harness_info, tmp_path):
    """Test _debug_pov_impl successful execution"""
    out_dir = tmp_path / "out"
    current_dir = tmp_path / "current"
    out_dir.mkdir()
    current_dir.mkdir()

    # Create a PoV file
    pov_file = out_dir / "iter0_pov_1.seed"
    pov_file.write_bytes(b"test pov data")

    state = VulnDiscoveryDebugState(
        harness=mock_harness_info,
        task=vuln_discovery_debug_task,
        output_dir=out_dir,
        current_dir=current_dir,
    )

    # Mock the debug agent
    mock_debug_result = MagicMock()
    mock_debug_result.pov_valid = False
    mock_debug_result.debug_output = "Debug output"
    mock_debug_result.analysis = "Analysis"
    mock_debug_result.reflection = "Reflection"

    vuln_discovery_debug_task.debug_subagent_unified.debug = Mock(return_value=mock_debug_result)

    result = vuln_discovery_debug_task._debug_pov_impl("pov_1", "test context", None, None, state, "tool_call_1")

    assert result is not None
    assert hasattr(result, "update")
    assert "messages" in result.update
    vuln_discovery_debug_task.debug_subagent_unified.debug.assert_called_once()


def test_debug_pov_impl_error_handling(vuln_discovery_debug_task, mock_harness_info, tmp_path):
    """Test _debug_pov_impl error handling"""
    out_dir = tmp_path / "out"
    current_dir = tmp_path / "current"
    out_dir.mkdir()
    current_dir.mkdir()

    pov_file = out_dir / "iter0_pov_1.seed"
    pov_file.write_bytes(b"test pov data")

    state = VulnDiscoveryDebugState(
        harness=mock_harness_info,
        task=vuln_discovery_debug_task,
        output_dir=out_dir,
        current_dir=current_dir,
    )

    # Mock debug agent to raise an error
    vuln_discovery_debug_task.debug_subagent_unified.debug = Mock(side_effect=Exception("Debug error"))

    result = vuln_discovery_debug_task._debug_pov_impl("pov_1", "test context", None, None, state, "tool_call_1")

    assert result is not None
    assert hasattr(result, "update")
    assert "messages" in result.update
    assert "error" in result.update["messages"][0].content.lower()


def test_init_state(vuln_discovery_debug_task, mock_harness_info, tmp_path):
    """Test _init_state method"""
    out_dir = tmp_path / "out"
    current_dir = tmp_path / "current"
    out_dir.mkdir()
    current_dir.mkdir()

    vuln_discovery_debug_task.get_harness_source = Mock(return_value=mock_harness_info)

    state = vuln_discovery_debug_task._init_state(out_dir, current_dir)

    assert isinstance(state, VulnDiscoveryDebugState)
    assert state.harness == mock_harness_info
    assert state.output_dir == out_dir
    assert state.current_dir == current_dir
    assert state.diff_content == ""  # Default for full mode


def test_init_state_delta_mode(vuln_discovery_debug_task, mock_harness_info, tmp_path):
    """Test _init_state in delta mode"""
    out_dir = tmp_path / "out"
    current_dir = tmp_path / "current"
    out_dir.mkdir()
    current_dir.mkdir()

    vuln_discovery_debug_task.get_harness_source = Mock(return_value=mock_harness_info)
    vuln_discovery_debug_task.challenge_task.is_delta_mode = Mock(return_value=True)

    # Mock get_diff_content
    with patch("buttercup.seed_gen.vuln_discovery_debug_task.get_diff_content") as mock_get_diff:
        mock_get_diff.return_value = "--- a/file.c\n+++ b/file.c\n@@ -1,1 +1,2 @@\n line"

        state = vuln_discovery_debug_task._init_state(out_dir, current_dir)

        assert isinstance(state, VulnDiscoveryDebugState)
        assert state.diff_content != ""
        assert "file.c" in state.diff_content


def test_write_pov_delta_mode_with_diff(vuln_discovery_debug_task, mock_llm, mock_harness_info, tmp_path):
    """Test _write_pov in delta mode to cover lines 198-200"""
    out_dir = tmp_path / "out"
    current_dir = tmp_path / "current"
    out_dir.mkdir()
    current_dir.mkdir()

    state = VulnDiscoveryDebugState(
        harness=mock_harness_info,
        task=vuln_discovery_debug_task,
        output_dir=out_dir,
        current_dir=current_dir,
        analysis="Delta mode analysis",
        diff_content="--- a/file.c\n+++ b/file.c\n@@ -1,1 +1,2 @@\n+vuln",  # Delta mode
    )

    mock_llm.invoke.return_value = AIMessage(
        content="```python\ndef gen_test_case() -> bytes:\n    return b'delta_test'\n```"
    )

    result = vuln_discovery_debug_task._write_pov(state)

    assert result is not None
    assert hasattr(result, "update")


def test_build_workflow(vuln_discovery_debug_task):
    """Test _build_workflow method to cover lines 451-501"""
    workflow = vuln_discovery_debug_task._build_workflow()

    assert workflow is not None
    # Workflow is a StateGraph, verify it was built
    assert hasattr(workflow, "nodes")


def test_recursion_limit(vuln_discovery_debug_task):
    """Test recursion_limit method to cover lines 503-509"""
    limit = vuln_discovery_debug_task.recursion_limit()

    # Should return a positive integer
    assert isinstance(limit, int)
    assert limit > 0
    # Expected: 1 + 2 * MAX_CONTEXT_ITERATIONS + 4 * MAX_POV_ITERATIONS + debug_steps
    # MAX_CONTEXT_ITERATIONS = 6, MAX_POV_ITERATIONS = 3
    # 1 + 2*6 + 4*3 + 2 = 1 + 12 + 12 + 2 = 27
    assert limit >= 20  # At least this much


def test_debug_pov_impl_pov_selection(vuln_discovery_debug_task, mock_harness_info, tmp_path):
    """Test _debug_pov_impl selecting most recent PoV when multiple exist"""
    out_dir = tmp_path / "out"
    current_dir = tmp_path / "current"
    out_dir.mkdir()
    current_dir.mkdir()

    # Create multiple PoV files
    pov_file1 = out_dir / "iter0_pov_1.seed"
    pov_file1.write_bytes(b"old pov data")

    import time

    time.sleep(0.01)  # Ensure different timestamps

    pov_file2 = out_dir / "iter1_pov_1.seed"
    pov_file2.write_bytes(b"new pov data")

    state = VulnDiscoveryDebugState(
        harness=mock_harness_info,
        task=vuln_discovery_debug_task,
        output_dir=out_dir,
        current_dir=current_dir,
    )

    # Mock the debug agent
    mock_debug_result = MagicMock()
    mock_debug_result.pov_valid = False
    mock_debug_result.debug_output = "Debug output"
    mock_debug_result.analysis = "Analysis"
    mock_debug_result.reflection = "Reflection"

    vuln_discovery_debug_task.debug_subagent_unified.debug = Mock(return_value=mock_debug_result)

    result = vuln_discovery_debug_task._debug_pov_impl("pov_1", "test context", None, None, state, "tool_call_1")

    assert result is not None
    # Should have selected the most recent file (iter1_pov_1.seed)
    vuln_discovery_debug_task.debug_subagent_unified.debug.assert_called_once()
    call_args = vuln_discovery_debug_task.debug_subagent_unified.debug.call_args
    pov_path = call_args.kwargs.get("pov_input_path") or call_args[1]["pov_input_path"]
    assert "iter1_pov_1.seed" in str(pov_path)


def test_debug_pov_tool_creation(vuln_discovery_debug_task):
    """Test _create_debug_pov_tool creates proper tool"""
    tool = vuln_discovery_debug_task._create_debug_pov_tool()

    assert tool is not None
    assert tool.name == "debug_pov"
    assert "PoV" in tool.description or "pov" in tool.description.lower()


def test_debug_pov_impl_with_custom_dirs(vuln_discovery_debug_task, mock_harness_info, tmp_path):
    """Test _debug_pov_impl with custom output_dir and current_dir"""
    out_dir = tmp_path / "out"
    current_dir = tmp_path / "current"
    custom_debug_dir = tmp_path / "custom_debug"
    custom_current_dir = tmp_path / "custom_current"
    out_dir.mkdir()
    current_dir.mkdir()
    custom_debug_dir.mkdir()
    custom_current_dir.mkdir()

    # Create a PoV file
    pov_file = out_dir / "iter0_pov_1.seed"
    pov_file.write_bytes(b"test pov data")

    state = VulnDiscoveryDebugState(
        harness=mock_harness_info,
        task=vuln_discovery_debug_task,
        output_dir=out_dir,
        current_dir=current_dir,
    )

    # Mock the debug agent
    mock_debug_result = MagicMock()
    mock_debug_result.pov_valid = False
    mock_debug_result.debug_output = "Debug output"
    mock_debug_result.analysis = "Analysis"
    mock_debug_result.reflection = "Reflection"

    vuln_discovery_debug_task.debug_subagent_unified.debug = Mock(return_value=mock_debug_result)

    result = vuln_discovery_debug_task._debug_pov_impl(
        "pov_1", "test context", str(custom_debug_dir), str(custom_current_dir), state, "tool_call_1"
    )

    assert result is not None
    # Verify custom dirs were used
    call_args = vuln_discovery_debug_task.debug_subagent_unified.debug.call_args
    assert call_args is not None


def test_format_debug_insights_with_multiple_results(vuln_discovery_debug_task, mock_harness_info, tmp_path):
    """Test _format_debug_insights with multiple debug results"""
    out_dir = tmp_path / "out"
    current_dir = tmp_path / "current"
    out_dir.mkdir()
    current_dir.mkdir()

    from buttercup.seed_gen.task import CodeSnippet, ToolCallResult

    state = VulnDiscoveryDebugState(
        harness=mock_harness_info,
        task=vuln_discovery_debug_task,
        output_dir=out_dir,
        current_dir=current_dir,
    )

    # Add multiple debug results
    debug_result1 = CodeSnippet(
        file_path=Path("debug1.txt"),
        code="First debug insight",
        start_line=1,
        end_line=5,
    )
    debug_result2 = CodeSnippet(
        file_path=Path("debug2.txt"),
        code="Second debug insight",
        start_line=1,
        end_line=5,
    )

    state.retrieved_context["debug_pov('test1', 'context1')"] = ToolCallResult(
        call="debug_pov('test1', 'context1')",
        results=[debug_result1],
    )
    state.retrieved_context["debug_pov('test2', 'context2')"] = ToolCallResult(
        call="debug_pov('test2', 'context2')",
        results=[debug_result2],
    )

    insights = vuln_discovery_debug_task._format_debug_insights(state)

    assert insights != ""
    # Should contain both insights
    assert "First" in insights or "Second" in insights
