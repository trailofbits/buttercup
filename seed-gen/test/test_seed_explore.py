"""Tests for SeedExploreTask"""

from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest
from langchain_core.messages import AIMessage
from langchain_core.messages.tool import ToolCall

from buttercup.seed_gen.seed_explore import SeedExploreTask
from test.conftest import (
    mock_sandbox_exec_funcs,
)


@pytest.fixture
def seed_explore_task(
    mock_challenge_task,
    mock_codequery,
    mock_project_yaml,
    mock_redis,
    mock_llm,
):
    """Create a SeedExploreTask instance with mocked dependencies."""
    with (
        patch("buttercup.seed_gen.task.Task.get_llm", return_value=mock_llm),
    ):
        task = SeedExploreTask(
            package_name="test_package",
            harness_name="test_harness",
            challenge_task=mock_challenge_task,
            codequery=mock_codequery,
            project_yaml=mock_project_yaml,
            redis=mock_redis,
        )

        return task


def test_do_task_success(
    seed_explore_task,
    mock_llm,
    mock_harness_info,
    tmp_path,
):
    """Test successful execution of do_task method"""
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    seed_explore_task.get_harness_source = Mock(return_value=mock_harness_info)

    with (
        patch("buttercup.common.llm.get_langfuse_callbacks", return_value=[]),
        patch("opentelemetry.trace.get_tracer") as mock_tracer,
        patch("buttercup.seed_gen.seed_explore.set_crs_attributes") as mock_set_attrs,
        patch("buttercup.seed_gen.task.sandbox_exec_funcs") as mock_sandbox_exec,
    ):
        # Mock the tracer span
        mock_span = MagicMock()
        mock_tracer.return_value.start_as_current_span.return_value.__enter__.return_value = (
            mock_span
        )
        mock_sandbox_exec.side_effect = mock_sandbox_exec_funcs

        # Mock LLM responses for the workflow
        context_messages = [
            AIMessage(
                content="I'll gather context about the target function",
                tool_calls=[
                    ToolCall(
                        id="context_call_1",
                        name="get_function_definition",
                        args={"function_name": "target_function"},
                    )
                ],
            ),
            AIMessage(
                content="I need more context",
                tool_calls=[
                    ToolCall(
                        id="context_call_2",
                        name="cat",
                        args={"file_path": "/src/test.c"},
                    )
                ],
            ),
            AIMessage(
                content="I need more context",
                tool_calls=[
                    ToolCall(
                        id="context_call_3",
                        name="get_callers",
                        args={
                            "function_name": "target_function",
                            "file_path": "/src/test.c",
                        },
                    )
                ],
            ),
            AIMessage(
                content="Doing a batch tool call with multiple tools",
                tool_calls=[
                    ToolCall(
                        id="context_call_4",
                        name="batch_tool",
                        args={
                            "tool_calls": {
                                "calls": [
                                    {
                                        "tool_name": "get_function_definition",
                                        "arguments": {"function_name": "target_function"},
                                    },
                                    {
                                        "tool_name": "get_type_definition",
                                        "arguments": {"type_name": "buffer_t"},
                                    },
                                ]
                            }
                        },
                    )
                ],
            ),
        ]

        seed_messages = [
            # Seed generation
            AIMessage(
                content=(
                    "Here are the seed functions:\n\n```python\n"
                    "def gen_seed_1() -> bytes:\n"
                    '    return b"A" * 50  # Simple test case\n\n'
                    "def gen_seed_2() -> bytes:\n"
                    '    return b"B" * 100  # Another test case\n```'
                ),
            ),
        ]
        mock_llm.invoke.side_effect = context_messages + seed_messages

        # Mock codequery for tools
        seed_explore_task.codequery.get_functions = Mock(
            return_value=[
                MagicMock(
                    name="target_function",
                    file_path=Path("/src/test.c"),
                    bodies=[
                        MagicMock(body="int target_function(char* input) { /* function body */ }")
                    ],
                )
            ]
        )
        seed_explore_task.codequery.get_callers = Mock(
            return_value=[
                MagicMock(
                    file_path=Path("/src/main.c"),
                    bodies=[MagicMock(body='int main() { target_function("test"); return 0; }')],
                    name="main",
                )
            ]
        )
        seed_explore_task.codequery.get_types = Mock(
            return_value=[
                MagicMock(
                    name="buffer_t",
                    file_path=Path("/src/types.h"),
                    definition="typedef struct { char* data; size_t size; } buffer_t;",
                )
            ]
        )

        # Mock challenge_task.exec_docker_cmd for cat tool
        seed_explore_task.challenge_task.exec_docker_cmd = Mock(
            return_value=MagicMock(
                success=True, output=b"int target_function(char* input) { /* function body */ }"
            )
        )

        seed_explore_task.do_task("target_function", [Path("/src/test.c")], out_dir)

        mock_tracer.assert_called_once_with("buttercup.seed_gen.seed_explore")
        mock_set_attrs.assert_called_once()

        mock_sandbox_exec.assert_called()

        seed_explore_task.codequery.get_functions.assert_called()
        seed_explore_task.codequery.get_callers.assert_called()
        seed_explore_task.codequery.get_types.assert_called()
        seed_explore_task.challenge_task.exec_docker_cmd.assert_called()

        # Check that seed files were created
        seed_files = list(out_dir.glob("*.seed"))
        assert len(seed_files) == 2, f"Expected 2 seed files, found {len(seed_files)}: {seed_files}"

        # Check the content of the seed files
        seed1_file = next(f for f in seed_files if "gen_seed_1" in f.name)
        seed2_file = next(f for f in seed_files if "gen_seed_2" in f.name)

        assert seed1_file.read_bytes() == b"mock_seed_data_1"
        assert seed2_file.read_bytes() == b"mock_seed_data_2"
