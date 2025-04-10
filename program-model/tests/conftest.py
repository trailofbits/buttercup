import pytest
import subprocess
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
    # Clone real oss-fuzz repo into temp dir
    oss_fuzz_dir = tmp_path / "fuzz-tooling"
    oss_fuzz_dir.mkdir(parents=True)
    source_dir = tmp_path / "src"
    source_dir.mkdir(parents=True)

    subprocess.run(
        [
            "git",
            "-C",
            str(oss_fuzz_dir),
            "clone",
            "https://github.com/aixcc-finals/oss-fuzz-aixcc.git",
        ],
        check=True,
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
    )

    # Download project source code
    # Checkout specific project commit for reproducibility
    subprocess.run(["git", "-C", str(source_dir), "clone", project_url], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(source_dir / project),
            "checkout",
            project_commit,
        ],
        check=True,
    )

    # Create task metadata
    TaskMeta(
        project_name=oss_fuzz_project,
        focus=oss_fuzz_project,
        task_id=f"task-id-{oss_fuzz_project}",
    ).save(tmp_path)

    return ChallengeTask(
        read_only_task_dir=tmp_path,
        local_task_dir=tmp_path,
    )
