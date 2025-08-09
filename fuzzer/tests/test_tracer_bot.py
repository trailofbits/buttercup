import pytest
from unittest.mock import patch, MagicMock
from redis import Redis
from buttercup.fuzzing_infra.tracer_bot import TracerBot
from buttercup.common.datastructures.msg_pb2 import Crash, Task, BuildOutput
from buttercup.common.task_registry import TaskRegistry
import time


@pytest.fixture
def redis_client():
    res = Redis(host="localhost", port=6379, db=13)
    yield res
    res.flushdb()


@pytest.fixture
def tracer_bot(redis_client):
    return TracerBot(redis=redis_client, seconds_sleep=1, wdir="/tmp", python="python3", max_tries=3)


def test_serve_item_should_process_normal_task(tracer_bot, redis_client):
    """Test that a normal task is processed correctly"""
    # Setup task registry with a non-expired, non-cancelled task
    registry = TaskRegistry(redis_client)

    # Mock the queue.pop method to return a test item
    task_id = "test_task_id"
    task_deadline = int(time.time()) + 3600  # Set deadline 1 hour in future

    # Create a Task for the registry
    mock_task = Task(task_id=task_id, deadline=task_deadline)

    # Create a BuildOutput for the crash target
    mock_build_output = BuildOutput(task_id=task_id)

    # Create the crash with BuildOutput as target
    mock_crash = Crash(target=mock_build_output, harness_name="test_harness", crash_input_path="test/path")

    mock_item = MagicMock()
    mock_item.deserialized = mock_crash
    mock_item.item_id = "test_item_id"

    # Register the task in the registry
    registry.set(mock_task)

    # Patch methods to avoid actual execution but track what would happen
    with (
        patch.object(tracer_bot.queue, "pop", return_value=mock_item),
        patch.object(tracer_bot.queue, "ack_item"),
        patch.object(tracer_bot.queue, "times_delivered", return_value=1),
        patch("buttercup.fuzzing_infra.tracer_runner.TracerRunner.run") as mock_run,
        patch("buttercup.common.node_local.make_locally_available") as mock_local,
    ):
        # Configure the run method to return a valid tracer info
        mock_tracer_info = MagicMock()
        mock_tracer_info.is_valid = True
        mock_tracer_info.stacktrace = "Test stacktrace"
        mock_run.return_value = mock_tracer_info

        # Set up the mock for make_locally_available
        mock_local.return_value = "local/test/path"

        # Run the serve_item method
        result = tracer_bot.serve_item()

        # Verify the task was processed (not skipped)
        assert result is True
        mock_run.assert_called_once()
        tracer_bot.queue.ack_item.assert_called_once_with("test_item_id")


def test_serve_item_should_skip_tasks_marked_for_stopping(tracer_bot, redis_client):
    """Test that tasks marked for stopping (expired or cancelled) are not processed"""
    # Define the task ID
    task_id = "skip_task_id"

    # Create a BuildOutput for the crash target
    mock_build_output = BuildOutput(task_id=task_id)

    # Create the crash with BuildOutput as target
    mock_crash = Crash(target=mock_build_output, harness_name="test_harness", crash_input_path="test/path")

    mock_item = MagicMock()
    mock_item.deserialized = mock_crash
    mock_item.item_id = "skip_item_id"

    # Patch the should_stop_processing method to always return True
    with (
        patch.object(tracer_bot.queue, "pop", return_value=mock_item),
        patch.object(tracer_bot.queue, "ack_item"),
        patch.object(tracer_bot.registry, "should_stop_processing", return_value=True),
        patch("buttercup.fuzzing_infra.tracer_runner.TracerRunner.run") as mock_run,
    ):
        # Run the serve_item method
        result = tracer_bot.serve_item()

        # Verify the task was acknowledged without processing
        assert result is True
        mock_run.assert_not_called()  # The run method should not be called for tasks marked for stopping
        tracer_bot.queue.ack_item.assert_called_once_with("skip_item_id")
        # Verify should_stop_processing was called with the correct task ID
        tracer_bot.registry.should_stop_processing.assert_called_once_with(task_id)
