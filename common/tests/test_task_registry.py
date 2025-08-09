import pytest
from unittest.mock import Mock
from buttercup.common.task_registry import TaskRegistry, CANCELLED_TASKS_SET, SUCCEEDED_TASKS_SET, ERRORED_TASKS_SET
from buttercup.common.datastructures.msg_pb2 import Task, SourceDetail
import time
from typing import Set
from redis import Redis
from unittest.mock import patch


@pytest.fixture
def redis_client():
    # Create a mock Redis client instead of connecting to a real one
    mock_redis = Mock(spec=Redis)

    # Mock key methods
    mock_redis.hlen.return_value = 0
    mock_redis.hexists.return_value = False
    mock_redis.hget.return_value = None
    mock_redis.hgetall.return_value = {}
    mock_redis.sismember.return_value = False
    mock_redis.smembers.return_value = []

    # For pipeline operations
    mock_pipeline = Mock()
    mock_pipeline.hdel.return_value = mock_pipeline
    mock_pipeline.srem.return_value = mock_pipeline
    mock_pipeline.execute.return_value = [1, 1]
    mock_redis.pipeline.return_value = mock_pipeline

    return mock_redis


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


def test_len(task_registry, sample_task, redis_client):
    # Setup
    redis_client.hlen.return_value = 2

    # Add some tasks directly
    task_registry.set(sample_task)
    task2 = Task(task_id="test456")
    task_registry.set(task2)

    # Test
    assert len(task_registry) == 2
    redis_client.hlen.assert_called_once_with(task_registry.hash_name)


def test_contains(task_registry, sample_task, redis_client):
    # Setup
    redis_client.hexists.side_effect = lambda hash_name, key: key.lower() == "test123"

    # Test
    task_registry.set(sample_task)
    assert "TEST123" in task_registry
    assert "test123" in task_registry
    assert "NONEXISTENT" not in task_registry


def test_set_and_get_task(task_registry, sample_task, redis_client):
    # Setup
    def mock_hget(hash_name, key):
        if key.lower() == "test123":
            return sample_task.SerializeToString()
        return None

    redis_client.hget.side_effect = mock_hget

    # Set the task
    task_registry.set(sample_task)

    # Verify hset was called with the right arguments
    redis_client.hset.assert_called_with(task_registry.hash_name, "test123", sample_task.SerializeToString())

    # Get and verify
    retrieved_task = task_registry.get("test123")
    _retrieved_task = task_registry.get("TEST123")

    # Verify fields match
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


def test_get_nonexistent_task(task_registry, redis_client):
    # Setup
    redis_client.hget.return_value = None

    # Test
    assert task_registry.get("nonexistent") is None
    redis_client.hget.assert_called_with(task_registry.hash_name, "nonexistent")


def test_delete_task(task_registry, sample_task, redis_client):
    # Setup
    redis_client.hexists.side_effect = lambda hash_name, key: key.lower() == "test123"

    # Test
    # Add and verify task exists
    task_registry.set(sample_task)
    assert "TEST123" in task_registry

    # Delete and verify it's gone
    task_registry.delete("test123")

    # Verify that pipeline operations were called
    pipeline = redis_client.pipeline.return_value
    pipeline.hdel.assert_called_once_with(task_registry.hash_name, "test123")
    pipeline.srem.assert_called_once_with(CANCELLED_TASKS_SET, "test123")
    pipeline.execute.assert_called_once()


def test_iter_tasks(task_registry, sample_task, redis_client):
    # Setup
    task2 = Task(task_id="test456", message_id="msg_456")

    # Mock hgetall to return our tasks
    mock_dict = {b"test123": sample_task.SerializeToString(), b"test456": task2.SerializeToString()}
    redis_client.hgetall.return_value = mock_dict
    redis_client.smembers.return_value = []

    # Test
    tasks = list(task_registry)

    # Verify
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

    # Setup Redis mock
    mock_dict = {b"full123": full_task.SerializeToString(), b"delta456": delta_task.SerializeToString()}
    redis_client.hgetall.return_value = mock_dict

    # Setup cancelled set to include delta456
    redis_client.smembers.return_value = [b"delta456"]

    # Test
    tasks = list(task_registry)

    # Verify
    assert len(tasks) == 2

    # Verify we can get both types of tasks
    task_types = {task.task_type for task in tasks}
    assert Task.TaskType.TASK_TYPE_FULL in task_types
    assert Task.TaskType.TASK_TYPE_DELTA in task_types

    # Verify cancelled state - should match the cancelled set
    cancelled_states = {task.cancelled for task in tasks}
    assert True in cancelled_states
    assert False in cancelled_states

    # Verify specific tasks have correct cancelled state
    tasks_dict = {task.task_id: task for task in tasks}
    assert not tasks_dict["full123"].cancelled
    assert tasks_dict["delta456"].cancelled


def test_update_task(task_registry, sample_task, redis_client):
    # Setup for is_cancelled and get
    redis_client.sismember.side_effect = lambda set_name, key: False
    redis_client.hget.return_value = sample_task.SerializeToString()

    # Set a task (cancelled flag doesn't matter)
    task_registry.set(sample_task)
    assert not task_registry.is_cancelled("test123")

    # Add to cancelled set (this is what actually matters)
    redis_client.sismember.side_effect = lambda set_name, key: key.lower() == "test123"

    # Now it should be reported as cancelled
    assert task_registry.is_cancelled("test123")

    # Get will now return a task with cancelled=True
    task_with_cancelled = Task()
    task_with_cancelled.CopyFrom(sample_task)
    task_with_cancelled.cancelled = True
    redis_client.hget.return_value = sample_task.SerializeToString()

    # Reset sismember for the get operation (which checks for cancelled flag)
    redis_client.sismember.side_effect = lambda set_name, key: key.lower() == "test123"

    # Get the task and verify it shows as cancelled
    retrieved_task = task_registry.get("test123")
    assert retrieved_task.cancelled


def test_mark_cancelled(task_registry, sample_task, redis_client):
    # Setup
    redis_client.sismember.return_value = False

    # Add the task
    task_registry.set(sample_task)
    assert not task_registry.is_cancelled("test123")

    # Mark as cancelled
    task_registry.mark_cancelled(sample_task)

    # Check that the task_id is in the cancelled tasks set
    redis_client.sadd.assert_called_once_with(CANCELLED_TASKS_SET, "test123")

    # Make is_cancelled return True now
    redis_client.sismember.return_value = True

    # Check that is_cancelled reports the task as cancelled
    assert task_registry.is_cancelled("test123")

    # The original task object should be unchanged
    assert not sample_task.cancelled

    # But the retrieved task should reflect the cancelled state from the set
    redis_client.hget.return_value = sample_task.SerializeToString()
    retrieved_task = task_registry.get("test123")
    assert retrieved_task.cancelled


def test_is_cancelled_with_set(task_registry, sample_task, redis_client):
    # Setup
    redis_client.sismember.return_value = False

    # Add the task
    task_registry.set(sample_task)

    # Initially not cancelled
    assert not task_registry.is_cancelled(sample_task)

    # Add to the cancelled set directly (mock it)
    redis_client.sismember.return_value = True

    # Should now report as cancelled because of the set
    assert task_registry.is_cancelled(sample_task)

    # Get the task directly - the set status should be reflected
    redis_client.hget.return_value = sample_task.SerializeToString()
    retrieved_task = task_registry.get("test123")
    assert retrieved_task.cancelled


def test_delete_removes_from_set(task_registry, sample_task, redis_client):
    # Set up
    redis_client.sismember.return_value = True

    # Add and cancel the task
    task_registry.set(sample_task)
    task_registry.mark_cancelled(sample_task)

    # Verify it's in the set
    assert task_registry.is_cancelled("test123")

    # Delete the task
    task_registry.delete("test123")

    # Verify that pipeline operations were called
    pipeline = redis_client.pipeline.return_value
    pipeline.hdel.assert_called_once_with(task_registry.hash_name, "test123")
    pipeline.srem.assert_called_once_with(CANCELLED_TASKS_SET, "test123")
    pipeline.execute.assert_called_once()


def test_is_expired(task_registry, redis_client):
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

    # Mock the get method for different task IDs
    def mock_hget(hash_name, key):
        if key == "expired-task":
            return expired_task.SerializeToString()
        elif key == "live-task":
            return live_task.SerializeToString()
        return None

    redis_client.hget.side_effect = mock_hget

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

    # Setup for __iter__
    mock_dict = {
        b"live-task": live_task.SerializeToString(),
        b"ignored-cancelled-flag": ignored_cancelled_flag_task.SerializeToString(),
        b"expired-task": expired_task.SerializeToString(),
        b"cancelled-task": cancelled_task.SerializeToString(),
    }
    redis_client.hgetall.return_value = mock_dict

    # Setup for cancelled set
    redis_client.smembers.return_value = [b"cancelled-task"]

    # Setup for is_expired checks
    def mock_is_expired(task_or_id):
        task_id = task_or_id.task_id if isinstance(task_or_id, Task) else task_or_id
        return task_id == "expired-task"

    # Patch the is_expired method
    original_is_expired = task_registry.is_expired
    task_registry.is_expired = mock_is_expired

    try:
        # Get live tasks
        live_tasks = task_registry.get_live_tasks()

        # Should include live_task and ignored_cancelled_flag_task
        assert len(live_tasks) == 2
        task_ids = {task.task_id for task in live_tasks}
        assert "live-task" in task_ids
        assert "ignored-cancelled-flag" in task_ids
        assert "expired-task" not in task_ids
        assert "cancelled-task" not in task_ids
    finally:
        # Restore original method
        task_registry.is_expired = original_is_expired


def test_get_cancelled_task_ids(task_registry, redis_client):
    # Initially there are no cancelled tasks
    redis_client.smembers.return_value = []
    assert task_registry.get_cancelled_task_ids() == []

    # Add a few task IDs to the cancelled set
    redis_client.smembers.return_value = [b"task1", b"task2", b"task3"]

    # Get the cancelled task IDs
    cancelled_ids = task_registry.get_cancelled_task_ids()

    # Check that all expected IDs are in the result
    assert len(cancelled_ids) == 3
    assert set(cancelled_ids) == {"task1", "task2", "task3"}

    # Simulate removing one task ID from the cancelled set
    redis_client.smembers.return_value = [b"task1", b"task3"]

    # Check that the removed ID is no longer in the result
    cancelled_ids = task_registry.get_cancelled_task_ids()
    assert len(cancelled_ids) == 2
    assert set(cancelled_ids) == {"task1", "task3"}


# Tests for should_stop_processing utility function


def test_should_stop_processing_with_cancelled_ids(task_registry, redis_client):
    """Test that should_stop_processing handles cancelled_ids correctly."""
    # Create a set of cancelled IDs
    cancelled_ids: Set[str] = {"cancelled-task-1", "cancelled-task-2"}

    # Create tasks to test with
    current_time = int(time.time())
    cancelled_task1 = Task(task_id="cancelled-task-1", deadline=current_time + 3600)
    cancelled_task2 = Task(task_id="cancelled-task-2", deadline=current_time + 3600)
    active_task = Task(task_id="active-task", deadline=current_time + 3600)

    # Setup mock Redis
    def mock_hget(hash_name, key):
        if key == "cancelled-task-1":
            return cancelled_task1.SerializeToString()
        elif key == "cancelled-task-2":
            return cancelled_task2.SerializeToString()
        elif key == "active-task":
            return active_task.SerializeToString()
        return None

    redis_client.hget.side_effect = mock_hget

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

    # Create cancelled task and add to cancelled set
    cancelled_task = Task(task_id="cancelled-task", deadline=current_time + 3600)

    # Setup Redis mock
    def mock_hget(hash_name, key):
        if key == "active-task":
            return active_task.SerializeToString()
        elif key == "cancelled-task":
            return cancelled_task.SerializeToString()
        return None

    redis_client.hget.side_effect = mock_hget

    # Setup sismember to handle cancelled status
    def mock_sismember(set_name, key):
        return key == "cancelled-task"

    redis_client.sismember.side_effect = mock_sismember

    # Test with a task ID string (no cancelled_ids)
    result = task_registry.should_stop_processing("active-task")
    assert result is False, "Should return False for non-cancelled, non-expired task"

    # Test with a Task object that is cancelled
    result = task_registry.should_stop_processing(cancelled_task)
    assert result is True, "Should return True for cancelled task"

    # Verify sismember was called correctly
    redis_client.sismember.assert_any_call(CANCELLED_TASKS_SET, "cancelled-task")


def test_should_stop_processing_expired_task(task_registry, redis_client):
    """Test that should_stop_processing returns True for expired tasks."""
    current_time = int(time.time())

    # Create an expired task (deadline in the past)
    expired_task = Task(task_id="expired-task", deadline=current_time - 3600)

    # Create an active task (deadline in the future)
    active_task = Task(task_id="active-task", deadline=current_time + 3600)

    # Setup Redis mock
    def mock_hget(hash_name, key):
        if key == "expired-task":
            return expired_task.SerializeToString()
        elif key == "active-task":
            return active_task.SerializeToString()
        return None

    redis_client.hget.side_effect = mock_hget

    # Setup is_cancelled to return False for all tasks
    redis_client.sismember.return_value = False

    # Setup is_expired to return True only for expired-task
    def mock_is_expired(task_or_id):
        task_id = task_or_id.task_id if isinstance(task_or_id, Task) else task_or_id
        return task_id == "expired-task"

    # Patch the is_expired method
    original_is_expired = task_registry.is_expired
    task_registry.is_expired = mock_is_expired

    try:
        # Test with a task ID string that is expired
        result = task_registry.should_stop_processing("expired-task")
        assert result is True, "Should return True for expired task (string ID)"

        # Test with a Task object that is expired
        result = task_registry.should_stop_processing(expired_task)
        assert result is True, "Should return True for expired task (Task object)"

        # Test with a task that is not expired
        result = task_registry.should_stop_processing("active-task")
        assert result is False, "Should return False for non-expired task"
    finally:
        # Restore original method
        task_registry.is_expired = original_is_expired


def test_mark_successful(task_registry, sample_task, redis_client):
    # Setup
    redis_client.sismember.return_value = False

    # Add the task
    task_registry.set(sample_task)
    assert not task_registry.is_successful("test123")

    # Mark as successful
    task_registry.mark_successful(sample_task)

    # Check that the task_id is in the successful tasks set
    redis_client.sadd.assert_called_once_with(SUCCEEDED_TASKS_SET, "test123")

    # Make is_successful return True now
    redis_client.sismember.return_value = True

    # Check that is_successful reports the task as successful
    assert task_registry.is_successful("test123")


def test_is_successful_with_set(task_registry, sample_task, redis_client):
    # Setup
    redis_client.sismember.return_value = False

    # Add the task
    task_registry.set(sample_task)

    # Initially not successful
    assert not task_registry.is_successful(sample_task)

    # Add to the successful set directly (mock it)
    redis_client.sismember.return_value = True

    # Should now report as successful because of the set
    assert task_registry.is_successful(sample_task)


def test_mark_errored(task_registry, sample_task, redis_client):
    # Setup
    redis_client.sismember.return_value = False

    # Add the task
    task_registry.set(sample_task)
    assert not task_registry.is_errored("test123")

    # Mark as errored
    task_registry.mark_errored(sample_task)

    # Check that the task_id is in the errored tasks set
    redis_client.sadd.assert_called_once_with(ERRORED_TASKS_SET, "test123")

    # Make is_errored return True now
    redis_client.sismember.return_value = True

    # Check that is_errored reports the task as errored
    assert task_registry.is_errored("test123")


def test_is_errored_with_set(task_registry, sample_task, redis_client):
    # Setup
    redis_client.sismember.return_value = False

    # Add the task
    task_registry.set(sample_task)

    # Initially not errored
    assert not task_registry.is_errored(sample_task)

    # Add to the errored set directly (mock it)
    redis_client.sismember.return_value = True

    # Should now report as errored because of the set
    assert task_registry.is_errored(sample_task)


def test_is_expired_with_delta(task_registry, redis_client):
    """Test the is_expired function with different delta_seconds values.

    When delta_seconds is positive, the task's deadline is effectively extended by that amount.
    When delta_seconds is negative, the task's deadline is effectively moved earlier by that amount.
    """
    current_time = 1000000000  # Fixed timestamp for testing

    with patch("time.time", return_value=current_time):
        # Create a task that just expired (deadline = current_time)
        just_expired_task = Task(
            task_id="just-expired",
            deadline=current_time,
        )

        # Create a task that will expire in 100 seconds
        soon_expired_task = Task(
            task_id="soon-expired",
            deadline=current_time + 100,
        )

        # Create a task that will expire in 1000 seconds
        future_task = Task(
            task_id="future-task",
            deadline=current_time + 1000,
        )

        # Mock the get method for different task IDs
        def mock_hget(hash_name, key):
            if key == "just-expired":
                return just_expired_task.SerializeToString()
            elif key == "soon-expired":
                return soon_expired_task.SerializeToString()
            elif key == "future-task":
                return future_task.SerializeToString()
            return None

        redis_client.hget.side_effect = mock_hget

        # Test just_expired_task with different deltas
        assert task_registry.is_expired(just_expired_task) is True  # No delta
        assert task_registry.is_expired(just_expired_task, delta_seconds=0) is True  # Zero delta
        assert (
            task_registry.is_expired(just_expired_task, delta_seconds=-60) is True
        )  # Negative delta (deadline moved earlier)
        assert (
            task_registry.is_expired(just_expired_task, delta_seconds=60) is False
        )  # Positive delta (deadline extended by 60s)

        # Test soon_expired_task with different deltas
        assert task_registry.is_expired(soon_expired_task) is False  # No delta
        assert task_registry.is_expired(soon_expired_task, delta_seconds=0) is False  # Zero delta
        assert (
            task_registry.is_expired(soon_expired_task, delta_seconds=-60) is False
        )  # Negative delta (deadline moved earlier by 60s)
        assert (
            task_registry.is_expired(soon_expired_task, delta_seconds=-100) is True
        )  # Negative delta (deadline moved earlier by 100s)
        assert (
            task_registry.is_expired(soon_expired_task, delta_seconds=60) is False
        )  # Positive delta (deadline extended by 60s)
        assert (
            task_registry.is_expired(soon_expired_task, delta_seconds=200) is False
        )  # Large positive delta (deadline extended by 200s)

        # Test future_task with different deltas
        assert task_registry.is_expired(future_task) is False  # No delta
        assert task_registry.is_expired(future_task, delta_seconds=0) is False  # Zero delta
        assert (
            task_registry.is_expired(future_task, delta_seconds=-60) is False
        )  # Negative delta (deadline moved earlier by 60s)
        assert (
            task_registry.is_expired(future_task, delta_seconds=1000) is False
        )  # Positive delta (deadline extended by 1000s)
        assert (
            task_registry.is_expired(future_task, delta_seconds=2000) is False
        )  # Large positive delta (deadline extended by 2000s)


def test_is_expired_with_delta_edge_cases(task_registry, redis_client):
    """Test edge cases for is_expired with delta_seconds.

    When delta_seconds is positive, the task's deadline is effectively extended by that amount.
    When delta_seconds is negative, the task's deadline is effectively moved earlier by that amount.
    """
    current_time = 1000000000  # Fixed timestamp for testing

    with patch("time.time", return_value=current_time):
        # Create a task that expired 1 second ago
        one_second_expired = Task(
            task_id="one-second-expired",
            deadline=current_time - 1,
        )

        # Create a task that will expire in 1 second
        one_second_future = Task(
            task_id="one-second-future",
            deadline=current_time + 1,
        )

        # Mock the get method
        def mock_hget(hash_name, key):
            if key == "one-second-expired":
                return one_second_expired.SerializeToString()
            elif key == "one-second-future":
                return one_second_future.SerializeToString()
            return None

        redis_client.hget.side_effect = mock_hget

        # Test with very small deltas
        assert task_registry.is_expired(one_second_expired, delta_seconds=0) is True  # No change to deadline
        assert task_registry.is_expired(one_second_expired, delta_seconds=1) is True  # Deadline extended by 1s
        assert task_registry.is_expired(one_second_expired, delta_seconds=2) is False  # Deadline extended by 2s
        assert task_registry.is_expired(one_second_expired, delta_seconds=-1) is True  # Deadline moved earlier by 1s
        assert task_registry.is_expired(one_second_future, delta_seconds=0) is False  # No change to deadline
        assert task_registry.is_expired(one_second_future, delta_seconds=1) is False  # Deadline extended by 1s
        assert task_registry.is_expired(one_second_future, delta_seconds=2) is False  # Deadline extended by 2s

        # Test with very large deltas
        assert (
            task_registry.is_expired(one_second_expired, delta_seconds=1000000) is False
        )  # Deadline extended by 1000000s
        assert (
            task_registry.is_expired(one_second_future, delta_seconds=1000000) is False
        )  # Deadline extended by 1000000s

        # Test with negative deltas
        assert task_registry.is_expired(one_second_expired, delta_seconds=-1) is True  # Deadline moved earlier by 1s
        assert task_registry.is_expired(one_second_future, delta_seconds=-1) is True  # Deadline moved earlier by 1s
        assert task_registry.is_expired(one_second_future, delta_seconds=-2) is True  # Deadline moved earlier by 2s


def test_is_expired_with_delta_time_changes(task_registry, redis_client):
    """Test is_expired behavior when time changes between calls.

    When delta_seconds is positive, the task's deadline is effectively extended by that amount.
    When delta_seconds is negative, the task's deadline is effectively moved earlier by that amount.
    """
    base_time = 1000000000  # Fixed base timestamp for testing

    # Create a task that will expire in 100 seconds from base_time
    task = Task(
        task_id="time-sensitive-task",
        deadline=base_time + 100,
    )

    # Mock the get method
    redis_client.hget.return_value = task.SerializeToString()

    # Test with different time points
    with patch("time.time") as mock_time:
        # First check: current time = base_time
        mock_time.return_value = base_time
        assert task_registry.is_expired(task) is False  # Not expired
        assert task_registry.is_expired(task, delta_seconds=50) is False  # Deadline extended by 50s
        assert task_registry.is_expired(task, delta_seconds=100) is False  # Deadline extended by 100s

        # Second check: current time = base_time + 50
        mock_time.return_value = base_time + 50
        assert task_registry.is_expired(task) is False  # Not expired
        assert task_registry.is_expired(task, delta_seconds=50) is False  # Deadline extended by 50s
        assert task_registry.is_expired(task, delta_seconds=100) is False  # Deadline extended by 100s

        # Third check: current time = base_time + 100
        mock_time.return_value = base_time + 100
        assert task_registry.is_expired(task) is True  # Expired
        assert task_registry.is_expired(task, delta_seconds=50) is False  # Deadline extended by 50s
        assert task_registry.is_expired(task, delta_seconds=100) is False  # Deadline extended by 100s

        # Fourth check: current time = base_time + 150
        mock_time.return_value = base_time + 150
        assert task_registry.is_expired(task) is True  # Expired
        assert task_registry.is_expired(task, delta_seconds=50) is True  # Deadline extended by 50s
        assert task_registry.is_expired(task, delta_seconds=100) is False  # Deadline extended by 100s
