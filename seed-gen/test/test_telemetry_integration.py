"""Integration tests with openlit telemetry enabled.

These tests verify seed-gen works correctly when openlit instrumentation is active,
as it would be in production when OTEL_EXPORTER_OTLP_ENDPOINT is set.
"""

from unittest.mock import MagicMock, Mock, patch

import openlit
import pytest
from langchain_core.messages import AIMessage

from buttercup.seed_gen.seed_init import SeedInitTask
from test.conftest import mock_sandbox_exec_funcs

# Initialize openlit at module load to enable instrumentation
# This simulates production where init_telemetry() is called at startup
openlit.init(
    disable_batch=True,
    otlp_endpoint=None,
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
    with patch("buttercup.seed_gen.task.Task.get_llm", return_value=mock_llm):
        task = SeedInitTask(
            package_name="test_package",
            harness_name="test_harness",
            challenge_task=mock_challenge_task,
            codequery=mock_codequery,
            project_yaml=mock_project_yaml,
            redis=mock_redis,
        )
        return task


def test_do_task_with_telemetry(
    seed_init_task,
    mock_llm,
    mock_harness_info,
    mock_llm_responses,
    mock_codequery_responses,
    mock_challenge_task_responses,
    tmp_path,
):
    """Test seed-gen do_task works with openlit telemetry enabled."""
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    seed_init_task.get_harness_source = Mock(return_value=mock_harness_info)

    with (
        patch("buttercup.common.llm.get_langfuse_callbacks", return_value=[]),
        patch("opentelemetry.trace.get_tracer") as mock_tracer,
        patch("buttercup.seed_gen.seed_init.set_crs_attributes"),
        patch("buttercup.seed_gen.task.sandbox_exec_funcs") as mock_sandbox_exec,
    ):
        mock_span = MagicMock()
        mock_tracer.return_value.start_as_current_span.return_value.__enter__.return_value = mock_span
        mock_sandbox_exec.side_effect = mock_sandbox_exec_funcs

        seed_messages = [
            AIMessage(
                content=(
                    "```python\n"
                    "def gen_seed_1() -> bytes:\n"
                    '    return b"A" * 50\n\n'
                    "def gen_seed_2() -> bytes:\n"
                    '    return b"B" * 100\n```'
                ),
            ),
        ]
        mock_llm.invoke.side_effect = mock_llm_responses + seed_messages

        seed_init_task.codequery.get_functions = Mock(
            return_value=mock_codequery_responses["get_functions"],
        )
        seed_init_task.codequery.get_callers = Mock(
            return_value=mock_codequery_responses["get_callers"],
        )
        seed_init_task.codequery.get_types = Mock(
            return_value=mock_codequery_responses["get_types"],
        )
        seed_init_task.challenge_task.exec_docker_cmd = Mock(
            return_value=mock_challenge_task_responses["exec_docker_cmd"],
        )

        seed_init_task.do_task(out_dir)

        seed_files = list(out_dir.glob("*.seed"))
        assert len(seed_files) == 2
