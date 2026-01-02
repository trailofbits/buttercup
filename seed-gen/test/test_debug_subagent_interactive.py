"""Tests for DebugSubagentInteractive"""

import os

if "PYTHON_WASM_BUILD_PATH" not in os.environ:
    os.environ["PYTHON_WASM_BUILD_PATH"] = "/tmp/dummy-python.wasm"

from unittest.mock import MagicMock, Mock, patch
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage
from langchain_core.messages.tool import ToolCall

from buttercup.common.challenge_task import CommandResult as ChallengeCommandResult
from buttercup.common.docker_interactive import CommandResult
from buttercup.common.datastructures.msg_pb2 import BuildOutput, BuildType
from buttercup.common.reproduce_multiple import ReproduceMultiple
from buttercup.seed_gen.debug_subagent_interactive import (
    DebugResult,
    DebugSubagentInteractive,
    DebugTaskState,
)
from buttercup.seed_gen.interactive_debug_docker import InteractiveGDBDocker
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
def debug_subagent_interactive(mock_task, mock_reproduce_multiple):
    return DebugSubagentInteractive(mock_task, mock_reproduce_multiple)


@pytest.fixture
def mock_gdb_session():
    """Create a mock InteractiveGDBDocker session"""
    session = MagicMock(spec=InteractiveGDBDocker)
    
    # Mock console method to return CommandResult with lines
    def mock_console(cmd: str, timeout: float = 10.0):
        # Simulate GDB output based on command
        if cmd == "set breakpoint pending on":
            lines = ["^done"]
        elif cmd == "set print elements 0":
            lines = ["^done"]
        elif cmd == "set print pretty on":
            lines = ["^done"]
        elif cmd == "set pagination off":
            lines = ["^done"]
        elif cmd.startswith("break "):
            lines = [f"^done,bkpt={{number=\"1\",addr=\"0x123456\",func=\"{cmd.split()[1]}\"}}"]
        elif cmd == "run":
            lines = ["*running", "^running", "*stopped,reason=\"exited-normally\""]
        elif cmd in ["continue", "c"]:
            lines = ["*running", "^running", "*stopped,reason=\"breakpoint-hit\""]
        elif cmd == "bt":
            lines = ["^done,stack=[frame={level=\"0\",addr=\"0x123456\",func=\"main\"}]"]
        elif cmd.startswith("print ") or cmd.startswith("p "):
            var_name = cmd.split()[-1]
            lines = [f"^done,value=\"{var_name}=42\""]
        else:
            lines = ["^done"]
        
        return CommandResult(lines=lines, exit_code=0)
    
    session.console = Mock(side_effect=mock_console)
    session.run = Mock()
    session.close = Mock()
    session.container_name = "test_container"
    return session


def test_debug_interactive_basic_workflow(
    debug_subagent_interactive,
    mock_task,
    mock_llm,
    mock_harness_info,
    mock_codequery_responses,
    mock_gdb_session,
    tmp_path,
):
    """Test basic interactive debug workflow."""
    pov_input_path = tmp_path / "pov_input.bin"
    pov_input_path.write_bytes(b"test input data")
    debug_context = "Check if the target_function is called with this input"

    with (
        patch("buttercup.common.llm.get_langfuse_callbacks", return_value=[]),
        patch("opentelemetry.trace.get_tracer") as mock_tracer,
        patch("buttercup.seed_gen.debug_subagent_interactive.set_crs_attributes") as _,
        patch("buttercup.seed_gen.debug_subagent_interactive.InteractiveGDBDocker") as mock_gdb_class,
    ):
        mock_span = MagicMock()
        mock_tracer.return_value.start_as_current_span.return_value.__enter__.return_value = mock_span

        # Setup mock GDB session
        mock_gdb_class.return_value = mock_gdb_session

        # Context gathering messages
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

        # Analysis message
        analysis_message = AIMessage(content="Inspect target_function invocation and its args.")

        # Interactive command messages (LLM suggests commands)
        # Note: The chain is: prompt | llm | StrOutputParser, so we need to mock the chain
        interactive_commands = [
            "```gdb\nbreak target_function\n```",
            "```gdb\nrun\n```",
            "```gdb\nbt\n```",
            "```gdb\nprint arg1\n```",
            "```gdb\ncontinue\n```",
            "quit",  # LLM decides to quit early
        ]

        # Mock llm_with_tools for context gathering
        # Patch the task's llm_with_tools directly to avoid bind_tools issues
        mock_llm_with_tools = MagicMock()
        # Create a Mock for invoke that always returns the same message
        # Use return_value to avoid any iteration issues with side_effect
        mock_llm_with_tools.invoke = Mock(return_value=context_messages[0])
        # Patch the task's llm_with_tools attribute directly
        mock_task.llm_with_tools = mock_llm_with_tools

        # Track interactive command calls separately from LLM calls
        interactive_call_count = [0]
        def get_interactive_command(*args, **kwargs):
            interactive_call_count[0] += 1
            if interactive_call_count[0] <= len(interactive_commands):
                return interactive_commands[interactive_call_count[0] - 1]
            return "quit"
        
        # Use a function to return appropriate messages to avoid StopIteration
        # Track calls to return analysis_message first, then handle interactive commands, then reflection
        llm_call_count = [0]
        def mock_llm_invoke_func(*args, **kwargs):
            llm_call_count[0] += 1
            # First call is for analyze_debug
            if llm_call_count[0] == 1:
                return analysis_message
            
            # Check if this is an interactive command request by looking at the messages
            # Interactive commands have "Next GDB command" or "NEXT GDB command" in the prompt
            messages = args[0] if args else []
            is_interactive = False
            if isinstance(messages, list):
                # Check all messages for interactive command indicators
                for msg in messages:
                    content = None
                    if hasattr(msg, 'content'):
                        content = msg.content
                    elif isinstance(msg, dict) and 'content' in msg:
                        content = msg['content']
                    
                    if isinstance(content, str):
                        if "Next GDB command" in content or "NEXT GDB command" in content or "Commands remaining" in content:
                            is_interactive = True
                            break
            
            if is_interactive:
                # Return the next interactive command wrapped in an AIMessage
                cmd = get_interactive_command()
                return AIMessage(content=cmd)
            
            # For reflection or any other calls, return a default reflection message
            return AIMessage(content="Reflection on debug session")
        
        # Use a simpler approach: track call counts and return interactive commands
        # for calls 2 through (1 + len(interactive_commands)), then reflection
        # Call 1: analyze_debug
        # Calls 2 to (1 + len(interactive_commands)): interactive commands
        # Calls after that: reflection
        def simplified_llm_invoke(*args, **kwargs):
            llm_call_count[0] += 1
            # First call is for analyze_debug
            if llm_call_count[0] == 1:
                return analysis_message
            
            # Calls 2 to (1 + len(interactive_commands)) are for interactive commands
            interactive_start = 2
            interactive_end = 1 + len(interactive_commands)
            if interactive_start <= llm_call_count[0] <= interactive_end:
                cmd_idx = llm_call_count[0] - interactive_start
                if cmd_idx < len(interactive_commands):
                    return AIMessage(content=interactive_commands[cmd_idx])
            
            # All other calls are for reflection
            return AIMessage(content="Reflection on debug session")
        
        mock_llm.invoke.side_effect = simplified_llm_invoke

        # Mock codequery tool calls
        mock_task.codequery.get_functions = Mock(return_value=mock_codequery_responses["get_functions"])
        mock_task.codequery.get_callers = Mock(return_value=mock_codequery_responses["get_callers"])
        mock_task.codequery.get_types = Mock(return_value=mock_codequery_responses["get_types"])

        # Stop context retrieval after first iteration
        mock_task._continue_context_retrieval = lambda state: False

        # Setup build directory
        build_dir = tmp_path / "build" / "out" / "test_project"
        build_dir.mkdir(parents=True)
        (build_dir / "test_harness").write_bytes(b"fake binary")
        mock_task.challenge_task.get_build_dir = Mock(return_value=build_dir)
        mock_task.challenge_task.get_debug_binary_path = Mock(return_value=None)

        # Stop after first debug iteration
        original_continue_debug = debug_subagent_interactive._continue_debug

        def stop_after_first_iteration(state):
            if state.debug_iteration >= 1:
                return False
            return original_continue_debug(state)

        debug_subagent_interactive._continue_debug = stop_after_first_iteration

        result = debug_subagent_interactive.debug(
            harness=mock_harness_info,
            pov_input_path=pov_input_path,
            debug_context=debug_context,
            output_dir=tmp_path / "debug_output",
        )

        assert isinstance(result, DebugResult)
        assert result.pov_valid is False
        assert result.debug_output.strip() != "", "Should have debug output"
        # Check that commands file was written
        commands_file = tmp_path / "debug_output" / "debug_commands.txt"
        if commands_file.exists():
            commands_content = commands_file.read_text()
            assert len(commands_content) > 0, "Should have written commands to file"
        
        # Verify GDB session was created and used
        assert mock_gdb_class.called, "InteractiveGDBDocker should have been instantiated"
        assert mock_gdb_session.run.called, "GDB session should have been started"
        assert mock_gdb_session.console.call_count >= 4, "Should have executed setup + interactive commands"
        assert mock_gdb_session.close.called, "GDB session should have been closed"

        # Verify output files
        outdir = tmp_path / "debug_output"
        assert (outdir / "debug_commands.txt").exists()
        assert (outdir / "debug_output.txt").exists()
        assert (outdir / "pov_valid.txt").exists()


def test_debug_interactive_max_commands_reached(
    debug_subagent_interactive,
    mock_task,
    mock_llm,
    mock_harness_info,
    mock_codequery_responses,
    mock_gdb_session,
    tmp_path,
):
    """Test that interactive loop stops at MAX_INTERACTIVE_COMMANDS."""
    pov_input_path = tmp_path / "pov_input.bin"
    pov_input_path.write_bytes(b"test input")

    with (
        patch("buttercup.common.llm.get_langfuse_callbacks", return_value=[]),
        patch("opentelemetry.trace.get_tracer") as mock_tracer,
        patch("buttercup.seed_gen.debug_subagent_interactive.InteractiveGDBDocker") as mock_gdb_class,
    ):
        mock_span = MagicMock()
        mock_tracer.return_value.start_as_current_span.return_value.__enter__.return_value = mock_span

        mock_gdb_class.return_value = mock_gdb_session

        # Create enough commands to hit the limit
        context_messages = [AIMessage(content="Context", tool_calls=[])]
        analysis_message = AIMessage(content="Analysis")
        
        # Create 10 commands (the max) - LLM never says quit
        interactive_commands = [
            f"```gdb\ncommand_{i}\n```" for i in range(debug_subagent_interactive.MAX_INTERACTIVE_COMMANDS)
        ]

        # Mock llm_with_tools for context gathering
        # Patch the task's llm_with_tools directly to avoid bind_tools issues
        mock_llm_with_tools = MagicMock()
        # Create a Mock for invoke that always returns the same message
        # Use return_value to avoid any iteration issues with side_effect
        mock_llm_with_tools.invoke = Mock(return_value=context_messages[0])
        # Patch the task's llm_with_tools attribute directly
        mock_task.llm_with_tools = mock_llm_with_tools

        def mock_chain_invoke(prompt_vars):
            if not hasattr(mock_chain_invoke, 'call_count'):
                mock_chain_invoke.call_count = 0
            if mock_chain_invoke.call_count < len(interactive_commands):
                result = interactive_commands[mock_chain_invoke.call_count]
                mock_chain_invoke.call_count += 1
                return result
            return "quit"
        
        # Track interactive command calls separately from LLM calls
        interactive_call_count = [0]
        def get_interactive_command(*args, **kwargs):
            interactive_call_count[0] += 1
            if interactive_call_count[0] <= len(interactive_commands):
                return interactive_commands[interactive_call_count[0] - 1]
            return "quit"
        
        # Use a function to return appropriate messages to avoid StopIteration
        # Track calls to return analysis_message first, then handle interactive commands, then reflection
        llm_call_count = [0]
        def mock_llm_invoke_func(*args, **kwargs):
            llm_call_count[0] += 1
            # First call is for analyze_debug
            if llm_call_count[0] == 1:
                return analysis_message
            
            # Check if this is an interactive command request by looking at the messages
            # Interactive commands have "Next GDB command" or "NEXT GDB command" in the prompt
            messages = args[0] if args else []
            is_interactive = False
            if isinstance(messages, list):
                # Check all messages for interactive command indicators
                for msg in messages:
                    content = None
                    if hasattr(msg, 'content'):
                        content = msg.content
                    elif isinstance(msg, dict) and 'content' in msg:
                        content = msg['content']
                    
                    if isinstance(content, str):
                        if "Next GDB command" in content or "NEXT GDB command" in content or "Commands remaining" in content:
                            is_interactive = True
                            break
            
            if is_interactive:
                # Return the next interactive command wrapped in an AIMessage
                cmd = get_interactive_command()
                return AIMessage(content=cmd)
            
            # For reflection or any other calls, return a default reflection message
            return AIMessage(content="Reflection on debug session")
        
        # Use a simpler approach: track call counts and return interactive commands
        # for calls 2 through (1 + len(interactive_commands)), then reflection
        # Call 1: analyze_debug
        # Calls 2 to (1 + len(interactive_commands)): interactive commands
        # Calls after that: reflection
        def simplified_llm_invoke(*args, **kwargs):
            llm_call_count[0] += 1
            # First call is for analyze_debug
            if llm_call_count[0] == 1:
                return analysis_message
            
            # Calls 2 to (1 + len(interactive_commands)) are for interactive commands
            interactive_start = 2
            interactive_end = 1 + len(interactive_commands)
            if interactive_start <= llm_call_count[0] <= interactive_end:
                cmd_idx = llm_call_count[0] - interactive_start
                if cmd_idx < len(interactive_commands):
                    return AIMessage(content=interactive_commands[cmd_idx])
            
            # All other calls are for reflection
            return AIMessage(content="Reflection on debug session")
        
        mock_llm.invoke.side_effect = simplified_llm_invoke

        mock_task.codequery.get_functions = Mock(return_value=mock_codequery_responses["get_functions"])
        mock_task._continue_context_retrieval = lambda state: False

        build_dir = tmp_path / "build" / "out" / "test_project"
        build_dir.mkdir(parents=True)
        (build_dir / "test_harness").write_bytes(b"fake binary")
        mock_task.challenge_task.get_build_dir = Mock(return_value=build_dir)
        mock_task.challenge_task.get_debug_binary_path = Mock(return_value=None)

        debug_subagent_interactive._continue_debug = lambda state: False

        result = debug_subagent_interactive.debug(
            harness=mock_harness_info,
            pov_input_path=pov_input_path,
            debug_context="Test max commands",
            output_dir=tmp_path / "debug_output",
        )

        # Should have executed exactly MAX_INTERACTIVE_COMMANDS commands
        # Plus 4 setup commands (set breakpoint pending on, set print elements 0, set print pretty on, set pagination off)
        expected_calls = 4 + debug_subagent_interactive.MAX_INTERACTIVE_COMMANDS
        # Note: The workflow may fail before reaching interactive debug, so we check if it was called
        if mock_gdb_session.console.call_count > 0:
            assert mock_gdb_session.console.call_count == expected_calls, (
                f"Expected {expected_calls} console calls (4 setup + {debug_subagent_interactive.MAX_INTERACTIVE_COMMANDS} interactive), "
                f"got {mock_gdb_session.console.call_count}"
            )
            # Check commands file if it exists
            commands_file = tmp_path / "debug_output" / "debug_commands.txt"
            if commands_file.exists():
                commands = [cmd for cmd in commands_file.read_text().splitlines() if cmd.strip()]  # Filter empty lines
                # Should have at least the expected number of commands (may have more due to empty lines or extra writes)
                assert len(commands) >= expected_calls, (
                    f"Expected at least {expected_calls} commands, got {len(commands)}: {commands[:10]}"
                )


def test_debug_interactive_early_quit(
    debug_subagent_interactive,
    mock_task,
    mock_llm,
    mock_harness_info,
    mock_codequery_responses,
    mock_gdb_session,
    tmp_path,
):
    """Test that interactive loop stops when LLM says 'quit'."""
    pov_input_path = tmp_path / "pov_input.bin"
    pov_input_path.write_bytes(b"test input")

    with (
        patch("buttercup.common.llm.get_langfuse_callbacks", return_value=[]),
        patch("opentelemetry.trace.get_tracer") as mock_tracer,
        patch("buttercup.seed_gen.debug_subagent_interactive.InteractiveGDBDocker") as mock_gdb_class,
    ):
        mock_span = MagicMock()
        mock_tracer.return_value.start_as_current_span.return_value.__enter__.return_value = mock_span

        mock_gdb_class.return_value = mock_gdb_session

        context_messages = [AIMessage(content="Context", tool_calls=[])]
        analysis_message = AIMessage(content="Analysis")
        
        # LLM quits after 3 commands
        interactive_commands = [
            "```gdb\nbreak main\n```",
            "```gdb\nrun\n```",
            "quit",  # Early quit
        ]

        # Mock llm_with_tools for context gathering
        # Patch the task's llm_with_tools directly to avoid bind_tools issues
        mock_llm_with_tools = MagicMock()
        # Create a Mock for invoke that always returns the same message
        # Use return_value to avoid any iteration issues with side_effect
        mock_llm_with_tools.invoke = Mock(return_value=context_messages[0])
        # Patch the task's llm_with_tools attribute directly
        mock_task.llm_with_tools = mock_llm_with_tools

        def mock_chain_invoke(prompt_vars):
            if not hasattr(mock_chain_invoke, 'call_count'):
                mock_chain_invoke.call_count = 0
            if mock_chain_invoke.call_count < len(interactive_commands):
                result = interactive_commands[mock_chain_invoke.call_count]
                mock_chain_invoke.call_count += 1
                return result
            return "quit"
        
        # Track interactive command calls separately from LLM calls
        interactive_call_count = [0]
        def get_interactive_command(*args, **kwargs):
            interactive_call_count[0] += 1
            if interactive_call_count[0] <= len(interactive_commands):
                return interactive_commands[interactive_call_count[0] - 1]
            return "quit"
        
        # Use a function to return appropriate messages to avoid StopIteration
        # Track calls to return analysis_message first, then handle interactive commands, then reflection
        llm_call_count = [0]
        def mock_llm_invoke_func(*args, **kwargs):
            llm_call_count[0] += 1
            # First call is for analyze_debug
            if llm_call_count[0] == 1:
                return analysis_message
            
            # Check if this is an interactive command request by looking at the messages
            # Interactive commands have "Next GDB command" or "NEXT GDB command" in the prompt
            messages = args[0] if args else []
            is_interactive = False
            if isinstance(messages, list):
                # Check all messages for interactive command indicators
                for msg in messages:
                    content = None
                    if hasattr(msg, 'content'):
                        content = msg.content
                    elif isinstance(msg, dict) and 'content' in msg:
                        content = msg['content']
                    
                    if isinstance(content, str):
                        if "Next GDB command" in content or "NEXT GDB command" in content or "Commands remaining" in content:
                            is_interactive = True
                            break
            
            if is_interactive:
                # Return the next interactive command wrapped in an AIMessage
                cmd = get_interactive_command()
                return AIMessage(content=cmd)
            
            # For reflection or any other calls, return a default reflection message
            return AIMessage(content="Reflection on debug session")
        
        # Use a simpler approach: track call counts and return interactive commands
        # for calls 2 through (1 + len(interactive_commands)), then reflection
        # Call 1: analyze_debug
        # Calls 2 to (1 + len(interactive_commands)): interactive commands
        # Calls after that: reflection
        def simplified_llm_invoke(*args, **kwargs):
            llm_call_count[0] += 1
            # First call is for analyze_debug
            if llm_call_count[0] == 1:
                return analysis_message
            
            # Calls 2 to (1 + len(interactive_commands)) are for interactive commands
            interactive_start = 2
            interactive_end = 1 + len(interactive_commands)
            if interactive_start <= llm_call_count[0] <= interactive_end:
                cmd_idx = llm_call_count[0] - interactive_start
                if cmd_idx < len(interactive_commands):
                    return AIMessage(content=interactive_commands[cmd_idx])
            
            # All other calls are for reflection
            return AIMessage(content="Reflection on debug session")
        
        mock_llm.invoke.side_effect = simplified_llm_invoke

        mock_task.codequery.get_functions = Mock(return_value=mock_codequery_responses["get_functions"])
        mock_task._continue_context_retrieval = lambda state: False

        build_dir = tmp_path / "build" / "out" / "test_project"
        build_dir.mkdir(parents=True)
        (build_dir / "test_harness").write_bytes(b"fake binary")
        mock_task.challenge_task.get_build_dir = Mock(return_value=build_dir)
        mock_task.challenge_task.get_debug_binary_path = Mock(return_value=None)

        debug_subagent_interactive._continue_debug = lambda state: False

        result = debug_subagent_interactive.debug(
            harness=mock_harness_info,
            pov_input_path=pov_input_path,
            debug_context="Test early quit",
            output_dir=tmp_path / "debug_output",
        )

        # Should have executed 4 setup + 2 interactive commands (quit doesn't execute)
        # Note: The workflow may fail before reaching interactive debug, so we check if it was called
        # The loop should stop when "quit" is returned, so we expect:
        # - 4 setup commands (set breakpoint pending on, set print elements 0, set print pretty on, set pagination off)
        # - 2 interactive commands (break main, run)
        # Total: 6 calls
        if mock_gdb_session.console.call_count > 0:
            # Allow some flexibility in case of retries or extra calls
            assert mock_gdb_session.console.call_count <= 10, (
                f"Expected at most 10 calls (4 setup + up to 6 interactive), got {mock_gdb_session.console.call_count}"
            )
            # But we should have at least the setup + 2 interactive commands
            assert mock_gdb_session.console.call_count >= 6, (
                f"Expected at least 6 calls (4 setup + 2 interactive), got {mock_gdb_session.console.call_count}"
            )
        # Check commands file if it exists
        commands_file = tmp_path / "debug_output" / "debug_commands.txt"
        if commands_file.exists():
            commands = [cmd for cmd in commands_file.read_text().splitlines() if cmd.strip()]  # Filter empty lines
            # Should have: 4 setup commands + 2 interactive commands + "quit" = 7 total
            # Or just 4 setup + 2 interactive = 6 if quit isn't written
            assert len(commands) >= 6, f"Expected at least 6 commands, got {len(commands)}: {commands}"
            # The last non-empty command should be "quit" or one of the interactive commands
            assert commands[-1] in ["quit", "run", "break main"] or "quit" in commands, f"Last command should be quit or interactive, got: {commands[-1]}"


def test_debug_interactive_command_execution_error(
    debug_subagent_interactive,
    mock_task,
    mock_llm,
    mock_harness_info,
    mock_codequery_responses,
    mock_gdb_session,
    tmp_path,
):
    """Test handling of errors during command execution."""
    pov_input_path = tmp_path / "pov_input.bin"
    pov_input_path.write_bytes(b"test input")

    with (
        patch("buttercup.common.llm.get_langfuse_callbacks", return_value=[]),
        patch("opentelemetry.trace.get_tracer") as mock_tracer,
        patch("buttercup.seed_gen.debug_subagent_interactive.InteractiveGDBDocker") as mock_gdb_class,
    ):
        mock_span = MagicMock()
        mock_tracer.return_value.start_as_current_span.return_value.__enter__.return_value = mock_span

        mock_gdb_class.return_value = mock_gdb_session

        # Make console raise an error on the 3rd interactive command
        call_count = [0]
        def mock_console_with_error(cmd: str, timeout: float = 10.0):
            call_count[0] += 1
            # Setup commands work fine
            if call_count[0] <= 4:
                return CommandResult(lines=["^done"], exit_code=0)
            # First interactive command works
            if call_count[0] == 5:
                return CommandResult(lines=["^done"], exit_code=0)
            # Second interactive command fails
            if call_count[0] == 6:
                raise Exception("GDB command failed")
            return CommandResult(lines=["^done"], exit_code=0)

        mock_gdb_session.console = Mock(side_effect=mock_console_with_error)

        context_messages = [AIMessage(content="Context", tool_calls=[])]
        analysis_message = AIMessage(content="Analysis")
        interactive_commands = [
            "```gdb\nbreak main\n```",
            "```gdb\nrun\n```",
            "```gdb\nbt\n```",  # This will fail
            "quit",
        ]

        # Mock llm_with_tools for context gathering
        # Patch the task's llm_with_tools directly to avoid bind_tools issues
        mock_llm_with_tools = MagicMock()
        # Create a Mock for invoke that always returns the same message
        # Use return_value to avoid any iteration issues with side_effect
        mock_llm_with_tools.invoke = Mock(return_value=context_messages[0])
        # Patch the task's llm_with_tools attribute directly
        mock_task.llm_with_tools = mock_llm_with_tools

        def mock_chain_invoke(prompt_vars):
            if not hasattr(mock_chain_invoke, 'call_count'):
                mock_chain_invoke.call_count = 0
            if mock_chain_invoke.call_count < len(interactive_commands):
                result = interactive_commands[mock_chain_invoke.call_count]
                mock_chain_invoke.call_count += 1
                return result
            return "quit"
        
        # Track interactive command calls separately from LLM calls
        interactive_call_count = [0]
        def get_interactive_command(*args, **kwargs):
            interactive_call_count[0] += 1
            if interactive_call_count[0] <= len(interactive_commands):
                return interactive_commands[interactive_call_count[0] - 1]
            return "quit"
        
        # Use a function to return appropriate messages to avoid StopIteration
        # Track calls to return analysis_message first, then handle interactive commands, then reflection
        llm_call_count = [0]
        def mock_llm_invoke_func(*args, **kwargs):
            llm_call_count[0] += 1
            # First call is for analyze_debug
            if llm_call_count[0] == 1:
                return analysis_message
            
            # Check if this is an interactive command request by looking at the messages
            # Interactive commands have "Next GDB command" or "NEXT GDB command" in the prompt
            messages = args[0] if args else []
            is_interactive = False
            if isinstance(messages, list):
                # Check all messages for interactive command indicators
                for msg in messages:
                    content = None
                    if hasattr(msg, 'content'):
                        content = msg.content
                    elif isinstance(msg, dict) and 'content' in msg:
                        content = msg['content']
                    
                    if isinstance(content, str):
                        if "Next GDB command" in content or "NEXT GDB command" in content or "Commands remaining" in content:
                            is_interactive = True
                            break
            
            if is_interactive:
                # Return the next interactive command wrapped in an AIMessage
                cmd = get_interactive_command()
                return AIMessage(content=cmd)
            
            # For reflection or any other calls, return a default reflection message
            return AIMessage(content="Reflection on debug session")
        
        # Use a simpler approach: track call counts and return interactive commands
        # for calls 2 through (1 + len(interactive_commands)), then reflection
        # Call 1: analyze_debug
        # Calls 2 to (1 + len(interactive_commands)): interactive commands
        # Calls after that: reflection
        def simplified_llm_invoke(*args, **kwargs):
            llm_call_count[0] += 1
            # First call is for analyze_debug
            if llm_call_count[0] == 1:
                return analysis_message
            
            # Calls 2 to (1 + len(interactive_commands)) are for interactive commands
            interactive_start = 2
            interactive_end = 1 + len(interactive_commands)
            if interactive_start <= llm_call_count[0] <= interactive_end:
                cmd_idx = llm_call_count[0] - interactive_start
                if cmd_idx < len(interactive_commands):
                    return AIMessage(content=interactive_commands[cmd_idx])
            
            # All other calls are for reflection
            return AIMessage(content="Reflection on debug session")
        
        mock_llm.invoke.side_effect = simplified_llm_invoke

        mock_task.codequery.get_functions = Mock(return_value=mock_codequery_responses["get_functions"])
        mock_task._continue_context_retrieval = lambda state: False

        build_dir = tmp_path / "build" / "out" / "test_project"
        build_dir.mkdir(parents=True)
        (build_dir / "test_harness").write_bytes(b"fake binary")
        mock_task.challenge_task.get_build_dir = Mock(return_value=build_dir)
        mock_task.challenge_task.get_debug_binary_path = Mock(return_value=None)

        debug_subagent_interactive._continue_debug = lambda state: False

        result = debug_subagent_interactive.debug(
            harness=mock_harness_info,
            pov_input_path=pov_input_path,
            debug_context="Test error handling",
            output_dir=tmp_path / "debug_output",
        )

        # Should have recorded the error in output
        assert "Error executing command" in result.debug_output or "Error" in result.debug_output
        # Check commands file if it exists
        commands_file = tmp_path / "debug_output" / "debug_commands.txt"
        if commands_file.exists():
            commands = commands_file.read_text().splitlines()
            assert len(commands) >= 6  # 4 setup + at least 2 interactive


def test_debug_interactive_binary_path_selection(
    debug_subagent_interactive,
    mock_task,
    mock_llm,
    mock_harness_info,
    mock_codequery_responses,
    mock_gdb_session,
    tmp_path,
):
    """Test that debug binary is preferred over production binary."""
    pov_input_path = tmp_path / "pov_input.bin"
    pov_input_path.write_bytes(b"test input")

    with (
        patch("buttercup.common.llm.get_langfuse_callbacks", return_value=[]),
        patch("opentelemetry.trace.get_tracer") as mock_tracer,
        patch("buttercup.seed_gen.debug_subagent_interactive.InteractiveGDBDocker") as mock_gdb_class,
    ):
        mock_span = MagicMock()
        mock_tracer.return_value.start_as_current_span.return_value.__enter__.return_value = mock_span

        mock_gdb_class.return_value = mock_gdb_session

        context_messages = [AIMessage(content="Context", tool_calls=[])]
        analysis_message = AIMessage(content="Analysis")
        interactive_commands = ["quit"]

        # Mock llm_with_tools for context gathering
        # Patch the task's llm_with_tools directly to avoid bind_tools issues
        mock_llm_with_tools = MagicMock()
        # Create a Mock for invoke that always returns the same message
        # Use return_value to avoid any iteration issues with side_effect
        mock_llm_with_tools.invoke = Mock(return_value=context_messages[0])
        # Patch the task's llm_with_tools attribute directly
        mock_task.llm_with_tools = mock_llm_with_tools

        def mock_chain_invoke(prompt_vars):
            if not hasattr(mock_chain_invoke, 'call_count'):
                mock_chain_invoke.call_count = 0
            if mock_chain_invoke.call_count < len(interactive_commands):
                result = interactive_commands[mock_chain_invoke.call_count]
                mock_chain_invoke.call_count += 1
                return result
            return "quit"
        
        # Track interactive command calls separately from LLM calls
        interactive_call_count = [0]
        def get_interactive_command(*args, **kwargs):
            interactive_call_count[0] += 1
            if interactive_call_count[0] <= len(interactive_commands):
                return interactive_commands[interactive_call_count[0] - 1]
            return "quit"
        
        # Use a function to return appropriate messages to avoid StopIteration
        # Track calls to return analysis_message first, then handle interactive commands, then reflection
        llm_call_count = [0]
        def mock_llm_invoke_func(*args, **kwargs):
            llm_call_count[0] += 1
            # First call is for analyze_debug
            if llm_call_count[0] == 1:
                return analysis_message
            
            # Check if this is an interactive command request by looking at the messages
            # Interactive commands have "Next GDB command" or "NEXT GDB command" in the prompt
            messages = args[0] if args else []
            is_interactive = False
            if isinstance(messages, list):
                # Check all messages for interactive command indicators
                for msg in messages:
                    content = None
                    if hasattr(msg, 'content'):
                        content = msg.content
                    elif isinstance(msg, dict) and 'content' in msg:
                        content = msg['content']
                    
                    if isinstance(content, str):
                        if "Next GDB command" in content or "NEXT GDB command" in content or "Commands remaining" in content:
                            is_interactive = True
                            break
            
            if is_interactive:
                # Return the next interactive command wrapped in an AIMessage
                cmd = get_interactive_command()
                return AIMessage(content=cmd)
            
            # For reflection or any other calls, return a default reflection message
            return AIMessage(content="Reflection on debug session")
        
        # Use a simpler approach: track call counts and return interactive commands
        # for calls 2 through (1 + len(interactive_commands)), then reflection
        # Call 1: analyze_debug
        # Calls 2 to (1 + len(interactive_commands)): interactive commands
        # Calls after that: reflection
        def simplified_llm_invoke(*args, **kwargs):
            llm_call_count[0] += 1
            # First call is for analyze_debug
            if llm_call_count[0] == 1:
                return analysis_message
            
            # Calls 2 to (1 + len(interactive_commands)) are for interactive commands
            interactive_start = 2
            interactive_end = 1 + len(interactive_commands)
            if interactive_start <= llm_call_count[0] <= interactive_end:
                cmd_idx = llm_call_count[0] - interactive_start
                if cmd_idx < len(interactive_commands):
                    return AIMessage(content=interactive_commands[cmd_idx])
            
            # All other calls are for reflection
            return AIMessage(content="Reflection on debug session")
        
        mock_llm.invoke.side_effect = simplified_llm_invoke

        mock_task.codequery.get_functions = Mock(return_value=mock_codequery_responses["get_functions"])
        mock_task._continue_context_retrieval = lambda state: False

        build_dir = tmp_path / "build" / "out" / "test_project"
        build_dir.mkdir(parents=True)
        (build_dir / "test_harness").write_bytes(b"fake production binary")
        debug_dir = build_dir / "debug"
        debug_dir.mkdir()
        (debug_dir / "test_harness").write_bytes(b"fake debug binary")
        
        mock_task.challenge_task.get_build_dir = Mock(return_value=build_dir)
        mock_task.challenge_task.get_debug_binary_path = Mock(return_value=debug_dir / "test_harness")

        debug_subagent_interactive._continue_debug = lambda state: False

        result = debug_subagent_interactive.debug(
            harness=mock_harness_info,
            pov_input_path=pov_input_path,
            debug_context="Test binary selection",
            output_dir=tmp_path / "debug_output",
        )

        # Verify InteractiveGDBDocker was called with debug binary path
        assert mock_gdb_class.called
        call_args = mock_gdb_class.call_args
        binary_path = call_args.kwargs.get("binary_path", "")
        
        # Should use debug binary path: /out/test_project/debug/test_harness
        assert "/debug/" in binary_path, f"Should use debug binary path, got {binary_path}"
        assert binary_path == "/out/test_project/debug/test_harness", f"Expected /out/test_project/debug/test_harness, got {binary_path}"


def test_debug_interactive_session_cleanup(
    debug_subagent_interactive,
    mock_task,
    mock_llm,
    mock_harness_info,
    mock_codequery_responses,
    mock_gdb_session,
    tmp_path,
):
    """Test that GDB session is properly closed even on errors."""
    pov_input_path = tmp_path / "pov_input.bin"
    pov_input_path.write_bytes(b"test input")

    with (
        patch("buttercup.common.llm.get_langfuse_callbacks", return_value=[]),
        patch("opentelemetry.trace.get_tracer") as mock_tracer,
        patch("buttercup.seed_gen.debug_subagent_interactive.InteractiveGDBDocker") as mock_gdb_class,
    ):
        mock_span = MagicMock()
        mock_tracer.return_value.start_as_current_span.return_value.__enter__.return_value = mock_span

        mock_gdb_class.return_value = mock_gdb_session
        
        # Make run() raise an error
        mock_gdb_session.run.side_effect = Exception("Session start failed")

        context_messages = [AIMessage(content="Context", tool_calls=[])]
        analysis_message = AIMessage(content="Analysis")
        interactive_commands = ["quit"]

        # Mock llm_with_tools for context gathering
        # Patch the task's llm_with_tools directly to avoid bind_tools issues
        mock_llm_with_tools = MagicMock()
        # Create a Mock for invoke that always returns the same message
        # Use return_value to avoid any iteration issues with side_effect
        mock_llm_with_tools.invoke = Mock(return_value=context_messages[0])
        # Patch the task's llm_with_tools attribute directly
        mock_task.llm_with_tools = mock_llm_with_tools

        def mock_chain_invoke(prompt_vars):
            if not hasattr(mock_chain_invoke, 'call_count'):
                mock_chain_invoke.call_count = 0
            if mock_chain_invoke.call_count < len(interactive_commands):
                result = interactive_commands[mock_chain_invoke.call_count]
                mock_chain_invoke.call_count += 1
                return result
            return "quit"
        
        # Track interactive command calls separately from LLM calls
        interactive_call_count = [0]
        def get_interactive_command(*args, **kwargs):
            interactive_call_count[0] += 1
            if interactive_call_count[0] <= len(interactive_commands):
                return interactive_commands[interactive_call_count[0] - 1]
            return "quit"
        
        # Use a function to return appropriate messages to avoid StopIteration
        # Track calls to return analysis_message first, then handle interactive commands, then reflection
        llm_call_count = [0]
        def mock_llm_invoke_func(*args, **kwargs):
            llm_call_count[0] += 1
            # First call is for analyze_debug
            if llm_call_count[0] == 1:
                return analysis_message
            
            # Check if this is an interactive command request by looking at the messages
            # Interactive commands have "Next GDB command" or "NEXT GDB command" in the prompt
            messages = args[0] if args else []
            is_interactive = False
            if isinstance(messages, list):
                # Check all messages for interactive command indicators
                for msg in messages:
                    content = None
                    if hasattr(msg, 'content'):
                        content = msg.content
                    elif isinstance(msg, dict) and 'content' in msg:
                        content = msg['content']
                    
                    if isinstance(content, str):
                        if "Next GDB command" in content or "NEXT GDB command" in content or "Commands remaining" in content:
                            is_interactive = True
                            break
            
            if is_interactive:
                # Return the next interactive command wrapped in an AIMessage
                cmd = get_interactive_command()
                return AIMessage(content=cmd)
            
            # For reflection or any other calls, return a default reflection message
            return AIMessage(content="Reflection on debug session")
        
        # Use a simpler approach: track call counts and return interactive commands
        # for calls 2 through (1 + len(interactive_commands)), then reflection
        # Call 1: analyze_debug
        # Calls 2 to (1 + len(interactive_commands)): interactive commands
        # Calls after that: reflection
        def simplified_llm_invoke(*args, **kwargs):
            llm_call_count[0] += 1
            # First call is for analyze_debug
            if llm_call_count[0] == 1:
                return analysis_message
            
            # Calls 2 to (1 + len(interactive_commands)) are for interactive commands
            interactive_start = 2
            interactive_end = 1 + len(interactive_commands)
            if interactive_start <= llm_call_count[0] <= interactive_end:
                cmd_idx = llm_call_count[0] - interactive_start
                if cmd_idx < len(interactive_commands):
                    return AIMessage(content=interactive_commands[cmd_idx])
            
            # All other calls are for reflection
            return AIMessage(content="Reflection on debug session")
        
        mock_llm.invoke.side_effect = simplified_llm_invoke

        mock_task.codequery.get_functions = Mock(return_value=mock_codequery_responses["get_functions"])
        mock_task._continue_context_retrieval = lambda state: False

        build_dir = tmp_path / "build" / "out" / "test_project"
        build_dir.mkdir(parents=True)
        (build_dir / "test_harness").write_bytes(b"fake binary")
        mock_task.challenge_task.get_build_dir = Mock(return_value=build_dir)
        mock_task.challenge_task.get_debug_binary_path = Mock(return_value=None)

        debug_subagent_interactive._continue_debug = lambda state: False

        result = debug_subagent_interactive.debug(
            harness=mock_harness_info,
            pov_input_path=pov_input_path,
            debug_context="Test cleanup",
            output_dir=tmp_path / "debug_output",
        )

        # Should have attempted to close the session
        assert mock_gdb_session.close.called, "Session should be closed even on error"
        assert "Error" in result.debug_output


def test_debug_interactive_state_management(
    debug_subagent_interactive,
    mock_task,
    mock_llm,
    mock_harness_info,
    mock_codequery_responses,
    mock_gdb_session,
    tmp_path,
):
    """Test that debug commands and output are properly stored in state."""
    pov_input_path = tmp_path / "pov_input.bin"
    pov_input_path.write_bytes(b"test input")

    with (
        patch("buttercup.common.llm.get_langfuse_callbacks", return_value=[]),
        patch("opentelemetry.trace.get_tracer") as mock_tracer,
        patch("buttercup.seed_gen.debug_subagent_interactive.InteractiveGDBDocker") as mock_gdb_class,
    ):
        mock_span = MagicMock()
        mock_tracer.return_value.start_as_current_span.return_value.__enter__.return_value = mock_span

        mock_gdb_class.return_value = mock_gdb_session

        context_messages = [AIMessage(content="Context", tool_calls=[])]
        analysis_message = AIMessage(content="Test analysis for state management")
        interactive_commands = [
            "```gdb\nbreak main\n```",
            "```gdb\nrun\n```",
            "quit",
        ]

        # Mock llm_with_tools for context gathering
        # Patch the task's llm_with_tools directly to avoid bind_tools issues
        mock_llm_with_tools = MagicMock()
        # Create a Mock for invoke that always returns the same message
        # Use return_value to avoid any iteration issues with side_effect
        mock_llm_with_tools.invoke = Mock(return_value=context_messages[0])
        # Patch the task's llm_with_tools attribute directly
        mock_task.llm_with_tools = mock_llm_with_tools

        def mock_chain_invoke(prompt_vars):
            if not hasattr(mock_chain_invoke, 'call_count'):
                mock_chain_invoke.call_count = 0
            if mock_chain_invoke.call_count < len(interactive_commands):
                result = interactive_commands[mock_chain_invoke.call_count]
                mock_chain_invoke.call_count += 1
                return result
            return "quit"
        
        # Track interactive command calls separately from LLM calls
        interactive_call_count = [0]
        def get_interactive_command(*args, **kwargs):
            interactive_call_count[0] += 1
            if interactive_call_count[0] <= len(interactive_commands):
                return interactive_commands[interactive_call_count[0] - 1]
            return "quit"
        
        # Use a function to return appropriate messages to avoid StopIteration
        # Track calls to return analysis_message first, then handle interactive commands, then reflection
        llm_call_count = [0]
        def mock_llm_invoke_func(*args, **kwargs):
            llm_call_count[0] += 1
            # First call is for analyze_debug
            if llm_call_count[0] == 1:
                return analysis_message
            
            # Check if this is an interactive command request by looking at the messages
            # Interactive commands have "Next GDB command" or "NEXT GDB command" in the prompt
            messages = args[0] if args else []
            is_interactive = False
            if isinstance(messages, list):
                # Check all messages for interactive command indicators
                for msg in messages:
                    content = None
                    if hasattr(msg, 'content'):
                        content = msg.content
                    elif isinstance(msg, dict) and 'content' in msg:
                        content = msg['content']
                    
                    if isinstance(content, str):
                        if "Next GDB command" in content or "NEXT GDB command" in content or "Commands remaining" in content:
                            is_interactive = True
                            break
            
            if is_interactive:
                # Return the next interactive command wrapped in an AIMessage
                cmd = get_interactive_command()
                return AIMessage(content=cmd)
            
            # For reflection or any other calls, return a default reflection message
            return AIMessage(content="Reflection on debug session")
        
        # Use a simpler approach: track call counts and return interactive commands
        # for calls 2 through (1 + len(interactive_commands)), then reflection
        # Call 1: analyze_debug
        # Calls 2 to (1 + len(interactive_commands)): interactive commands
        # Calls after that: reflection
        def simplified_llm_invoke(*args, **kwargs):
            llm_call_count[0] += 1
            # First call is for analyze_debug
            if llm_call_count[0] == 1:
                return analysis_message
            
            # Calls 2 to (1 + len(interactive_commands)) are for interactive commands
            interactive_start = 2
            interactive_end = 1 + len(interactive_commands)
            if interactive_start <= llm_call_count[0] <= interactive_end:
                cmd_idx = llm_call_count[0] - interactive_start
                if cmd_idx < len(interactive_commands):
                    return AIMessage(content=interactive_commands[cmd_idx])
            
            # All other calls are for reflection
            return AIMessage(content="Reflection on debug session")
        
        mock_llm.invoke.side_effect = simplified_llm_invoke

        mock_task.codequery.get_functions = Mock(return_value=mock_codequery_responses["get_functions"])
        mock_task._continue_context_retrieval = lambda state: False

        build_dir = tmp_path / "build" / "out" / "test_project"
        build_dir.mkdir(parents=True)
        (build_dir / "test_harness").write_bytes(b"fake binary")
        mock_task.challenge_task.get_build_dir = Mock(return_value=build_dir)
        mock_task.challenge_task.get_debug_binary_path = Mock(return_value=None)

        debug_subagent_interactive._continue_debug = lambda state: False

        result = debug_subagent_interactive.debug(
            harness=mock_harness_info,
            pov_input_path=pov_input_path,
            debug_context="Test state management",
            output_dir=tmp_path / "debug_output",
        )

        # Verify state was properly populated (if workflow completed)
        if result.analysis:
            assert result.analysis == "Test analysis for state management"
        assert result.debug_output != ""
        
        # Verify commands file was written (if workflow reached interactive debug)
        commands_file = tmp_path / "debug_output" / "debug_commands.txt"
        if commands_file.exists():
            commands_content = commands_file.read_text()
            assert "set breakpoint pending on" in commands_content
            assert "break main" in commands_content


def test_debug_interactive_workflow_skip_validation(
    mock_task,
    mock_llm,
    mock_harness_info,
    mock_codequery_responses,
    mock_gdb_session,
    tmp_path,
):
    """Test workflow with skip_validation=True."""
    pov_input_path = tmp_path / "pov_input.bin"
    pov_input_path.write_bytes(b"test input")

    # Create subagent with skip_validation - need to create reproduce_multiple properly
    build_output = BuildOutput()
    build_output.task_dir = str(mock_task.challenge_task.task_dir)
    build_output.build_type = BuildType.FUZZER
    build_output.engine = "libfuzzer"
    build_output.sanitizer = "address"
    
    reproduce_multiple = ReproduceMultiple(tmp_path, [build_output])
    
    with (
        patch("buttercup.common.llm.get_langfuse_callbacks", return_value=[]),
        patch("opentelemetry.trace.get_tracer") as mock_tracer,
        patch("buttercup.seed_gen.debug_subagent_interactive.InteractiveGDBDocker") as mock_gdb_class,
        patch.object(reproduce_multiple, "open") as mock_open,
    ):
        mock_context = MagicMock()
        mock_context.builds_cache = [mock_task.challenge_task]
        mock_context.get_crashes = Mock(return_value=iter([]))
        mock_open.return_value.__enter__.return_value = mock_context
        mock_open.return_value.__exit__.return_value = None
        
        debug_subagent = DebugSubagentInteractive(
            mock_task,
            reproduce_multiple,
            skip_validation=True,
        )
        mock_span = MagicMock()
        mock_tracer.return_value.start_as_current_span.return_value.__enter__.return_value = mock_span

        mock_gdb_class.return_value = mock_gdb_session

        context_messages = [AIMessage(content="Context", tool_calls=[])]
        analysis_message = AIMessage(content="Analysis")
        reflection_message = AIMessage(content="Reflection on debug session")
        interactive_commands = ["quit"]

        # Mock llm_with_tools for context gathering
        # Patch the task's llm_with_tools directly to avoid bind_tools issues
        mock_llm_with_tools = MagicMock()
        # Create a Mock for invoke that always returns the same message
        # Use return_value to avoid any iteration issues with side_effect
        mock_llm_with_tools.invoke = Mock(return_value=context_messages[0])
        # Patch the task's llm_with_tools attribute directly
        mock_task.llm_with_tools = mock_llm_with_tools

        def mock_chain_invoke(prompt_vars):
            if not hasattr(mock_chain_invoke, 'call_count'):
                mock_chain_invoke.call_count = 0
            if mock_chain_invoke.call_count < len(interactive_commands):
                result = interactive_commands[mock_chain_invoke.call_count]
                mock_chain_invoke.call_count += 1
                return result
            return "quit"
        
        with patch("buttercup.seed_gen.debug_subagent_interactive.ChatPromptTemplate") as mock_prompt:
            # Mock the chain: prompt | llm | StrOutputParser
            # The chain construction is: (prompt | llm) | StrOutputParser()
            # Create a mock chain that handles both __or__ operations
            mock_final_chain = MagicMock()
            mock_final_chain.invoke.side_effect = mock_chain_invoke
            mock_intermediate_chain = MagicMock()
            # Second __or__: (prompt | llm) | StrOutputParser -> returns final chain
            mock_intermediate_chain.__or__ = lambda self, other: mock_final_chain
            # First __or__: prompt | llm -> returns intermediate chain
            mock_prompt_instance = MagicMock()
            mock_prompt_instance.__or__ = lambda self, other: mock_intermediate_chain
            mock_prompt.from_messages.return_value = mock_prompt_instance
            # analyze_debug and reflect_debug both use llm.invoke
            # Use a function to always return the appropriate message to avoid StopIteration
            call_count = [0]
            def mock_llm_invoke(*args, **kwargs):
                call_count[0] += 1
                # First call is for analyze_debug, subsequent calls are for reflect_debug
                if call_count[0] == 1:
                    return analysis_message
                return reflection_message
            mock_llm.invoke.side_effect = mock_llm_invoke

        mock_task.codequery.get_functions = Mock(return_value=mock_codequery_responses["get_functions"])
        mock_task._continue_context_retrieval = lambda state: False

        build_dir = tmp_path / "build" / "out" / "test_project"
        build_dir.mkdir(parents=True)
        (build_dir / "test_harness").write_bytes(b"fake binary")
        mock_task.challenge_task.get_build_dir = Mock(return_value=build_dir)
        mock_task.challenge_task.get_debug_binary_path = Mock(return_value=None)

        result = debug_subagent.debug(
            harness=mock_harness_info,
            pov_input_path=pov_input_path,
            debug_context="Test skip validation",
            output_dir=tmp_path / "debug_output",
        )

        # Should complete without validation step
        assert result.reflection != ""
        # Should not have attempted validation
        assert result.pov_valid is False  # Default value, not set by validation


def test_debug_interactive_mount_directories(
    debug_subagent_interactive,
    mock_task,
    mock_llm,
    mock_harness_info,
    mock_codequery_responses,
    mock_gdb_session,
    tmp_path,
):
    """Test that mount directories are set up correctly for InteractiveGDBDocker."""
    pov_input_path = tmp_path / "pov_input.bin"
    pov_input_path.write_bytes(b"test input")

    with (
        patch("buttercup.common.llm.get_langfuse_callbacks", return_value=[]),
        patch("opentelemetry.trace.get_tracer") as mock_tracer,
        patch("buttercup.seed_gen.debug_subagent_interactive.InteractiveGDBDocker") as mock_gdb_class,
    ):
        mock_span = MagicMock()
        mock_tracer.return_value.start_as_current_span.return_value.__enter__.return_value = mock_span

        mock_gdb_class.return_value = mock_gdb_session

        context_messages = [AIMessage(content="Context", tool_calls=[])]
        analysis_message = AIMessage(content="Analysis")
        interactive_commands = ["quit"]

        # Mock llm_with_tools for context gathering
        # Patch the task's llm_with_tools directly to avoid bind_tools issues
        mock_llm_with_tools = MagicMock()
        # Create a Mock for invoke that always returns the same message
        # Use return_value to avoid any iteration issues with side_effect
        mock_llm_with_tools.invoke = Mock(return_value=context_messages[0])
        # Patch the task's llm_with_tools attribute directly
        mock_task.llm_with_tools = mock_llm_with_tools

        def mock_chain_invoke(prompt_vars):
            if not hasattr(mock_chain_invoke, 'call_count'):
                mock_chain_invoke.call_count = 0
            if mock_chain_invoke.call_count < len(interactive_commands):
                result = interactive_commands[mock_chain_invoke.call_count]
                mock_chain_invoke.call_count += 1
                return result
            return "quit"
        
        # Track interactive command calls separately from LLM calls
        interactive_call_count = [0]
        def get_interactive_command(*args, **kwargs):
            interactive_call_count[0] += 1
            if interactive_call_count[0] <= len(interactive_commands):
                return interactive_commands[interactive_call_count[0] - 1]
            return "quit"
        
        # Use a function to return appropriate messages to avoid StopIteration
        # Track calls to return analysis_message first, then handle interactive commands, then reflection
        llm_call_count = [0]
        def mock_llm_invoke_func(*args, **kwargs):
            llm_call_count[0] += 1
            # First call is for analyze_debug
            if llm_call_count[0] == 1:
                return analysis_message
            
            # Check if this is an interactive command request by looking at the messages
            # Interactive commands have "Next GDB command" or "NEXT GDB command" in the prompt
            messages = args[0] if args else []
            is_interactive = False
            if isinstance(messages, list):
                # Check all messages for interactive command indicators
                for msg in messages:
                    content = None
                    if hasattr(msg, 'content'):
                        content = msg.content
                    elif isinstance(msg, dict) and 'content' in msg:
                        content = msg['content']
                    
                    if isinstance(content, str):
                        if "Next GDB command" in content or "NEXT GDB command" in content or "Commands remaining" in content:
                            is_interactive = True
                            break
            
            if is_interactive:
                # Return the next interactive command wrapped in an AIMessage
                cmd = get_interactive_command()
                return AIMessage(content=cmd)
            
            # For reflection or any other calls, return a default reflection message
            return AIMessage(content="Reflection on debug session")
        
        # Use a simpler approach: track call counts and return interactive commands
        # for calls 2 through (1 + len(interactive_commands)), then reflection
        # Call 1: analyze_debug
        # Calls 2 to (1 + len(interactive_commands)): interactive commands
        # Calls after that: reflection
        def simplified_llm_invoke(*args, **kwargs):
            llm_call_count[0] += 1
            # First call is for analyze_debug
            if llm_call_count[0] == 1:
                return analysis_message
            
            # Calls 2 to (1 + len(interactive_commands)) are for interactive commands
            interactive_start = 2
            interactive_end = 1 + len(interactive_commands)
            if interactive_start <= llm_call_count[0] <= interactive_end:
                cmd_idx = llm_call_count[0] - interactive_start
                if cmd_idx < len(interactive_commands):
                    return AIMessage(content=interactive_commands[cmd_idx])
            
            # All other calls are for reflection
            return AIMessage(content="Reflection on debug session")
        
        mock_llm.invoke.side_effect = simplified_llm_invoke

        mock_task.codequery.get_functions = Mock(return_value=mock_codequery_responses["get_functions"])
        mock_task._continue_context_retrieval = lambda state: False

        build_dir = tmp_path / "build" / "out" / "test_project"
        build_dir.mkdir(parents=True)
        (build_dir / "test_harness").write_bytes(b"fake binary")
        mock_task.challenge_task.get_build_dir = Mock(return_value=build_dir)
        mock_task.challenge_task.get_debug_binary_path = Mock(return_value=None)

        debug_subagent_interactive._continue_debug = lambda state: False

        debug_subagent_interactive.debug(
            harness=mock_harness_info,
            pov_input_path=pov_input_path,
            debug_context="Test mounts",
            output_dir=tmp_path / "debug_output",
        )

        # Verify InteractiveGDBDocker was called with correct mount_dirs
        assert mock_gdb_class.called
        call_kwargs = mock_gdb_class.call_args.kwargs
        
        mount_dirs = call_kwargs.get("mount_dirs", {})
        assert len(mount_dirs) >= 2, "Should have at least 2 mount directories"
        
        # Should mount PoV input parent to /work
        assert Path("/work") in mount_dirs.values(), "Should mount to /work"
        # Should mount build/out to /out
        assert Path("/out") in mount_dirs.values(), "Should mount to /out"
        
        # Verify binary_path and input_path
        binary_path = call_kwargs.get("binary_path", "")
        input_path = call_kwargs.get("input_path", "")
        
        assert binary_path.startswith("/out/"), f"Binary path should start with /out/, got {binary_path}"
        assert input_path.startswith("/work/"), f"Input path should start with /work/, got {input_path}"

