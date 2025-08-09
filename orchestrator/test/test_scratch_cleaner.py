import os
import shutil
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from redis import Redis

from buttercup.orchestrator.scratch_cleaner.scratch_cleaner import ScratchCleaner
from buttercup.common.task_registry import TaskRegistry
from buttercup.common.datastructures.msg_pb2 import Task


@pytest.fixture
def temp_scratch_dir(tmp_path: Path) -> Path:
    """Create a temporary scratch directory for testing."""
    scratch_dir = tmp_path / "scratch"
    scratch_dir.mkdir()
    yield scratch_dir
    shutil.rmtree(scratch_dir, ignore_errors=True)


@pytest.fixture
def mock_redis() -> MagicMock:
    """Create a mock Redis instance."""
    return MagicMock(spec=Redis)


@pytest.fixture
def mock_task_registry(mock_redis: MagicMock) -> MagicMock:
    """Create a mock TaskRegistry."""
    return MagicMock(spec=TaskRegistry)


@pytest.fixture
def scratch_cleaner(temp_scratch_dir: Path, mock_redis: MagicMock, mock_task_registry: MagicMock) -> ScratchCleaner:
    """Create a ScratchCleaner instance with mocked dependencies."""
    cleaner = ScratchCleaner(
        redis=mock_redis, scratch_dir=temp_scratch_dir, sleep_time=0.1, delete_old_tasks_scratch_delta_seconds=1
    )
    cleaner.task_registry = mock_task_registry
    return cleaner


def test_scratch_cleaner_initialization(scratch_cleaner: ScratchCleaner, mock_redis: MagicMock):
    """Test that ScratchCleaner initializes correctly."""
    assert scratch_cleaner.redis == mock_redis
    assert isinstance(scratch_cleaner.task_registry, TaskRegistry)
    assert scratch_cleaner.sleep_time == 0.1
    assert scratch_cleaner.delete_old_tasks_scratch_delta_seconds == 1


def test_serve_item_no_tasks(scratch_cleaner: ScratchCleaner, mock_task_registry: MagicMock):
    """Test serve_item when there are no tasks."""
    mock_task_registry.__iter__.return_value = []
    assert not scratch_cleaner.serve_item()


def test_serve_item_no_expired_tasks(scratch_cleaner: ScratchCleaner, mock_task_registry: MagicMock):
    """Test serve_item when there are no expired tasks."""
    task = Task(task_id="test-task")
    mock_task_registry.__iter__.return_value = [task]
    mock_task_registry.is_expired.return_value = False

    assert not scratch_cleaner.serve_item()
    mock_task_registry.is_expired.assert_called_once_with(task, delta_seconds=1)


def test_serve_item_expired_task_no_dir(
    scratch_cleaner: ScratchCleaner, mock_task_registry: MagicMock, temp_scratch_dir: Path
):
    """Test serve_item when there is an expired task but no directory."""
    task = Task(task_id="test-task")
    mock_task_registry.__iter__.return_value = [task]
    mock_task_registry.is_expired.return_value = True

    assert not scratch_cleaner.serve_item()
    assert not (temp_scratch_dir / "test-task").exists()


def test_serve_item_expired_task_with_dir(
    scratch_cleaner: ScratchCleaner, mock_task_registry: MagicMock, temp_scratch_dir: Path
):
    """Test serve_item when there is an expired task with a directory."""
    task = Task(task_id="test-task")
    mock_task_registry.__iter__.return_value = [task]
    mock_task_registry.is_expired.return_value = True

    # Create a task directory
    task_dir = temp_scratch_dir / "test-task"
    task_dir.mkdir()
    test_file = task_dir / "test.txt"
    test_file.write_text("test")

    assert scratch_cleaner.serve_item()
    assert not task_dir.exists()


def test_serve_item_multiple_tasks(
    scratch_cleaner: ScratchCleaner, mock_task_registry: MagicMock, temp_scratch_dir: Path
):
    """Test serve_item with multiple tasks, some expired and some not."""
    tasks = [Task(task_id="expired-1"), Task(task_id="not-expired"), Task(task_id="expired-2")]
    mock_task_registry.__iter__.return_value = tasks

    def is_expired(task: Task, delta_seconds: int) -> bool:
        return task.task_id.startswith("expired")

    mock_task_registry.is_expired.side_effect = is_expired

    # Create directories for all tasks
    for task in tasks:
        (temp_scratch_dir / task.task_id).mkdir()
        (temp_scratch_dir / task.task_id / "test.txt").write_text("test")

    assert scratch_cleaner.serve_item()

    # Check that only expired directories were deleted
    assert not (temp_scratch_dir / "expired-1").exists()
    assert (temp_scratch_dir / "not-expired").exists()
    assert not (temp_scratch_dir / "expired-2").exists()


def test_serve_item_delete_failure(
    scratch_cleaner: ScratchCleaner, mock_task_registry: MagicMock, temp_scratch_dir: Path
):
    """Test serve_item when directory deletion fails (but it should be just ignored)."""
    task = Task(task_id="test-task")
    mock_task_registry.__iter__.return_value = [task]
    mock_task_registry.is_expired.return_value = True

    # Create a task directory
    task_dir = temp_scratch_dir / "test-task"
    task_dir.mkdir()
    test_file = task_dir / "test.txt"
    test_file.write_text("test")

    # Make the directory read-only to cause deletion failure
    os.chmod(task_dir, 0o444)

    assert scratch_cleaner.serve_item()
    assert task_dir.exists()

    # Clean up
    os.chmod(task_dir, 0o777)
