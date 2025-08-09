import pytest
from unittest.mock import patch, MagicMock, Mock
from redis import Redis
from buttercup.program_model.program_model import ProgramModel
from buttercup.common.datastructures.msg_pb2 import IndexRequest
from buttercup.common.task_registry import TaskRegistry


@pytest.fixture
def redis_client():
    res = Mock(spec=Redis)
    return res


@pytest.fixture
def program_model(redis_client):
    model = ProgramModel(redis=redis_client)
    # Ensure the queues are mocked since we won't have a real Redis
    model.task_queue = Mock()
    model.output_queue = Mock()
    model.registry = Mock(spec=TaskRegistry)
    return model


def test_serve_item_skip_cancelled_task(program_model):
    """Test that cancelled or expired tasks are skipped"""
    # Set up the mocks
    mock_task_id = "test_cancelled_task_id"

    # Create mock IndexRequest
    mock_request = IndexRequest(task_id=mock_task_id)

    # Create mock RQItem
    mock_item = MagicMock()
    mock_item.deserialized = mock_request
    mock_item.item_id = "test_item_id"

    # Mock the queue to return our test item
    program_model.task_queue.pop.return_value = mock_item

    # Mock registry to indicate the task should be stopped (cancelled or expired)
    program_model.registry.should_stop_processing.return_value = True

    # Call serve_item
    result = program_model.serve_item()

    # Verify the task was acknowledged without processing
    assert result is True
    program_model.registry.should_stop_processing.assert_called_once_with(mock_task_id)
    program_model.task_queue.ack_item.assert_called_once_with(mock_item.item_id)

    # Verify process_task was not called
    # This is a bit tricky since it's a method on the same object
    # We'll patch it for the next test to verify it's called for normal tasks


def test_serve_item_process_normal_task(program_model):
    """Test that normal tasks are processed"""
    # Set up the mocks
    mock_task_id = "test_normal_task_id"

    # Create mock IndexRequest
    mock_request = IndexRequest(task_id=mock_task_id)

    # Create mock RQItem
    mock_item = MagicMock()
    mock_item.deserialized = mock_request
    mock_item.item_id = "test_item_id"

    # Mock the queue to return our test item
    program_model.task_queue.pop.return_value = mock_item

    # Mock registry to indicate the task should not be stopped
    program_model.registry.should_stop_processing.return_value = False

    # Mock process_task to return success
    with patch.object(program_model, "process_task", return_value=True):
        # Call serve_item
        result = program_model.serve_item()

        # Verify the task was processed and acknowledged
        assert result is True
        program_model.registry.should_stop_processing.assert_called_once_with(
            mock_task_id
        )
        program_model.process_task.assert_called_once_with(mock_request)
        program_model.task_queue.ack_item.assert_called_once_with(mock_item.item_id)
        program_model.output_queue.push.assert_called_once()
