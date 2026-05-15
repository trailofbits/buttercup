"""Tests for VulnDiscoveryFullTask"""

from unittest.mock import MagicMock, Mock, patch

import pytest
from buttercup.common.datastructures.msg_pb2 import BuildOutput, Crash
from buttercup.common.reproduce_multiple import ReproduceResult
from langchain_core.messages import AIMessage
from langchain_core.messages.tool import ToolCall

from buttercup.seed_gen.vuln_discovery_full import VulnDiscoveryFullTask
from test.conftest import (
    mock_sandbox_exec_funcs,
)


@pytest.fixture
def vuln_discovery_full_task(
    mock_challenge_task,
    mock_codequery,
    mock_project_yaml,
    mock_redis,
    mock_reproduce_multiple,
    mock_llm,
    mock_crash_submit,
):
    """Create a VulnDiscoveryFullTask instance with mocked dependencies."""
    with (
        patch("buttercup.seed_gen.task.Task.get_llm", return_value=mock_llm),
    ):
        task = VulnDiscoveryFullTask(
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

        return task


def test_do_task_valid_pov(
    vuln_discovery_full_task,
    mock_llm,
    mock_harness_info,
    mock_reproduce_multiple,
    mock_crash_submit,
    tmp_path,
    mock_challenge_task_responses,
    mock_codequery_responses,
):
    """Test successful execution of do_task method with valid PoV found on 2nd iteration"""
    out_dir = tmp_path / "out"
    current_dir = tmp_path / "current"
    out_dir.mkdir()
    current_dir.mkdir()

    vuln_discovery_full_task.get_harness_source = Mock(return_value=mock_harness_info)

    # Mock reproduce_multiple to return crashes on 2nd iteration
    def mock_get_crashes(pov_path, harness_name):
        if "iter1_" in pov_path.name:
            build = BuildOutput()
            build.sanitizer = "asan"

            result = MagicMock(spec=ReproduceResult)
            result.did_crash.return_value = True
            result.stacktrace.return_value = "Stack trace for crash"

            command_result = MagicMock()
            command_result.output = b"stdout output"
            command_result.error = b"stderr output"
            result.command_result = command_result

            yield build, result
        else:
            return

    mock_reproduce_multiple.get_crashes.side_effect = mock_get_crashes

    with (
        patch("buttercup.common.llm.get_langfuse_callbacks", return_value=[]),
        patch("opentelemetry.trace.get_tracer") as mock_tracer,
        patch("buttercup.seed_gen.vuln_base_task.set_crs_attributes") as mock_set_attrs,
        patch("buttercup.seed_gen.vuln_base_task.sandbox_exec_funcs") as mock_sandbox_exec,
        patch("buttercup.seed_gen.vuln_base_task.stack_parsing.get_crash_token") as mock_get_token,
    ):
        mock_span = MagicMock()
        mock_tracer.return_value.start_as_current_span.return_value.__enter__.return_value = mock_span
        mock_sandbox_exec.side_effect = mock_sandbox_exec_funcs
        mock_get_token.return_value = "test_crash_token"

        # Mock crash_set.add to simulate that 2nd crash is duplicate
        mock_crash_submit.crash_set.add.side_effect = [False, True]

        context_messages = [
            AIMessage(
                content="I'll gather context about the target function",
                tool_calls=[
                    ToolCall(
                        id="context_call_1",
                        name="get_function_definition",
                        args={"function_name": "target_function"},
                    ),
                ],
            ),
            AIMessage(
                content="I need more context",
                tool_calls=[
                    ToolCall(
                        id="context_call_2",
                        name="get_type_definition",
                        args={"type_name": "buffer_t"},
                    ),
                ],
            ),
            AIMessage(
                content="I need more context",
                tool_calls=[
                    ToolCall(
                        id="context_call_3",
                        name="cat",
                        args={"file_path": "/src/test.c"},
                    ),
                ],
            ),
            AIMessage(
                content="I need more context",
                tool_calls=[
                    ToolCall(
                        id="context_call_4",
                        name="get_callers",
                        args={"function_name": "target_function", "file_path": "/src/test.c"},
                    ),
                ],
            ),
        ] * 2

        vuln_messages = []
        for _ in range(vuln_discovery_full_task.MAX_POV_ITERATIONS):
            vuln_messages.append(
                AIMessage(content="This is a buffer overflow vulnerability in the strcpy function"),
            )
            vuln_messages.append(
                AIMessage(
                    content=(
                        "Here are the test functions:\n\n```python\n"
                        "def gen_test_case_1() -> bytes:\n"
                        '    return b"A" * 200  # Buffer overflow test case\n'
                        "def gen_test_case_2() -> bytes:\n"
                        '    return b"B" * 300  # Another buffer overflow test case\n```'
                    ),
                ),
            )

        mock_llm.invoke.side_effect = context_messages + vuln_messages

        vuln_discovery_full_task.codequery.get_functions = Mock(
            return_value=mock_codequery_responses["get_functions"],
        )
        vuln_discovery_full_task.codequery.get_callers = Mock(
            return_value=mock_codequery_responses["get_callers"],
        )
        vuln_discovery_full_task.codequery.get_types = Mock(
            return_value=mock_codequery_responses["get_types"],
        )
        vuln_discovery_full_task.challenge_task.exec_docker_cmd = Mock(
            return_value=mock_challenge_task_responses["exec_docker_cmd"],
        )

        vuln_discovery_full_task.do_task(out_dir, current_dir)

        mock_tracer.assert_called_once_with("buttercup.seed_gen.vuln_base_task")
        mock_set_attrs.assert_called_once()

        vuln_discovery_full_task.codequery.get_functions.assert_called()
        vuln_discovery_full_task.codequery.get_callers.assert_called()
        vuln_discovery_full_task.codequery.get_types.assert_called()
        vuln_discovery_full_task.challenge_task.exec_docker_cmd.assert_called()

        mock_sandbox_exec.assert_called()

        for i in range(2):
            iter_pov_files = list(out_dir.glob(f"iter{i}_*.seed"))
            assert len(iter_pov_files) == 2, (
                f"Expected 2 seeds for iter{i}, found {len(iter_pov_files)}: {iter_pov_files}"
            )

            iter_pov1_file = next(f for f in iter_pov_files if "gen_seed_1" in f.name)
            iter_pov2_file = next(f for f in iter_pov_files if "gen_seed_2" in f.name)

            assert iter_pov1_file.read_bytes() == b"mock_seed_data_1"
            assert iter_pov2_file.read_bytes() == b"mock_seed_data_2"

        mock_reproduce_multiple.get_crashes.assert_called()

        assert mock_crash_submit.crash_set.add.call_count == 2
        mock_crash_submit.crash_queue.push.assert_called_once()

        crash_call = mock_crash_submit.crash_queue.push.call_args[0][0]
        assert isinstance(crash_call, Crash)
        assert crash_call.harness_name == "test_harness"
        assert crash_call.crash_token == "test_crash_token"
        assert crash_call.stacktrace == "Stack trace for crash"

        iter_pov_files_skipped = list(out_dir.glob("iter2_*.seed"))
        assert len(iter_pov_files_skipped) == 0, (
            f"Expected skipping 3rd iter, but there are {len(iter_pov_files_skipped)} seeds"
        )
