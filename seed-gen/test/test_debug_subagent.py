"""Tests for DebugSubagent"""

import os

if "PYTHON_WASM_BUILD_PATH" not in os.environ:
    os.environ["PYTHON_WASM_BUILD_PATH"] = "/tmp/dummy-python.wasm"

from unittest.mock import MagicMock, Mock, patch

import pytest
from langchain_core.messages import AIMessage
from langchain_core.messages.tool import ToolCall

from buttercup.common.challenge_task import CommandResult
from buttercup.common.datastructures.msg_pb2 import BuildOutput, BuildType
from buttercup.common.reproduce_multiple import ReproduceMultiple
from buttercup.seed_gen.debug_subagent import DebugResult, DebugSubagent, DebugTaskState
from test.conftest import (
    mock_challenge_task,
    mock_codequery,
    mock_project_yaml,
    mock_redis,
    mock_llm,
    mock_harness_info,
    mock_codequery_responses,
    mock_challenge_task_responses,
)


@pytest.fixture
def mock_task(mock_challenge_task, mock_codequery, mock_project_yaml, mock_redis, mock_llm):
    with patch("buttercup.seed_gen.task.Task.get_llm", return_value=mock_llm):
        from buttercup.seed_gen.seed_init import SeedInitTask

        return SeedInitTask(
            package_name="test_package",
            harness_name="test_harness",
            challenge_task=mock_challenge_task,
            codequery=mock_codequery,
            project_yaml=mock_project_yaml,
            redis=mock_redis,
        )


@pytest.fixture
def mock_reproduce_multiple(mock_task, tmp_path):
    build_output = BuildOutput()
    build_output.task_dir = str(mock_task.challenge_task.task_dir)
    build_output.build_type = BuildType.FUZZER
    build_output.engine = "libfuzzer"
    build_output.sanitizer = "address"

    reproduce_multiple = ReproduceMultiple(tmp_path, [build_output])

    with patch.object(reproduce_multiple, "open") as mock_open:
        mock_context = MagicMock()
        mock_context.builds_cache = [mock_task.challenge_task]
        mock_context.get_crashes = Mock(return_value=iter([]))
        mock_open.return_value.__enter__.return_value = mock_context
        mock_open.return_value.__exit__.return_value = None
        yield reproduce_multiple


@pytest.fixture
def debug_subagent(mock_task, mock_reproduce_multiple):
    return DebugSubagent(mock_task, mock_reproduce_multiple)


def test_debug_basic_workflow(
    debug_subagent,
    mock_task,
    mock_llm,
    mock_harness_info,
    mock_codequery_responses,
    mock_challenge_task_responses,
    tmp_path,
):
    """Test basic debug workflow (PoV not valid)."""
    pov_input_path = tmp_path / "pov_input.bin"
    pov_input_path.write_bytes(b"test input data")
    debug_context = "Check if the target_function is called with this input"

    with (
        patch("buttercup.common.llm.get_langfuse_callbacks", return_value=[]),
        patch("opentelemetry.trace.get_tracer") as mock_tracer,
        patch("buttercup.seed_gen.debug_subagent.set_crs_attributes") as _,
    ):
        mock_span = MagicMock()
        mock_tracer.return_value.start_as_current_span.return_value.__enter__.return_value = mock_span

        # Context gathering messages - just one iteration since _continue_context_retrieval returns False
        context_messages = [
            AIMessage(
                content="I'll gather context about the target function for debugging",
                tool_calls=[
                    ToolCall(
                        id="context_call_1",
                        name="get_function_definition",
                        args={"function_name": "target_function"},
                    ),
                ],
            ),
        ]

        # Debug workflow messages
        debug_messages = [
            AIMessage(content="Inspect target_function invocation and its args."),  # analyze_debug
            AIMessage(
                content=(
                    "```gdb\n"
                    "break target_function\n"
                    "run\n"
                    "bt\n"
                    "info args\n"
                    "continue\n"
                    "```"
                )
            ),  # write_debug_script
        ]

        # Mock LLM responses: context gathering + debug workflow
        mock_llm.invoke.side_effect = context_messages + debug_messages

        # Mock codequery tool calls
        mock_task.codequery.get_functions = Mock(return_value=mock_codequery_responses["get_functions"])
        mock_task.codequery.get_callers = Mock(return_value=mock_codequery_responses["get_callers"])
        mock_task.codequery.get_types = Mock(return_value=mock_codequery_responses["get_types"])

        # Stop context retrieval after first iteration
        mock_task._continue_context_retrieval = lambda state: False

        # GDB execution stub
        gdb_result = CommandResult(
            success=True,
            output=b"Breakpoint 1, target_function (...) at test.c:10\n#0 target_function\n",
            error=b"",
        )

        def mock_exec_docker_cmd(cmd, **kwargs):
            if isinstance(cmd, list) and cmd and cmd[0] == "gdb":
                return gdb_result
            return mock_challenge_task_responses["exec_docker_cmd"]

        mock_task.challenge_task.exec_docker_cmd = Mock(side_effect=mock_exec_docker_cmd)

        build_dir = tmp_path / "build" / "out" / "test_project"
        build_dir.mkdir(parents=True)
        mock_task.challenge_task.get_build_dir = Mock(return_value=build_dir)

        # Stop after first debug iteration (prevents needing extra LLM responses)
        original_continue_debug = debug_subagent._continue_debug

        def stop_after_first_iteration(state):
            if state.debug_iteration >= 1:
                return False
            return original_continue_debug(state)

        debug_subagent._continue_debug = stop_after_first_iteration

        result = debug_subagent.debug(
            harness=mock_harness_info,
            pov_input_path=pov_input_path,
            debug_context=debug_context,
            output_dir=tmp_path / "debug_output",
        )

        assert isinstance(result, DebugResult)
        assert result.pov_valid is False
        assert result.debug_script.strip() != ""
        assert result.debug_output.strip() != ""

        outdir = tmp_path / "debug_output"
        assert (outdir / "debug_script.gdb").exists()
        assert (outdir / "debug_output.txt").exists()
        assert (outdir / "pov_valid.txt").exists()


def test_debug_with_valid_pov(
    debug_subagent,
    mock_task,
    mock_llm,
    mock_harness_info,
    mock_codequery_responses,
    mock_challenge_task_responses,
    tmp_path,
):
    """Test debug workflow with valid PoV (causes crash)."""
    pov_input_path = tmp_path / "pov_input.bin"
    pov_input_path.write_bytes(b"crash input")
    debug_context = "Verify this PoV causes a crash"

    with (
        patch("buttercup.common.llm.get_langfuse_callbacks", return_value=[]),
        patch("opentelemetry.trace.get_tracer") as mock_tracer,
        patch("buttercup.seed_gen.debug_subagent.set_crs_attributes") as _,
    ):
        mock_span = MagicMock()
        mock_tracer.return_value.start_as_current_span.return_value.__enter__.return_value = mock_span

        # Context gathering messages - just one iteration since _continue_context_retrieval returns False
        context_messages = [
            AIMessage(
                content="I'll gather context about the crash",
                tool_calls=[
                    ToolCall(
                        id="context_call_1",
                        name="get_function_definition",
                        args={"function_name": "target_function"},
                    ),
                ],
            ),
        ]

        # Debug workflow messages
        debug_messages = [
            AIMessage(content="Confirm crash and capture backtrace."),  # analyze_debug
            AIMessage(content="```gdb\nrun\nbt\n```"),  # write_debug_script
        ]

        mock_llm.invoke.side_effect = context_messages + debug_messages

        # Mock codequery tool calls
        mock_task.codequery.get_functions = Mock(return_value=mock_codequery_responses["get_functions"])
        mock_task.codequery.get_callers = Mock(return_value=mock_codequery_responses["get_callers"])
        mock_task.codequery.get_types = Mock(return_value=mock_codequery_responses["get_types"])

        # Stop context retrieval after first iteration
        mock_task._continue_context_retrieval = lambda state: False

        gdb_result = CommandResult(
            success=True,
            output=b"Program received signal SIGSEGV\n#0 0xdeadbeef\n",
            error=b"",
        )

        def mock_exec_docker_cmd(cmd, **kwargs):
            if isinstance(cmd, list) and cmd and cmd[0] == "gdb":
                return gdb_result
            return mock_challenge_task_responses["exec_docker_cmd"]

        mock_task.challenge_task.exec_docker_cmd = Mock(side_effect=mock_exec_docker_cmd)

        build_dir = tmp_path / "build" / "out" / "test_project"
        build_dir.mkdir(parents=True)
        mock_task.challenge_task.get_build_dir = Mock(return_value=build_dir)

        # Stop after first debug iteration (prevents needing extra LLM responses)
        original_continue_debug = debug_subagent._continue_debug

        def stop_after_first_iteration(state):
            if state.debug_iteration >= 1:
                return False
            return original_continue_debug(state)

        debug_subagent._continue_debug = stop_after_first_iteration

        from buttercup.common.challenge_task import ReproduceResult

        # Create a mock reproduce result that indicates a crash
        crash_result = MagicMock(spec=ReproduceResult)
        crash_result.did_crash.return_value = True
        crash_result.stacktrace.return_value = "Stack trace for crash"
        crash_result.command_result = CommandResult(
            success=True,
            output=b"==ERROR: AddressSanitizer: heap-buffer-overflow",
            error=b"",
        )

        with patch.object(debug_subagent.reproduce_multiple, "open") as mock_open:
            mock_context = MagicMock()
            mock_context.builds_cache = [mock_task.challenge_task]
            mock_build = BuildOutput()
            mock_build.build_type = BuildType.FUZZER
            mock_context.get_crashes = Mock(return_value=iter([(mock_build, crash_result)]))
            mock_open.return_value.__enter__.return_value = mock_context
            mock_open.return_value.__exit__.return_value = None

            result = debug_subagent.debug(
                harness=mock_harness_info,
                pov_input_path=pov_input_path,
                debug_context=debug_context,
                output_dir=tmp_path / "debug_output",
            )

        assert result.pov_valid is True


def test_debug_error_handling(
    debug_subagent,
    mock_task,
    mock_llm,
    mock_harness_info,
    mock_codequery_responses,
    tmp_path,
):
    """Test error handling when GDB execution fails."""
    pov_input_path = tmp_path / "pov_input.bin"
    pov_input_path.write_bytes(b"test")

    with (
        patch("buttercup.common.llm.get_langfuse_callbacks", return_value=[]),
        patch("opentelemetry.trace.get_tracer") as mock_tracer,
    ):
        mock_span = MagicMock()
        mock_tracer.return_value.start_as_current_span.return_value.__enter__.return_value = mock_span

        # Context gathering messages - just one iteration since _continue_context_retrieval returns False
        context_messages = [
            AIMessage(
                content="I'll gather context for debugging",
                tool_calls=[
                    ToolCall(
                        id="context_call_1",
                        name="get_function_definition",
                        args={"function_name": "target_function"},
                    ),
                ],
            ),
        ]

        # Debug workflow messages
        debug_messages = [
            AIMessage(content="Analysis"),  # analyze_debug
            AIMessage(content="```gdb\nrun\n```"),  # write_debug_script
        ]

        mock_llm.invoke.side_effect = context_messages + debug_messages

        # Mock codequery tool calls
        mock_task.codequery.get_functions = Mock(return_value=mock_codequery_responses["get_functions"])
        mock_task.codequery.get_callers = Mock(return_value=mock_codequery_responses["get_callers"])
        mock_task.codequery.get_types = Mock(return_value=mock_codequery_responses["get_types"])

        # Stop context retrieval after first iteration
        mock_task._continue_context_retrieval = lambda state: False

        mock_task.challenge_task.exec_docker_cmd = Mock(side_effect=Exception("Docker error"))

        build_dir = tmp_path / "build" / "out" / "test_project"
        build_dir.mkdir(parents=True)
        mock_task.challenge_task.get_build_dir = Mock(return_value=build_dir)

        # Stop after first debug iteration (prevents needing extra LLM responses)
        original_continue_debug = debug_subagent._continue_debug

        def stop_after_first_iteration(state):
            if state.debug_iteration >= 1:
                return False
            return original_continue_debug(state)

        debug_subagent._continue_debug = stop_after_first_iteration

        result = debug_subagent.debug(
            harness=mock_harness_info,
            pov_input_path=pov_input_path,
            debug_context="Test error handling",
            output_dir=tmp_path / "debug_output",
        )

        assert result.pov_valid is False
        assert "Error" in result.debug_output


def test_debug_malformed_llm_response(
    debug_subagent,
    mock_task,
    mock_llm,
    mock_harness_info,
    mock_codequery_responses,
    mock_challenge_task_responses,
    tmp_path,
):
    """Test handling of malformed LLM response (no code block)."""
    pov_input_path = tmp_path / "pov_input.bin"
    pov_input_path.write_bytes(b"test input")
    debug_context = "Check if this input causes issues"

    with (
        patch("buttercup.common.llm.get_langfuse_callbacks", return_value=[]),
        patch("opentelemetry.trace.get_tracer") as mock_tracer,
        patch("buttercup.seed_gen.debug_subagent.set_crs_attributes") as _,
    ):
        mock_span = MagicMock()
        mock_tracer.return_value.start_as_current_span.return_value.__enter__.return_value = mock_span

        # Context gathering messages
        context_messages = [
            AIMessage(
                content="I'll gather context",
                tool_calls=[
                    ToolCall(
                        id="context_call_1",
                        name="get_function_definition",
                        args={"function_name": "target_function"},
                    ),
                ],
            ),
        ]

        # Debug workflow messages - MALFORMED response (no code block)
        debug_messages = [
            AIMessage(content="Analysis of the issue"),  # analyze_debug
            AIMessage(content="I'll create a debug script to check this but forgot the code block."),  # write_debug_script - MALFORMED!
        ]

        mock_llm.invoke.side_effect = context_messages + debug_messages

        # Mock codequery tool calls
        mock_task.codequery.get_functions = Mock(return_value=mock_codequery_responses["get_functions"])
        mock_task.codequery.get_callers = Mock(return_value=mock_codequery_responses["get_callers"])
        mock_task.codequery.get_types = Mock(return_value=mock_codequery_responses["get_types"])

        # Stop context retrieval after first iteration
        mock_task._continue_context_retrieval = lambda state: False

        # Mock docker command
        mock_task.challenge_task.exec_docker_cmd = Mock(
            return_value=mock_challenge_task_responses["exec_docker_cmd"]
        )

        build_dir = tmp_path / "build" / "out" / "test_project"
        build_dir.mkdir(parents=True)
        mock_task.challenge_task.get_build_dir = Mock(return_value=build_dir)

        # Stop after first debug iteration
        original_continue_debug = debug_subagent._continue_debug

        def stop_after_first_iteration(state):
            if state.debug_iteration >= 1:
                return False
            return original_continue_debug(state)

        debug_subagent._continue_debug = stop_after_first_iteration

        result = debug_subagent.debug(
            harness=mock_harness_info,
            pov_input_path=pov_input_path,
            debug_context=debug_context,
            output_dir=tmp_path / "debug_output",
        )

        # Should complete without crashing, but with empty script
        assert isinstance(result, DebugResult)
        assert result.pov_valid is False
        assert result.debug_script == ""  # Empty due to extraction failure
        assert result.debug_output == "No debug script provided"  # Message from _run_debug_script
        assert len(result.attempts) == 1  # Still recorded the attempt


def test_debug_docker_path_construction(
    debug_subagent,
    mock_task,
    mock_llm,
    mock_harness_info,
    mock_codequery_responses,
    tmp_path,
):
    """Test that Docker paths are constructed correctly for GDB execution."""
    pov_input_path = tmp_path / "pov_input.bin"
    pov_input_path.write_bytes(b"test input")
    debug_context = "Test path construction"

    # Create a proper debug script file
    debug_script_content = "break main\nrun\nbt\ncontinue\n"
    
    with (
        patch("buttercup.common.llm.get_langfuse_callbacks", return_value=[]),
        patch("opentelemetry.trace.get_tracer") as mock_tracer,
        patch("buttercup.seed_gen.debug_subagent.set_crs_attributes") as _,
    ):
        mock_span = MagicMock()
        mock_tracer.return_value.start_as_current_span.return_value.__enter__.return_value = mock_span

        # Context gathering messages
        context_messages = [
            AIMessage(
                content="I'll gather context",
                tool_calls=[
                    ToolCall(
                        id="context_call_1",
                        name="get_function_definition",
                        args={"function_name": "main"},
                    ),
                ],
            ),
        ]

        # Debug workflow messages with proper GDB script
        debug_messages = [
            AIMessage(content="Test analysis"),
            AIMessage(content=f"```gdb\n{debug_script_content}```"),
        ]

        mock_llm.invoke.side_effect = context_messages + debug_messages

        # Mock codequery
        mock_task.codequery.get_functions = Mock(return_value=mock_codequery_responses["get_functions"])
        mock_task.codequery.get_callers = Mock(return_value=mock_codequery_responses["get_callers"])
        mock_task.codequery.get_types = Mock(return_value=mock_codequery_responses["get_types"])
        mock_task._continue_context_retrieval = lambda state: False

        # Track the Docker command that gets called
        docker_cmd_captured = None
        mount_dirs_captured = None

        def capture_docker_cmd(cmd, mount_dirs=None, **kwargs):
            nonlocal docker_cmd_captured, mount_dirs_captured
            docker_cmd_captured = cmd
            mount_dirs_captured = mount_dirs
            return CommandResult(success=True, output=b"Test output", error=b"")

        mock_task.challenge_task.exec_docker_cmd = Mock(side_effect=capture_docker_cmd)

        # Set up build directory
        build_dir = tmp_path / "build" / "out"
        build_dir.mkdir(parents=True)
        mock_task.challenge_task.get_build_dir = Mock(return_value=build_dir)
        
        # Set harness name for path verification
        mock_task.harness_name = "test_fuzzer"

        # Stop after first iteration
        original_continue_debug = debug_subagent._continue_debug
        def stop_after_first(state):
            return state.debug_iteration < 1 and original_continue_debug(state)
        debug_subagent._continue_debug = stop_after_first

        result = debug_subagent.debug(
            harness=mock_harness_info,
            pov_input_path=pov_input_path,
            debug_context=debug_context,
            output_dir=tmp_path / "debug_output",
        )

        # Verify the Docker command was called
        assert docker_cmd_captured is not None, "Docker command should have been called"
        assert mount_dirs_captured is not None, "Mount directories should have been provided"

        # TEST 1: Binary path should be /out/{harness_name}, NOT /out/{project_name}/{harness_name}
        binary_path = docker_cmd_captured[docker_cmd_captured.index("--args") + 1]
        assert binary_path == "/out/test_fuzzer", (
            f"Binary path should be /out/test_fuzzer, got {binary_path}. "
            "It should NOT include project_name in the path!"
        )

        # TEST 2: Debug script should be mounted as parent directory
        debug_script_path_in_container = docker_cmd_captured[docker_cmd_captured.index("-x") + 1]
        assert debug_script_path_in_container.startswith("/tmp/debug_workdir/"), (
            f"Debug script should be in /tmp/debug_workdir/, got {debug_script_path_in_container}"
        )

        # TEST 3: PoV input should be mounted as parent directory
        pov_path_in_container = docker_cmd_captured[-1]
        assert pov_path_in_container.startswith("/tmp/pov_workdir/"), (
            f"PoV input should be in /tmp/pov_workdir/, got {pov_path_in_container}"
        )

        # TEST 4: Mount directories should include parent dirs, not individual files
        from pathlib import Path
        mount_paths = list(mount_dirs_captured.keys())
        mount_targets = list(mount_dirs_captured.values())
        
        # Should have 3 mounts: debug_script parent, pov_input parent, build_dir
        assert len(mount_dirs_captured) == 3, (
            f"Expected 3 mount directories (debug parent, pov parent, build), got {len(mount_dirs_captured)}"
        )
        
        # Verify all mount sources are directories, not files
        for mount_source in mount_paths:
            assert mount_source.is_dir(), (
                f"Mount source {mount_source} should be a directory, not a file"
            )

        # TEST 5: Build directory should be mounted to /out
        assert Path("/out") in mount_targets, (
            f"Build directory should be mounted to /out, got targets: {mount_targets}"
        )


def test_debug_binary_path_without_project_name(
    debug_subagent,
    mock_task,
    mock_llm,
    mock_harness_info,
    mock_codequery_responses,
    tmp_path,
):
    """Regression test: Ensure binary path does NOT include project_name subdirectory."""
    pov_input_path = tmp_path / "pov_input.bin"
    pov_input_path.write_bytes(b"test")

    with (
        patch("buttercup.common.llm.get_langfuse_callbacks", return_value=[]),
        patch("opentelemetry.trace.get_tracer") as mock_tracer,
    ):
        mock_span = MagicMock()
        mock_tracer.return_value.start_as_current_span.return_value.__enter__.return_value = mock_span

        context_messages = [
            AIMessage(
                content="Context",
                tool_calls=[
                    ToolCall(
                        id="1",
                        name="get_function_definition",
                        args={"function_name": "main"},
                    ),
                ],
            ),
        ]
        debug_messages = [
            AIMessage(content="Analysis"),
            AIMessage(content="```gdb\nrun\n```"),
        ]
        mock_llm.invoke.side_effect = context_messages + debug_messages

        mock_task.codequery.get_functions = Mock(return_value=mock_codequery_responses["get_functions"])
        mock_task.codequery.get_callers = Mock(return_value=mock_codequery_responses["get_callers"])
        mock_task.codequery.get_types = Mock(return_value=mock_codequery_responses["get_types"])
        mock_task._continue_context_retrieval = lambda state: False

        captured_cmd = None
        def capture_cmd(cmd, **kwargs):
            nonlocal captured_cmd
            captured_cmd = cmd
            return CommandResult(success=True, output=b"", error=b"")

        mock_task.challenge_task.exec_docker_cmd = Mock(side_effect=capture_cmd)
        
        build_dir = tmp_path / "build"
        build_dir.mkdir(parents=True)
        mock_task.challenge_task.get_build_dir = Mock(return_value=build_dir)
        mock_task.harness_name = "my_fuzzer"
        mock_task.challenge_task.project_name = "libpng"  # Should NOT appear in path!

        original_continue_debug = debug_subagent._continue_debug
        debug_subagent._continue_debug = lambda state: state.debug_iteration < 1 and original_continue_debug(state)

        debug_subagent.debug(
            harness=mock_harness_info,
            pov_input_path=pov_input_path,
            debug_context="Test",
            output_dir=tmp_path / "out",
        )

        assert captured_cmd is not None
        binary_path = captured_cmd[captured_cmd.index("--args") + 1]
        
        # CRITICAL: Binary should be /out/my_fuzzer, NOT /out/libpng/my_fuzzer
        assert binary_path == "/out/my_fuzzer", (
            f"Binary path must be /out/my_fuzzer (no project name subdirectory), got {binary_path}"
        )
        assert "/libpng/" not in binary_path, (
            f"Binary path should NOT contain project_name 'libpng', got {binary_path}"
        )
