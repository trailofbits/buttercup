"""Shared test fixtures and utilities for seed-gen tests."""

from pathlib import Path
from unittest.mock import MagicMock, Mock

import pytest
from langchain_core.language_models import BaseChatModel
from redis import Redis

from buttercup.common.challenge_task import ChallengeTask
from buttercup.common.project_yaml import Language, ProjectYaml
from buttercup.common.task_meta import TaskMeta
from buttercup.program_model.codequery import CodeQueryPersistent
from buttercup.seed_gen.find_harness import HarnessInfo


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

    # Create a mock source file
    source_file = task_dir / "src" / "test.c"
    source_file.write_text("""#include <string.h>
#include <stdio.h>

int target_function(char* input) {
    char buffer[100];
    strcpy(buffer, input);
    printf("Processed: %s", buffer);
    return 0;
}

int main() {
    target_function("test");
    return 0;
}
""")

    challenge_task = ChallengeTask(read_only_task_dir=task_dir)
    return challenge_task


@pytest.fixture
def mock_challenge_task_with_diff(tmp_path):
    """Create a mock challenge task with diff support."""
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

    target_function(input);
    free(input);
    return 0;
}
""",
        harness_name="test_harness",
    )


def mock_sandbox_exec_funcs(functions: str, output_dir: Path):
    """Mock sandbox that writes seed files to the output directory."""
    # Check for strings that should be in python code
    assert "def " in functions
    assert "return" in functions

    seed1_path = output_dir / "gen_seed_1.seed"
    seed1_path.write_bytes(b"mock_seed_data_1")

    seed2_path = output_dir / "gen_seed_2.seed"
    seed2_path.write_bytes(b"mock_seed_data_2")


def pytest_addoption(parser):
    parser.addoption(
        "--runintegration", action="store_true", default=False, help="run integration tests"
    )


def pytest_configure(config):
    config.addinivalue_line("markers", "integration: mark test as an integration test")


def pytest_collection_modifyitems(config, items):
    if config.getoption("--runintegration"):
        # --runintegration given in cli: do not skip integration tests
        return
    skip_integration = pytest.mark.skip(reason="need --runintegration option to run")
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip_integration)
