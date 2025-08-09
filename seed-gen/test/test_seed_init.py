"""Tests for SeedInitTask"""

from unittest.mock import MagicMock, Mock, patch

import pytest
from langchain_core.messages import AIMessage

from buttercup.seed_gen.seed_init import SeedInitTask
from test.conftest import (
    mock_sandbox_exec_funcs,
)


@pytest.fixture
def seed_init_task(
    mock_challenge_task,
    mock_codequery,
    mock_project_yaml,
    mock_redis,
    mock_llm,
):
    """Create a SeedInitTask instance with mocked dependencies."""
    with (
        patch("buttercup.seed_gen.task.Task.get_llm", return_value=mock_llm),
    ):
        task = SeedInitTask(
            package_name="test_package",
            harness_name="test_harness",
            challenge_task=mock_challenge_task,
            codequery=mock_codequery,
            project_yaml=mock_project_yaml,
            redis=mock_redis,
        )

        return task


def test_do_task_success(
    seed_init_task,
    mock_llm,
    mock_harness_info,
    mock_llm_responses,
    mock_codequery_responses,
    mock_challenge_task_responses,
    tmp_path,
):
    """Test successful execution of do_task method"""
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    seed_init_task.get_harness_source = Mock(return_value=mock_harness_info)

    with (
        patch("buttercup.common.llm.get_langfuse_callbacks", return_value=[]),
        patch("opentelemetry.trace.get_tracer") as mock_tracer,
        patch("buttercup.seed_gen.seed_init.set_crs_attributes") as mock_set_attrs,
        patch("buttercup.seed_gen.task.sandbox_exec_funcs") as mock_sandbox_exec,
    ):
        # Mock the tracer span
        mock_span = MagicMock()
        mock_tracer.return_value.start_as_current_span.return_value.__enter__.return_value = mock_span
        mock_sandbox_exec.side_effect = mock_sandbox_exec_funcs

        # Mock LLM responses for the workflow
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
        mock_llm.invoke.side_effect = mock_llm_responses + seed_messages

        # Mock codequery for tools
        seed_init_task.codequery.get_functions = Mock(return_value=mock_codequery_responses["get_functions"])
        seed_init_task.codequery.get_callers = Mock(return_value=mock_codequery_responses["get_callers"])
        seed_init_task.codequery.get_types = Mock(return_value=mock_codequery_responses["get_types"])

        # Mock challenge_task.exec_docker_cmd for cat tool
        seed_init_task.challenge_task.exec_docker_cmd = Mock(
            return_value=mock_challenge_task_responses["exec_docker_cmd"]
        )

        seed_init_task.do_task(out_dir)

        mock_tracer.assert_called_once_with("buttercup.seed_gen.seed_init")
        mock_set_attrs.assert_called_once()

        mock_sandbox_exec.assert_called()

        seed_init_task.codequery.get_functions.assert_called()
        seed_init_task.codequery.get_callers.assert_called()
        seed_init_task.codequery.get_types.assert_called()
        seed_init_task.challenge_task.exec_docker_cmd.assert_called()

        # Check that seed files were created
        seed_files = list(out_dir.glob("*.seed"))
        assert len(seed_files) == 2, f"Expected 2 seed files, found {len(seed_files)}: {seed_files}"

        # Check the content of the seed files
        seed1_file = next(f for f in seed_files if "gen_seed_1" in f.name)
        seed2_file = next(f for f in seed_files if "gen_seed_2" in f.name)

        assert seed1_file.read_bytes() == b"mock_seed_data_1"
        assert seed2_file.read_bytes() == b"mock_seed_data_2"
