"""Tests for VulnDiscoveryDeltaTask"""

from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest
from langchain_core.messages import AIMessage
from langchain_core.messages.tool import ToolCall

from buttercup.seed_gen.vuln_discovery_delta import VulnDiscoveryDeltaTask
from test.conftest import (
    mock_sandbox_exec_funcs,
)


@pytest.fixture
def vuln_discovery_task(
    mock_challenge_task_with_diff,
    mock_codequery,
    mock_project_yaml,
    mock_redis,
    mock_reproduce_multiple,
    mock_llm,
    mock_crash_submit,
):
    """Create a VulnDiscoveryDeltaTask instance with mocked dependencies."""
    with (
        patch("buttercup.seed_gen.task.Task.get_llm", return_value=mock_llm),
    ):
        task = VulnDiscoveryDeltaTask(
            package_name="test_package",
            harness_name="test_harness",
            challenge_task=mock_challenge_task_with_diff,
            codequery=mock_codequery,
            project_yaml=mock_project_yaml,
            redis=mock_redis,
            reproduce_multiple=mock_reproduce_multiple,
            sarifs=[],
            crash_submit=mock_crash_submit,
        )

        return task


def test_do_task_no_valid_povs(
    vuln_discovery_task,
    mock_llm,
    mock_harness_info,
    tmp_path,
    mock_crash_submit,
    mock_reproduce_multiple,
):
    """Test successful execution of do_task method with no valid PoVs found"""
    out_dir = tmp_path / "out"
    current_dir = tmp_path / "current"
    out_dir.mkdir()
    current_dir.mkdir()

    vuln_discovery_task.get_harness_source = Mock(return_value=mock_harness_info)

    with (
        patch("buttercup.common.llm.get_langfuse_callbacks", return_value=[]),
        patch("opentelemetry.trace.get_tracer") as mock_tracer,
        patch("buttercup.seed_gen.vuln_base_task.set_crs_attributes") as mock_set_attrs,
        patch("buttercup.seed_gen.vuln_base_task.sandbox_exec_funcs") as mock_sandbox_exec,
    ):
        # Mock the tracer span
        mock_span = MagicMock()
        mock_tracer.return_value.start_as_current_span.return_value.__enter__.return_value = (
            mock_span
        )
        mock_sandbox_exec.side_effect = mock_sandbox_exec_funcs

        # Mock LLM responses for the workflow
        context_messages = [
            # Context gathering - first iteration
            AIMessage(
                content="I'll gather context about the vulnerability",
                tool_calls=[
                    ToolCall(
                        id="context_call_1",
                        name="get_function_definition",
                        args={"function_name": "vulnerable_function"},
                    )
                ],
            ),
            AIMessage(
                content="I need more context",
                tool_calls=[
                    ToolCall(
                        id="context_call_2",
                        name="get_type_definition",
                        args={"type_name": "buffer_t"},
                    )
                ],
            ),
            AIMessage(
                content="I need more context",
                tool_calls=[
                    ToolCall(
                        id="context_call_3",
                        name="cat",
                        args={"file_path": "/src/test.c"},
                    )
                ],
            ),
            AIMessage(
                content="I need more context",
                tool_calls=[
                    ToolCall(
                        id="context_call_4",
                        name="get_callers",
                        args={"function_name": "vulnerable_function", "file_path": "/src/test.c"},
                    )
                ],
            ),
            AIMessage(content="Making no tool calls for this context iteration"),
            AIMessage(
                content="Doing an empty batch tool call",
                tool_calls=[
                    ToolCall(
                        id="context_call_5",
                        name="batch_tool",
                        args={"tool_calls": {"calls": []}},
                    )
                ],
            ),
        ]

        vuln_messages = [
            # Bug analysis
            AIMessage(content="This is a buffer overflow vulnerability in the strcpy function"),
            # PoV writing
            AIMessage(
                content=(
                    "Here are the test functions:\n\n```python\ndef gen_test_case_1() -> bytes:\n"
                    '    return b"A" * 200  # Buffer overflow test case\n'
                    "def gen_test_case_2() -> bytes:\n"
                    '    return b"B" * 300  # Another buffer overflow test case\n```'
                ),
            ),
        ]
        # this works because there is 1 mock_llm instance for the test
        mock_llm.invoke.side_effect = (
            context_messages + vuln_messages * vuln_discovery_task.MAX_POV_ITERATIONS
        )

        # Mock codequery for tools
        vuln_discovery_task.codequery.get_functions = Mock(
            return_value=[
                MagicMock(
                    name="vulnerable_function",
                    file_path=Path("/src/test.c"),
                    bodies=[
                        MagicMock(
                            body="int vulnerable_function(char* input) { /* function body */ }"
                        )
                    ],
                )
            ]
        )
        vuln_discovery_task.codequery.get_types = Mock(
            return_value=[
                MagicMock(
                    file_path=Path("/src/test.c"),
                    definition="typedef struct { int size; char* data; } buffer_t;",
                )
            ]
        )
        vuln_discovery_task.codequery.get_callers = Mock(
            return_value=[
                MagicMock(
                    file_path=Path("/src/main.c"),
                    bodies=[
                        MagicMock(body='int main() { vulnerable_function("test"); return 0; }')
                    ],
                    name="main",
                )
            ]
        )

        # Mock challenge_task.exec_docker_cmd for cat tool
        vuln_discovery_task.challenge_task.exec_docker_cmd = Mock(
            return_value=MagicMock(
                success=True, output=b"int vulnerable_function(char* input) { /* function body */ }"
            )
        )

        vuln_discovery_task.do_task(out_dir, current_dir)

        mock_tracer.assert_called_once_with("buttercup.seed_gen.vuln_base_task")
        mock_set_attrs.assert_called_once()

        vuln_discovery_task.codequery.get_functions.assert_called()
        vuln_discovery_task.codequery.get_callers.assert_called()
        vuln_discovery_task.codequery.get_types.assert_called()
        vuln_discovery_task.challenge_task.exec_docker_cmd.assert_called()

        mock_sandbox_exec.assert_called()
        mock_reproduce_multiple.get_crashes.assert_called()

        for i in range(vuln_discovery_task.MAX_POV_ITERATIONS):
            iter_pov_files = list(out_dir.glob(f"iter{i}_*.seed"))
            assert (
                len(iter_pov_files) == 2
            ), f"Expected 2 seeds for iter{i}, found {len(iter_pov_files)}: {iter_pov_files}"

            # Check the content of the PoV files
            iter_pov1_file = next(f for f in iter_pov_files if "gen_seed_1" in f.name)
            iter_pov2_file = next(f for f in iter_pov_files if "gen_seed_2" in f.name)

            assert iter_pov1_file.read_bytes() == b"mock_seed_data_1"
            assert iter_pov2_file.read_bytes() == b"mock_seed_data_2"

        mock_crash_submit.crash_set.add.assert_not_called()
        mock_crash_submit.crash_queue.push.assert_not_called()
