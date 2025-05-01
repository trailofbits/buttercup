import pytest
import subprocess
import os
from unittest.mock import patch
from buttercup.program_model.api import Graph
from buttercup.program_model.graph import encode_value
from buttercup.common.challenge_task import ChallengeTask
from buttercup.common.task_meta import TaskMeta
from pathlib import Path


def is_cleanup_enabled(request) -> bool:
    """Check if the --no-cleanup flag was passed to pytest."""
    return not request.config.getoption("--no-cleanup")


def cleanup_graphdb(request, task_id: str):
    """Clean up the JanusGraph database by dropping vertices and edges associated with a specific task ID."""
    if not is_cleanup_enabled(request):
        return

    with Graph(url="ws://localhost:8182/gremlin") as graph:
        # Drop vertices and edges associated with the task ID
        graph.g.V().has(
            "task_id", encode_value(task_id.encode("utf-8"))
        ).drop().iterate()
        graph.g.E().has(
            "task_id", encode_value(task_id.encode("utf-8"))
        ).drop().iterate()


def pytest_addoption(parser):
    parser.addoption(
        "--runintegration",
        action="store_true",
        default=False,
        help="run integration tests",
    )
    parser.addoption(
        "--no-cleanup",
        action="store_true",
        default=False,
        help="do not clean up database before and after tests",
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


def oss_fuzz_task(
    tmp_path: Path,
    oss_fuzz_project: str,
    project: str,
    project_url: str,
    project_commit: str,
) -> ChallengeTask:
    """Create a challenge task using a real OSS-Fuzz repository."""
    oss_fuzz_dir = tmp_path / "fuzz-tooling"
    if not oss_fuzz_dir.exists():
        oss_fuzz_dir.mkdir(parents=True)

        # Clone real oss-fuzz repo into temp dir
        subprocess.run(
            [
                "git",
                "-C",
                str(oss_fuzz_dir),
                "clone",
                "https://github.com/aixcc-finals/oss-fuzz-aixcc.git",
            ],
            check=True,
            capture_output=True,
        )
        # Restore oss-fuzz project directory to specific commit
        subprocess.run(
            [
                "git",
                "-C",
                str(oss_fuzz_dir / "oss-fuzz-aixcc"),
                "checkout",
                "aixcc-afc",
                "--",
                f"projects/{oss_fuzz_project}",
            ],
            check=True,
            capture_output=True,
        )

    source_dir = tmp_path / "src"
    if not source_dir.exists():
        source_dir.mkdir(parents=True)

        # Download project source code
        subprocess.run(
            ["git", "-C", str(source_dir), "clone", project_url],
            check=True,
            capture_output=True,
        )
        # Checkout specific project commit for reproducibility
        subprocess.run(
            [
                "git",
                "-C",
                str(source_dir / project),
                "checkout",
                project_commit,
            ],
            check=True,
            capture_output=True,
        )

    # Create task metadata
    TaskMeta(
        project_name=oss_fuzz_project,
        focus=project,
        task_id=f"task-id-{oss_fuzz_project}",
        metadata={
            "task_id": f"task-id-{oss_fuzz_project}",
            "round_id": "testing",
            "team_id": "tob",
        },
    ).save(tmp_path)

    with patch.dict(os.environ, {"OSS_FUZZ_CONTAINER_ORG": "aixcc-afc"}):
        return ChallengeTask(
            read_only_task_dir=tmp_path,
            local_task_dir=tmp_path,
        )
