from pathlib import Path
from buttercup.common.challenge_task import ChallengeTask
from buttercup.common.task_meta import TaskMeta
from buttercup.patcher.utils import find_file_in_source_dir
import pytest


@pytest.fixture
def task_dir(tmp_path: Path) -> Path:
    """Create a mock challenge task directory structure."""
    # Create the task directory
    task_dir = tmp_path / "test-task-id-1"
    task_dir.mkdir(parents=True, exist_ok=True)

    # Create the main directories
    oss_fuzz = task_dir / "fuzz-tooling" / "my-oss-fuzz"
    source = task_dir / "src" / "my-source"
    diffs = task_dir / "diff" / "my-diff"

    oss_fuzz.mkdir(parents=True, exist_ok=True)
    source.mkdir(parents=True, exist_ok=True)
    diffs.mkdir(parents=True, exist_ok=True)

    # Create some mock patch files
    (diffs / "patch1.diff").write_text("mock patch 1")
    (diffs / "patch2.diff").write_text("mock patch 2")

    # Create a mock helper.py file
    helper_path = oss_fuzz / "infra/helper.py"
    helper_path.parent.mkdir(parents=True, exist_ok=True)
    helper_path.write_text("import sys;\nsys.exit(0)\n")

    # Create a mock test.txt file
    (source / "test.txt").write_text("mock test content")
    (source / "subdir").mkdir(parents=True, exist_ok=True)
    (source / "subdir2").mkdir(parents=True, exist_ok=True)
    (source / "subdir" / "test2.txt").write_text("mock test content 2")
    (source / "subdir" / "test.txt").write_text("mock test content 3")
    (source / "subdir" / "same_name.txt").write_text("mock test same content 1")
    (source / "subdir2" / "same_name.txt").write_text("mock test same content 2")
    (source / "d1" / "d2" / "d3").mkdir(parents=True, exist_ok=True)
    (source / "d1" / "d2" / "d3" / "test.txt").write_text("mock test content 4")

    # Create task metadata
    TaskMeta(
        project_name="example_project",
        focus="my-source",
        task_id="task-id-challenge-task",
        metadata={"task_id": "task-id-challenge-task", "round_id": "testing", "team_id": "tob"},
    ).save(task_dir)

    yield task_dir


@pytest.fixture
def mock_challenge_task(task_dir: Path) -> ChallengeTask:
    """Create a mock challenge task for testing."""
    return ChallengeTask(
        read_only_task_dir=task_dir,
        local_task_dir=task_dir,
    )


def test_find_file_in_source_dir_direct(mock_challenge_task: ChallengeTask):
    res = find_file_in_source_dir(mock_challenge_task, Path("test.txt"))
    assert res == Path("test.txt")


def test_find_file_in_source_dir_absolute(mock_challenge_task: ChallengeTask):
    res = find_file_in_source_dir(mock_challenge_task, Path("/src/example_project/test.txt"))
    assert res == Path("test.txt")


def test_find_file_in_source_dir_relative(mock_challenge_task: ChallengeTask):
    res = find_file_in_source_dir(mock_challenge_task, Path("src/example_project/test.txt"))
    assert res == Path("test.txt")


def test_find_file_in_source_dir_relative_subdir(mock_challenge_task: ChallengeTask):
    res = find_file_in_source_dir(mock_challenge_task, Path("src/example_project/subdir/test.txt"))
    assert res == Path("subdir/test.txt")
    res = find_file_in_source_dir(mock_challenge_task, Path("/src/example_project/subdir/test.txt"))
    assert res == Path("subdir/test.txt")


def test_find_file_fuzzy_search(mock_challenge_task: ChallengeTask):
    res = find_file_in_source_dir(mock_challenge_task, Path("test2.txt"))
    assert res == Path("subdir/test2.txt")

    res = find_file_in_source_dir(mock_challenge_task, Path("d2/d3/test.txt"))
    assert res == Path("d1/d2/d3/test.txt")

    # The path is wrong, we don't want to match this
    res = find_file_in_source_dir(mock_challenge_task, Path("d3/d2/test.txt"))
    assert res is None

    # The path is wrong, we don't want to match this
    res = find_file_in_source_dir(mock_challenge_task, Path("d2/d3/test-nonexistent.txt"))
    assert res is None
