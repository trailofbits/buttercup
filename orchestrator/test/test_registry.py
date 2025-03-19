import pytest
from buttercup.orchestrator.registry import TaskRegistry, CANCELLED_TASKS_SET
from buttercup.common.datastructures.msg_pb2 import Task, SourceDetail
from redis import Redis
import time
from typing import Set


@pytest.fixture
def redis_client():
    redis = Redis(host="localhost", port=6379, db=0)
    redis.flushdb()  # Clean the db before tests
    yield redis
    redis.flushdb()  # Clean the db after tests


@pytest.fixture
def task_registry(redis_client):
    return TaskRegistry(redis_client, hash_name="test_hash")


@pytest.fixture
def sample_task():
    task = Task()
    task.task_id = "test123"
    task.message_id = "msg_123"
    task.message_time = 1234567890
    task.task_type = Task.TaskType.TASK_TYPE_FULL
    task.deadline = 1234567899
    task.cancelled = False

    # Add a source detail
    source = task.sources.add()
    source.sha256 = "abc123"
    source.source_type = SourceDetail.SourceType.SOURCE_TYPE_REPO
    source.url = "https://github.com/example/repo"

    return task


def test_len(task_registry, sample_task):
    # Add some tasks directly
    task_registry.set(sample_task)
    task2 = Task(task_id="test456")
    task_registry.set(task2)

    assert len(task_registry) == 2


def test_contains(task_registry, sample_task):
    task_registry.set(sample_task)
    assert "TEST123" in task_registry
    assert "test123" in task_registry
    assert "NONEXISTENT" not in task_registry


def test_set_and_get_task(task_registry, sample_task):
    # Set the task
    task_registry.set(sample_task)

    # Get and verify
    retrieved_task = task_registry.get("test123")
    retrieved_task2 = task_registry.get("TEST123")
    assert retrieved_task == retrieved_task2

    # Verify all fields are preserved
    assert retrieved_task.task_id == sample_task.task_id
    assert retrieved_task.message_id == sample_task.message_id
    assert retrieved_task.message_time == sample_task.message_time
    assert retrieved_task.task_type == sample_task.task_type
    assert retrieved_task.deadline == sample_task.deadline
    assert retrieved_task.cancelled == sample_task.cancelled

    # Verify source details
    assert len(retrieved_task.sources) == 1
    source = retrieved_task.sources[0]
    assert source.sha256 == "abc123"
    assert source.source_type == SourceDetail.SourceType.SOURCE_TYPE_REPO
    assert source.url == "https://github.com/example/repo"


def test_get_nonexistent_task(task_registry):
    assert task_registry.get("nonexistent") is None


def test_delete_task(task_registry, sample_task):
    # Add and verify task exists
    task_registry.set(sample_task)
    assert "TEST123" in task_registry

    # Delete and verify it's gone
    task_registry.delete("test123")
    assert "TEST123" not in task_registry


def test_iter_tasks(task_registry, sample_task):
    # Add multiple tasks
    task_registry.set(sample_task)
    task2 = Task(task_id="test456", message_id="msg_456")
    task_registry.set(task2)

    tasks = list(task_registry)
    assert len(tasks) == 2
    assert all(isinstance(task, Task) for task in tasks)
    task_ids = {task.task_id for task in tasks}
    assert task_ids == {"test123", "test456"}


def test_iter_tasks_with_different_types(task_registry, redis_client):
    # Create and add two different tasks
    full_task = Task(task_id="full123", task_type=Task.TaskType.TASK_TYPE_FULL, message_id="msg_full", cancelled=False)
    delta_task = Task(
        task_id="delta456", task_type=Task.TaskType.TASK_TYPE_DELTA, message_id="msg_delta", cancelled=True
    )

    task_registry.set(full_task)
    task_registry.set(delta_task)

    # Add to cancelled set - this is now the source of truth for cancellation
    redis_client.sadd(CANCELLED_TASKS_SET, "delta456")

    assert len(task_registry) == 2

    # Verify we can get both types of tasks
    task_types = {task.task_type for task in task_registry}
    assert Task.TaskType.TASK_TYPE_FULL in task_types
    assert Task.TaskType.TASK_TYPE_DELTA in task_types

    # Verify cancelled state - should match the cancelled set
    cancelled_states = {task.cancelled for task in task_registry}
    assert True in cancelled_states
    assert False in cancelled_states

    # Verify specific tasks have correct cancelled state
    tasks = {task.task_id: task.cancelled for task in task_registry}
    assert tasks["full123"] is False
    assert tasks["delta456"] is True


def test_update_task(task_registry, sample_task, redis_client):
    # Set a task (cancelled flag doesn't matter)
    task_registry.set(sample_task)
    assert not task_registry.is_cancelled("test123")

    # Add to cancelled set (this is what actually matters)
    redis_client.sadd(CANCELLED_TASKS_SET, "test123")

    # Now it should be reported as cancelled
    assert task_registry.is_cancelled("test123")
    assert task_registry.get("test123").cancelled


def test_mark_cancelled(task_registry, sample_task, redis_client):
    # Add the task
    task_registry.set(sample_task)
    assert not task_registry.is_cancelled("test123")

    # Mark as cancelled
    task_registry.mark_cancelled(sample_task)

    # Check that the task_id is in the cancelled tasks set
    assert redis_client.sismember(CANCELLED_TASKS_SET, "test123")

    # Check that is_cancelled reports the task as cancelled
    assert task_registry.is_cancelled("test123")

    # The original task object should be unchanged
    assert not sample_task.cancelled

    # But the retrieved task should reflect the cancelled state from the set
    retrieved_task = task_registry.get("test123")
    assert retrieved_task.cancelled


def test_is_cancelled_with_set(task_registry, sample_task, redis_client):
    # Add the task
    task_registry.set(sample_task)

    # Initially not cancelled
    assert not task_registry.is_cancelled(sample_task)

    # Add to the cancelled set directly
    redis_client.sadd(CANCELLED_TASKS_SET, "test123")

    # Should now report as cancelled because of the set
    assert task_registry.is_cancelled(sample_task)

    # Get the task directly - the set status should be reflected
    retrieved_task = task_registry.get("test123")
    assert retrieved_task.cancelled


def test_delete_removes_from_set(task_registry, sample_task, redis_client):
    # Add and cancel the task
    task_registry.set(sample_task)
    task_registry.mark_cancelled(sample_task)

    # Verify it's in the set
    assert redis_client.sismember(CANCELLED_TASKS_SET, "test123")

    # Delete the task
    task_registry.delete("test123")

    # Verify it's removed from the set
    assert not redis_client.sismember(CANCELLED_TASKS_SET, "test123")


def test_is_expired(task_registry):
    """Test the is_expired function with different cases"""
    current_time = int(time.time())

    # Create an expired task
    expired_task = Task(
        task_id="expired-task",
        deadline=current_time - 1000,  # Deadline in the past
    )

    # Create a non-expired task
    live_task = Task(
        task_id="live-task",
        deadline=current_time + 1000,  # Deadline in the future
    )

    # Add tasks to the registry
    task_registry.set(expired_task)
    task_registry.set(live_task)

    # Test with task objects
    assert task_registry.is_expired(expired_task) is True
    assert task_registry.is_expired(live_task) is False

    # Test with task IDs
    assert task_registry.is_expired("expired-task") is True
    assert task_registry.is_expired("live-task") is False

    # Test with non-existent task ID
    assert task_registry.is_expired("non-existent-task") is False


def test_get_live_tasks(task_registry, redis_client):
    # Create a variety of tasks
    current_time = int(time.time())

    # Active task (not cancelled, not expired)
    live_task = Task(
        task_id="live-task",
        cancelled=False,  # cancelled flag doesn't matter, only the set
        deadline=current_time + 1000,
    )

    # Task not in cancelled set but with cancelled=True (should be ignored)
    ignored_cancelled_flag_task = Task(
        task_id="ignored-cancelled-flag",
        cancelled=True,  # This should be ignored since not in cancelled set
        deadline=current_time + 1000,
    )

    # Expired task
    expired_task = Task(task_id="expired-task", cancelled=False, deadline=current_time - 1000)

    # Task in cancelled set
    cancelled_task = Task(
        task_id="cancelled-task",
        cancelled=False,  # cancelled flag doesn't matter
        deadline=current_time + 1000,
    )

    # Add all tasks to registry
    task_registry.set(live_task)
    task_registry.set(ignored_cancelled_flag_task)
    task_registry.set(expired_task)
    task_registry.set(cancelled_task)

    # Add to cancelled set directly - only this matters for cancellation
    redis_client.sadd(CANCELLED_TASKS_SET, "cancelled-task")

    # Get live tasks
    live_tasks = task_registry.get_live_tasks()

    # Should include live_task and ignored_cancelled_flag_task
    assert len(live_tasks) == 2
    task_ids = {task.task_id for task in live_tasks}
    assert "live-task" in task_ids
    assert "ignored-cancelled-flag" in task_ids
    assert "expired-task" not in task_ids
    assert "cancelled-task" not in task_ids


def test_get_cancelled_task_ids(task_registry, redis_client):
    # Initially there are no cancelled tasks
    assert task_registry.get_cancelled_task_ids() == []

    # Add a few task IDs to the cancelled set
    redis_client.sadd(CANCELLED_TASKS_SET, "task1")
    redis_client.sadd(CANCELLED_TASKS_SET, "task2")
    redis_client.sadd(CANCELLED_TASKS_SET, "task3")

    # Get the cancelled task IDs
    cancelled_ids = task_registry.get_cancelled_task_ids()

    # Check that all expected IDs are in the result
    assert len(cancelled_ids) == 3
    assert set(cancelled_ids) == {"task1", "task2", "task3"}

    # Remove one task ID from the cancelled set
    redis_client.srem(CANCELLED_TASKS_SET, "task2")

    # Check that the removed ID is no longer in the result
    cancelled_ids = task_registry.get_cancelled_task_ids()
    assert len(cancelled_ids) == 2
    assert set(cancelled_ids) == {"task1", "task3"}


# Tests for should_stop_processing utility function


def test_should_stop_processing_with_cancelled_ids(task_registry):
    """Test that should_stop_processing handles cancelled_ids correctly."""
    # Create a set of cancelled IDs
    cancelled_ids: Set[str] = {"cancelled-task-1", "cancelled-task-2"}

    # Create tasks to test with
    cancelled_task1 = Task(task_id="cancelled-task-1", deadline=int(time.time()) + 3600)
    cancelled_task2 = Task(task_id="cancelled-task-2", deadline=int(time.time()) + 3600)
    active_task = Task(task_id="active-task", deadline=int(time.time()) + 3600)

    # Add tasks to registry
    task_registry.set(cancelled_task1)
    task_registry.set(cancelled_task2)
    task_registry.set(active_task)

    # Test with a task ID string that is in cancelled_ids
    result = task_registry.should_stop_processing("cancelled-task-1", cancelled_ids)
    assert result is True, "Should return True for task in cancelled_ids (string ID)"

    # Test with a Task object that is in cancelled_ids
    result = task_registry.should_stop_processing(cancelled_task2, cancelled_ids)
    assert result is True, "Should return True for task in cancelled_ids (Task object)"

    # Test with a task that is not in cancelled_ids
    result = task_registry.should_stop_processing("active-task", cancelled_ids)
    assert result is False, "Should return False for task not in cancelled_ids"


def test_should_stop_processing_no_cancelled_ids(task_registry, redis_client):
    """Test that should_stop_processing correctly uses is_cancelled when no cancelled_ids are provided."""
    current_time = int(time.time())

    # Create active task
    active_task = Task(task_id="active-task", deadline=current_time + 3600)
    task_registry.set(active_task)

    # Create cancelled task and add to cancelled set
    cancelled_task = Task(task_id="cancelled-task", deadline=current_time + 3600)
    task_registry.set(cancelled_task)
    redis_client.sadd(CANCELLED_TASKS_SET, "cancelled-task")

    # Test with a task ID string (no cancelled_ids)
    result = task_registry.should_stop_processing("active-task")
    assert result is False, "Should return False for non-cancelled, non-expired task"

    # Test with a Task object that is cancelled
    result = task_registry.should_stop_processing(cancelled_task)
    assert result is True, "Should return True for cancelled task"


def test_should_stop_processing_expired_task(task_registry):
    """Test that should_stop_processing returns True for expired tasks."""
    current_time = int(time.time())

    # Create an expired task (deadline in the past)
    expired_task = Task(task_id="expired-task", deadline=current_time - 3600)
    task_registry.set(expired_task)

    # Create an active task (deadline in the future)
    active_task = Task(task_id="active-task", deadline=current_time + 3600)
    task_registry.set(active_task)

    # Test with a task ID string that is expired
    result = task_registry.should_stop_processing("expired-task")
    assert result is True, "Should return True for expired task (string ID)"

    # Test with a Task object that is expired
    result = task_registry.should_stop_processing(expired_task)
    assert result is True, "Should return True for expired task (Task object)"

    # Test with a task that is not expired
    result = task_registry.should_stop_processing("active-task")
    assert result is False, "Should return False for non-expired task"
