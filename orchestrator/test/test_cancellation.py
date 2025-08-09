import time
from unittest.mock import Mock, patch
import pytest
from redis import Redis

from buttercup.common.datastructures.msg_pb2 import TaskDelete
from buttercup.common.queues import ReliableQueue, RQItem
from buttercup.orchestrator.scheduler.cancellation import Cancellation
from buttercup.common.task_registry import TaskRegistry
from buttercup.common.datastructures.msg_pb2 import Task


@pytest.fixture
def mock_redis():
    return Mock(spec=Redis)


@pytest.fixture
def mock_queue():
    queue = Mock(spec=ReliableQueue)
    queue.pop.return_value = None
    return queue


@pytest.fixture
def mock_registry():
    registry = Mock(spec=TaskRegistry)
    registry.__iter__ = Mock(return_value=iter([]))
    # Ensure smembers returns an iterable
    registry.redis = Mock()
    registry.redis.smembers = Mock(return_value=[])
    return registry


@pytest.fixture
def cancellation(mock_redis, mock_queue, mock_registry):
    with patch("buttercup.orchestrator.scheduler.cancellation.QueueFactory") as mock_factory:
        mock_factory.return_value.create.return_value = mock_queue

        # Patch the TaskRegistry constructor to return our mock registry
        with patch("buttercup.common.task_registry.TaskRegistry", return_value=mock_registry):
            # Create a Cancellation instance with our mocked dependencies
            cancellation = Cancellation(redis=mock_redis)
            # Replace the registry instance with our mock to ensure tests use it
            cancellation.registry = mock_registry
            return cancellation


def test_process_delete_request_success(cancellation, mock_registry):
    # Arrange
    task_id = "test_task_123"
    current_time = time.time()
    delete_request = TaskDelete(task_id=task_id, received_at=current_time)

    # Act
    result = cancellation.process_delete_request(delete_request)

    # Assert
    assert result is True
    # Should mark the task as cancelled directly by ID without fetching it first
    mock_registry.mark_cancelled.assert_called_once_with(task_id)
    # Should not need to call get anymore
    mock_registry.get.assert_not_called()


def test_process_delete_request_all_tasks(cancellation, mock_registry):
    # Arrange
    current_time = time.time()
    delete_request = TaskDelete(all=True, received_at=current_time)

    # Create mock tasks
    mock_task1 = Mock(spec=Task, task_id="task1")
    mock_task2 = Mock(spec=Task, task_id="task2")
    mock_task3 = Mock(spec=Task, task_id="task3")
    mock_tasks = [mock_task1, mock_task2, mock_task3]

    # Configure the registry.__iter__ to return our tasks
    mock_registry.__iter__.return_value = iter(mock_tasks)

    # Configure is_cancelled to return False for all tasks
    mock_registry.is_cancelled.return_value = False

    # Act
    result = cancellation.process_delete_request(delete_request)

    # Assert
    assert result is True
    assert mock_registry.mark_cancelled.call_count == 3
    mock_registry.mark_cancelled.assert_any_call(mock_task1)
    mock_registry.mark_cancelled.assert_any_call(mock_task2)
    mock_registry.mark_cancelled.assert_any_call(mock_task3)


def test_process_delete_request_all_tasks_some_already_cancelled(cancellation, mock_registry):
    # Arrange
    current_time = time.time()
    delete_request = TaskDelete(all=True, received_at=current_time)

    # Create mock tasks
    mock_task1 = Mock(spec=Task, task_id="task1")
    mock_task2 = Mock(spec=Task, task_id="task2")
    mock_task3 = Mock(spec=Task, task_id="task3")
    mock_tasks = [mock_task1, mock_task2, mock_task3]

    # Configure the registry.__iter__ to return our tasks
    mock_registry.__iter__.return_value = iter(mock_tasks)

    # Configure is_cancelled to return True for task2 and False for others
    def is_cancelled_side_effect(task):
        return task.task_id == "task2"  # task2 is already cancelled

    mock_registry.is_cancelled.side_effect = is_cancelled_side_effect

    # Act
    result = cancellation.process_delete_request(delete_request)

    # Assert
    assert result is True
    assert mock_registry.mark_cancelled.call_count == 2
    mock_registry.mark_cancelled.assert_any_call(mock_task1)
    mock_registry.mark_cancelled.assert_any_call(mock_task3)

    # task2 should not be cancelled again
    assert not any(call[0][0] == mock_task2 for call in mock_registry.mark_cancelled.call_args_list)


# Removed the test_check_timeouts since that functionality has been removed
# Expiration is now handled through the registry's is_expired method and should_stop_processing function


def test_process_iteration_with_delete_request_single_task(cancellation, mock_queue, mock_registry):
    # Arrange
    task_id = "test_task_456"
    current_time = time.time()
    delete_request = TaskDelete(task_id=task_id, received_at=current_time)
    mock_queue.pop.return_value = RQItem(item_id="queue_item_1", deserialized=delete_request)

    # Act
    result = cancellation.process_cancellations()

    # Assert
    assert result is True
    mock_queue.pop.assert_called_once()
    # Should mark the task as cancelled directly by ID without fetching it first
    mock_registry.mark_cancelled.assert_called_once_with(task_id)
    # Should not need to call get anymore
    mock_registry.get.assert_not_called()
    mock_queue.ack_item.assert_called_once_with("queue_item_1")


def test_process_iteration_with_delete_request_all_tasks(cancellation, mock_queue, mock_registry):
    # Arrange
    current_time = time.time()
    delete_request = TaskDelete(all=True, received_at=current_time)
    mock_queue.pop.return_value = RQItem(item_id="queue_item_all", deserialized=delete_request)

    # Create mock tasks
    mock_task1 = Mock(spec=Task, task_id="task1")
    mock_task2 = Mock(spec=Task, task_id="task2")
    mock_tasks = [mock_task1, mock_task2]

    # Configure the registry to return our tasks and handle is_cancelled
    mock_registry.__iter__.return_value = iter(mock_tasks)
    mock_registry.is_cancelled.return_value = False

    # Act
    result = cancellation.process_cancellations()

    # Assert
    assert result is True
    mock_queue.pop.assert_called_once()
    mock_registry.mark_cancelled.assert_any_call(mock_task1)
    mock_registry.mark_cancelled.assert_any_call(mock_task2)
    assert mock_registry.mark_cancelled.call_count == 2
    mock_queue.ack_item.assert_called_once_with("queue_item_all")


def test_process_iteration_no_delete_request(cancellation, mock_queue, mock_registry):
    # Arrange
    mock_queue.pop.return_value = None

    # Act
    result = cancellation.process_cancellations()

    # Assert
    assert result is False
    mock_queue.pop.assert_called_once()
    mock_registry.get.assert_not_called()
    mock_registry.mark_cancelled.assert_not_called()
    mock_queue.ack_item.assert_not_called()
