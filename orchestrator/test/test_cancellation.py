import time
from unittest.mock import Mock, patch
import pytest
from redis import Redis

from buttercup.common.datastructures.msg_pb2 import TaskDelete
from buttercup.common.queues import ReliableQueue, RQItem
from buttercup.orchestrator.scheduler.cancellation import Cancellation
from buttercup.orchestrator.registry import TaskRegistry, Task


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
    return registry


@pytest.fixture
def cancellation(mock_redis, mock_queue, mock_registry):
    with patch("buttercup.orchestrator.scheduler.cancellation.QueueFactory") as mock_factory:
        mock_factory.return_value.create.return_value = mock_queue
        with patch("buttercup.orchestrator.scheduler.cancellation.TaskRegistry", return_value=mock_registry):
            return Cancellation(redis=mock_redis)


def test_process_delete_request_success(cancellation, mock_registry):
    # Arrange
    task_id = "test_task_123"
    current_time = time.time()
    delete_request = TaskDelete(task_id=task_id, received_at=current_time)
    mock_task = Mock(spec=Task)
    mock_task.received_at = current_time
    mock_registry.get.return_value = mock_task

    # Act
    result = cancellation.process_delete_request(delete_request)

    # Assert
    assert result is True
    mock_registry.get.assert_called_once_with(task_id)
    mock_registry.mark_cancelled.assert_called_once_with(mock_task)


def test_process_delete_request_task_not_found(cancellation, mock_registry):
    # Arrange
    task_id = "nonexistent_task"
    current_time = time.time()
    delete_request = TaskDelete(task_id=task_id, received_at=current_time)
    mock_registry.get.return_value = None

    # Act
    result = cancellation.process_delete_request(delete_request)

    # Assert
    assert result is False
    mock_registry.get.assert_called_once_with(task_id)
    mock_registry.mark_cancelled.assert_not_called()


def test_process_iteration_with_delete_request(cancellation, mock_queue, mock_registry):
    # Arrange
    task_id = "test_task_456"
    current_time = time.time()
    delete_request = TaskDelete(task_id=task_id, received_at=current_time)
    mock_queue.pop.return_value = RQItem(item_id="queue_item_1", deserialized=delete_request)
    mock_task = Mock(spec=Task)
    mock_task.received_at = current_time  # Add received_at for logging
    mock_registry.get.return_value = mock_task

    # Act
    result = cancellation.process_cancellations()

    # Assert
    assert result is True
    mock_queue.pop.assert_called_once()
    mock_registry.get.assert_called_once_with(task_id)
    mock_registry.mark_cancelled.assert_called_once_with(mock_task)
    mock_queue.ack_item.assert_called_once_with("queue_item_1")


def test_process_iteration_no_delete_request(cancellation, mock_queue, mock_registry):
    # Arrange
    mock_queue.pop.return_value = None
    mock_registry.__iter__.return_value = iter([])  # No tasks to timeout

    # Act
    result = cancellation.process_cancellations()

    # Assert
    assert result is False
    mock_queue.pop.assert_called_once()
    mock_registry.get.assert_not_called()
    mock_registry.mark_cancelled.assert_not_called()
    mock_queue.ack_item.assert_not_called()
