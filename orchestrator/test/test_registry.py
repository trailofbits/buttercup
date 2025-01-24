import pytest
from buttercup.orchestrator.registry import TaskRegistry
from buttercup.common.datastructures.orchestrator_pb2 import Task, SourceDetail
from redis import Redis


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


def test_iter_tasks_with_different_types(task_registry):
    # Create and add two different tasks
    full_task = Task(task_id="full123", task_type=Task.TaskType.TASK_TYPE_FULL, message_id="msg_full", cancelled=False)
    delta_task = Task(
        task_id="delta456", task_type=Task.TaskType.TASK_TYPE_DELTA, message_id="msg_delta", cancelled=True
    )

    task_registry.set(full_task)
    task_registry.set(delta_task)

    assert len(task_registry) == 2

    # Verify we can get both types of tasks
    task_types = {task.task_type for task in task_registry}
    assert Task.TaskType.TASK_TYPE_FULL in task_types
    assert Task.TaskType.TASK_TYPE_DELTA in task_types

    # Verify cancelled state is preserved
    cancelled_states = {task.cancelled for task in task_registry}
    assert True in cancelled_states
    assert False in cancelled_states


def test_update_task(task_registry, sample_task):
    task_registry.set(sample_task)
    assert not task_registry.get("test123").cancelled
    sample_task.cancelled = True
    task_registry.set(sample_task)
    assert task_registry.get("test123").cancelled
