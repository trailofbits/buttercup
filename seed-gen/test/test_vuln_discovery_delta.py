"""Tests for VulnDiscoveryDeltaTask"""

from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.messages.tool import ToolCall
from redis import Redis

from buttercup.common.challenge_task import ChallengeTask
from buttercup.common.project_yaml import Language, ProjectYaml
from buttercup.common.reproduce_multiple import ReproduceMultiple
from buttercup.common.task_meta import TaskMeta
from buttercup.program_model.codequery import CodeQueryPersistent
from buttercup.seed_gen.find_harness import HarnessInfo
from buttercup.seed_gen.vuln_discovery_delta import VulnDiscoveryDeltaTask


@pytest.fixture
def mock_llm():
    """Create a mock LLM"""
    llm = MagicMock(spec=BaseChatModel)
    llm.model_name = "claude-4-sonnet"
    llm.bind_tools.return_value = llm
    llm.with_fallbacks.return_value = llm
    return llm


@pytest.fixture
def mock_challenge_task(tmp_path):
    """Create a mock challenge task."""
    task_dir = tmp_path / "test-challenge"
    task_dir.mkdir(parents=True)

    # Create required directories
    (task_dir / "src").mkdir()
    (task_dir / "fuzz-tooling").mkdir()
    (task_dir / "diff").mkdir()

    # Create a mock project.yaml
    project_yaml_path = task_dir / "fuzz-tooling" / "projects" / "test_project" / "project.yaml"
    project_yaml_path.parent.mkdir(parents=True)
    project_yaml_path.write_text("""name: test_project
language: c
""")

    # Create a mock helper.py in infra/infra/helper.py
    helper_path = task_dir / "fuzz-tooling" / "infra" / "infra" / "helper.py"
    helper_path.parent.mkdir(parents=True)
    helper_path.write_text("import sys; sys.exit(0)")

    # Create task metadata
    TaskMeta(
        project_name="test_project",
        focus="test-source",
        task_id="test-task-id",
        metadata={"task_id": "test-task-id", "round_id": "testing", "team_id": "tob"},
    ).save(task_dir)

    # Create a mock diff file
    diff_file = task_dir / "diff" / "test.diff"
    diff_file.write_text("""--- a/src/test.c
+++ b/src/test.c
@@ -10,6 +10,7 @@ int vulnerable_function(char* input) {
    char buffer[100];
    strcpy(buffer, input);  // Potential buffer overflow
+    printf(\"Processed: %s\", buffer);
    return 0;
}
""")

    # Create a mock source file
    source_file = task_dir / "src" / "test.c"
    source_file.write_text("""#include <string.h>
#include <stdio.h>

int vulnerable_function(char* input) {
    char buffer[100];
    strcpy(buffer, input);  // Potential buffer overflow
    printf(\"Processed: %s\", buffer);
    return 0;
}

int main() {
    vulnerable_function(\"test\");
    return 0;
}
""")

    challenge_task = ChallengeTask(read_only_task_dir=task_dir)
    challenge_task.is_delta_mode = Mock(return_value=True)
    challenge_task.get_diffs = Mock(return_value=[diff_file])

    return challenge_task


@pytest.fixture
def mock_codequery():
    """Create a mock CodeQueryPersistent."""
    codequery = MagicMock(spec=CodeQueryPersistent)
    return codequery


@pytest.fixture
def mock_project_yaml():
    """Create a mock ProjectYaml."""
    project_yaml = MagicMock(spec=ProjectYaml)
    project_yaml.unified_language = Language.C
    return project_yaml


@pytest.fixture
def mock_redis():
    """Create a mock Redis instance."""
    return MagicMock(spec=Redis)


@pytest.fixture
def mock_reproduce_multiple():
    """Create a mock ReproduceMultiple."""
    reproduce_multiple = MagicMock(spec=ReproduceMultiple)

    @contextmanager
    def mock_context():
        yield reproduce_multiple

    reproduce_multiple.open = mock_context
    reproduce_multiple.get_crashes = Mock(return_value=[])

    return reproduce_multiple


@pytest.fixture
def vuln_discovery_task(
    mock_challenge_task,
    mock_codequery,
    mock_project_yaml,
    mock_redis,
    mock_reproduce_multiple,
    mock_llm,
):
    """Create a VulnDiscoveryDeltaTask instance with mocked dependencies."""
    with (
        patch("buttercup.seed_gen.task.Task.get_llm", return_value=mock_llm),
    ):
        task = VulnDiscoveryDeltaTask(
            package_name="test_package",
            harness_name="test_harness",
            challenge_task=mock_challenge_task,
            codequery=mock_codequery,
            project_yaml=mock_project_yaml,
            redis=mock_redis,
            reproduce_multiple=mock_reproduce_multiple,
            sarifs=[],
            crash_submit=None,
        )

        return task


@pytest.fixture
def mock_harness_info():
    """Create mock harness info."""
    return HarnessInfo(
        file_path=Path("/src/test_harness.c"),
        code="""#include <stdint.h>
#include <stdlib.h>

int LLVMFuzzerTestOneInput(const uint8_t *data, size_t size) {
    if (size < 1) return 0;

    char* input = malloc(size + 1);
    memcpy(input, data, size);
    input[size] = '\\0';

    vulnerable_function(input);
    free(input);
    return 0;
}
""",
        harness_name="test_harness",
    )


def mock_sandbox_exec_funcs(functions: str, output_dir: Path):
    """Mock sandbox that writes PoV files to the output directory."""
    # Check for strings that should be in python code
    assert "def " in functions
    assert "return" in functions

    pov1_path = output_dir / "gen_test_case_1.seed"
    pov1_path.write_bytes(b"mock_pov_data_1")

    pov2_path = output_dir / "gen_test_case_2.seed"
    pov2_path.write_bytes(b"mock_pov_data_2")


def test_do_task_no_valid_povs(
    vuln_discovery_task,
    mock_llm,
    mock_harness_info,
    tmp_path,
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

        mock_sandbox_exec.assert_called()

        for i in range(vuln_discovery_task.MAX_POV_ITERATIONS):
            iter_pov_files = list(out_dir.glob(f"iter{i}_*.seed"))
            assert (
                len(iter_pov_files) == 2
            ), f"Expected 2 PoV files for iter{i}, found {len(iter_pov_files)}: {iter_pov_files}"

            # Check the content of the PoV files
            iter_pov1_file = next(f for f in iter_pov_files if "gen_test_case_1" in f.name)
            iter_pov2_file = next(f for f in iter_pov_files if "gen_test_case_2" in f.name)

            assert iter_pov1_file.read_bytes() == b"mock_pov_data_1"
            assert iter_pov2_file.read_bytes() == b"mock_pov_data_2"
