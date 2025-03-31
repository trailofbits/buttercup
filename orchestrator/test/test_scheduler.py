import pytest
from unittest.mock import Mock, patch
from redis import Redis

from buttercup.common.datastructures.msg_pb2 import Task, TaskReady, SourceDetail, BuildOutput, WeightedHarness
from buttercup.common.maps import BUILD_TYPES
from buttercup.common.task_meta import TaskMeta

from buttercup.common.queues import RQItem, ReliableQueue
from buttercup.orchestrator.scheduler.scheduler import Scheduler
from buttercup.orchestrator.registry import TaskRegistry
from buttercup.orchestrator.scheduler.submission_tracker import SubmissionTracker
from buttercup.common.queues import QueueFactory

import tempfile
from pathlib import Path


@pytest.fixture
def mock_redis():
    return Mock(spec=Redis)


@pytest.fixture
def mock_patch_api():
    return Mock()


@pytest.fixture
def mock_bundles_queue():
    return Mock(spec=ReliableQueue)


@pytest.fixture
def mock_submission_tracker():
    return Mock(spec=SubmissionTracker)


@pytest.fixture
def mock_task_registry():
    return Mock(spec=TaskRegistry)


@pytest.fixture
def mock_api_client():
    return Mock()


@pytest.fixture
def mock_queues():
    crash_queue = Mock()
    traced_vulnerabilities_queue = Mock()
    confirmed_vulnerabilities_queue = Mock()

    # Mock QueueFactory
    queue_factory = Mock(spec=QueueFactory)
    queue_factory.create.side_effect = [crash_queue, traced_vulnerabilities_queue, confirmed_vulnerabilities_queue]

    # Create a patch for QueueFactory
    with patch("buttercup.orchestrator.scheduler.vulnerabilities.QueueFactory", return_value=queue_factory):
        yield {
            "factory": queue_factory,
            "crash": crash_queue,
            "traced": traced_vulnerabilities_queue,
            "confirmed": confirmed_vulnerabilities_queue,
        }


@pytest.fixture
def scheduler(
    mock_redis,
    mock_patch_api,
    mock_bundles_queue,
    mock_submission_tracker,
    mock_task_registry,
    mock_api_client,
    mock_queues,
):
    with (
        patch("buttercup.orchestrator.competition_api_client.PatchApi", return_value=mock_patch_api),
        patch("buttercup.orchestrator.scheduler.scheduler.TaskRegistry", return_value=mock_task_registry),
    ):
        # Create a scheduler instance with mocked dependencies
        scheduler = Scheduler(
            tasks_storage_dir=Path("/tmp/task_downloads"),
            scratch_dir=Path("/tmp/crs_scratch"),
            redis=mock_redis,
            competition_api_url="http://test-api:8080",
            competition_api_key_id="test_key_id",
            competition_api_key_token="test_key_token",
        )

        # Mock patches and vulnerabilities
        scheduler.patches = Mock()
        scheduler.patches.status_checker = Mock()
        scheduler.patches.check_pending_statuses = Mock()

        scheduler.vulnerabilities = Mock()
        scheduler.vulnerabilities.status_checker = Mock()
        scheduler.vulnerabilities.check_pending_statuses = Mock()

        # Set up bundles mock
        scheduler.bundles = Mock()
        scheduler.bundles.process_bundles = Mock(return_value=False)

        return scheduler


@pytest.mark.skip(reason="Not implemented")
def test_process_ready_task(scheduler):
    # Create a mock task with example-libpng source
    source = SourceDetail(source_type=SourceDetail.SourceType.SOURCE_TYPE_REPO, url="https://github.com/libpng/libpng")
    task = Task(task_id="test-task-1", sources=[source])

    build_request = scheduler.process_ready_task(task)

    assert build_request.engine == "libfuzzer"
    assert build_request.sanitizer == "address"
    assert build_request.task_dir == "/tasks_storage/test-task-1"


@patch("buttercup.orchestrator.scheduler.scheduler.get_fuzz_targets")
def test_process_build_output(mock_get_fuzz_targets, scheduler):
    mock_get_fuzz_targets.return_value = ["target1", "target2"]

    # TODO(Ian): this is stupid
    with tempfile.TemporaryDirectory() as td:
        task_dir = Path(td) / "test-task"
        src_dir = task_dir / "src"
        tooling_dir = task_dir / "fuzz-tooling"
        ossfuzz_dir = tooling_dir / "oss-fuzz"
        source_code_dir = src_dir / "source-code"
        stub_helper_py = ossfuzz_dir / "infra" / "helper.py"

        # Create directories
        src_dir.mkdir(parents=True, exist_ok=True)
        tooling_dir.mkdir(parents=True, exist_ok=True)
        ossfuzz_dir.mkdir(parents=True, exist_ok=True)
        source_code_dir.mkdir(parents=True, exist_ok=True)
        stub_helper_py.parent.mkdir(parents=True, exist_ok=True)
        stub_helper_py.touch()

        # Create and save TaskMeta
        task_meta = TaskMeta(project_name="test-package", focus="test-focus", task_id="task-id-build-output")
        task_meta.save(task_dir)

        build_output = BuildOutput(
            engine="libfuzzer",
            sanitizer="address",
            task_dir=str(task_dir),
            task_id="blah",
            build_type=BUILD_TYPES.FUZZER.value,
        )

        targets = scheduler.process_build_output(build_output)

        assert len(targets) == 2
        assert all(isinstance(t, WeightedHarness) for t in targets)
        assert all(t.weight == 1.0 for t in targets)
        assert all(t.task_id == build_output.task_id for t in targets)
        assert [t.harness_name for t in targets] == ["target1", "target2"]


@pytest.mark.skip(reason="Not implemented")
def test_serve_ready_task(scheduler):
    # Create mock task and queue item
    source = SourceDetail(source_type=SourceDetail.SourceType.SOURCE_TYPE_REPO, path="example-libpng")
    task = Task(task_id="test-task-3", sources=[source])
    task_ready = TaskReady(task=task)
    mock_item = RQItem(item_id="item1", deserialized=task_ready)

    # Mock queue operations
    scheduler.ready_queue.pop = Mock(return_value=mock_item)
    scheduler.build_requests_queue.push = Mock()
    scheduler.ready_queue.ack_item = Mock()

    result = scheduler.serve_ready_task()

    assert result is True, "serve_ready_task should return True"
    scheduler.build_requests_queue.push.assert_called_once()
    scheduler.ready_queue.ack_item.assert_called_once_with("item1")


def test_update_expired_task_weights(scheduler):
    """Test that expired and cancelled task weights are updated to zero."""

    # Set up the mock registry and cached cancelled IDs
    scheduler.task_registry = Mock()
    scheduler.cached_cancelled_ids = {"cancelled-task-789"}

    # Mock the should_stop_processing method to return True for specific tasks
    original_should_stop_processing = scheduler.should_stop_processing
    scheduler.should_stop_processing = Mock()

    def mock_should_stop_processing(task_or_id):
        task_id = task_or_id.task_id if isinstance(task_or_id, Task) else task_or_id
        return task_id in {"expired-task-456", "cancelled-task-789"}

    scheduler.should_stop_processing.side_effect = mock_should_stop_processing

    # Set up mock harnesses in the harness map
    live_harness = WeightedHarness(
        weight=1.0, harness_name="live-harness", package_name="test-package", task_id="live-task-123"
    )

    expired_harness = WeightedHarness(
        weight=1.0, harness_name="expired-harness", package_name="test-package", task_id="expired-task-456"
    )

    cancelled_harness = WeightedHarness(
        weight=1.0, harness_name="cancelled-harness", package_name="test-package", task_id="cancelled-task-789"
    )

    # Set up the mock harness map
    scheduler.harness_map = Mock()
    scheduler.harness_map.list_harnesses.return_value = [live_harness, expired_harness, cancelled_harness]

    # Call the function being tested
    result = scheduler.update_expired_task_weights()

    # Verify the result
    assert result is True, "Should return True because weights were updated"

    # Verify that should_stop_processing was called for each task
    assert scheduler.should_stop_processing.call_count == 3
    scheduler.should_stop_processing.assert_any_call("live-task-123")
    scheduler.should_stop_processing.assert_any_call("expired-task-456")
    scheduler.should_stop_processing.assert_any_call("cancelled-task-789")

    # Verify that the harness map was called to update both expired and cancelled task weights
    assert scheduler.harness_map.push_harness.call_count == 2

    # Get the updated harnesses
    updated_harnesses = [call[0][0] for call in scheduler.harness_map.push_harness.call_args_list]
    updated_task_ids = [h.task_id for h in updated_harnesses]

    # Check that weights were set to zero for both expired and cancelled tasks
    assert "expired-task-456" in updated_task_ids
    assert "cancelled-task-789" in updated_task_ids
    assert all(h.weight == -1.0 for h in updated_harnesses)

    # The live task should not have been updated
    assert "live-task-123" not in updated_task_ids

    # Restore the original method
    scheduler.should_stop_processing = original_should_stop_processing


def test_update_expired_task_weights_none_updated(scheduler):
    """Test that no weights are updated when all tasks are live or already at zero weight."""

    # Set up the mock registry
    scheduler.task_registry = Mock()

    # Mock the should_stop_processing method to return appropriate values
    original_should_stop_processing = scheduler.should_stop_processing
    scheduler.should_stop_processing = Mock()

    def mock_should_stop_processing(task_or_id):
        task_id = task_or_id.task_id if isinstance(task_or_id, Task) else task_or_id
        return task_id in {"expired-task-456", "cancelled-task-789"}

    scheduler.should_stop_processing.side_effect = mock_should_stop_processing

    # Set up mock harnesses in the harness map - one live, two at zero weight
    live_harness = WeightedHarness(
        weight=1.0, harness_name="live-harness", package_name="test-package", task_id="live-task-123"
    )

    zero_expired_harness = WeightedHarness(
        weight=0.0, harness_name="zero-expired-harness", package_name="test-package", task_id="expired-task-456"
    )

    zero_cancelled_harness = WeightedHarness(
        weight=0.0, harness_name="zero-cancelled-harness", package_name="test-package", task_id="cancelled-task-789"
    )

    # Set up the mock harness map
    scheduler.harness_map = Mock()
    scheduler.harness_map.list_harnesses.return_value = [live_harness, zero_expired_harness, zero_cancelled_harness]

    # Call the function being tested
    result = scheduler.update_expired_task_weights()

    # Verify the result
    assert result is False, "Should return False because no weights were updated"

    # Verify that should_stop_processing was only called for the live harness (weight > 0)
    assert scheduler.should_stop_processing.call_count == 1
    scheduler.should_stop_processing.assert_called_once_with("live-task-123")

    # Verify that the harness map was not called to update any weights
    scheduler.harness_map.push_harness.assert_not_called()

    # Restore the original method
    scheduler.should_stop_processing = original_should_stop_processing


def test_update_expired_task_weights_no_registry(scheduler):
    """Test that the function returns False when registry is None."""
    # Ensure task_registry is None
    scheduler.task_registry = None

    # Mock the should_stop_processing method to always return False
    original_should_stop_processing = scheduler.should_stop_processing
    scheduler.should_stop_processing = Mock(return_value=False)

    # Call the function
    result = scheduler.update_expired_task_weights()

    # Check that it returns False
    assert result is False, "Should return False when task_registry is None"

    # Verify should_stop_processing was not called
    scheduler.should_stop_processing.assert_not_called()

    # Restore the original method
    scheduler.should_stop_processing = original_should_stop_processing


def test_update_expired_task_weights_no_harness_map(scheduler):
    """Test that the function returns False when harness_map is None."""
    # Set up a mock task registry but make harness_map None
    scheduler.task_registry = Mock()
    scheduler.harness_map = None

    # Mock the should_stop_processing method to avoid side effects
    original_should_stop_processing = scheduler.should_stop_processing
    scheduler.should_stop_processing = Mock(return_value=False)

    # Call the function
    result = scheduler.update_expired_task_weights()

    # Check that it returns False
    assert result is False, "Should return False when harness_map is None"

    # Verify should_stop_processing was not called
    scheduler.should_stop_processing.assert_not_called()

    # Restore the original method
    scheduler.should_stop_processing = original_should_stop_processing


def test_should_stop_processing_no_registry(scheduler):
    """Test that should_stop_processing returns False when task_registry is None."""
    # Ensure task_registry is None
    scheduler.task_registry = None
    scheduler.cached_cancelled_ids = set()

    # Test with a task ID string
    result = scheduler.should_stop_processing("task-123")
    assert result is False, "Should return False when task_registry is None"

    # Test with a Task object
    task = Task(task_id="task-123")
    result = scheduler.should_stop_processing(task)
    assert result is False, "Should return False when task_registry is None"


def test_should_stop_processing_cancelled_task(scheduler):
    """Test that should_stop_processing returns True for cancelled tasks."""
    # Setup registry and cached cancelled IDs
    scheduler.task_registry = Mock()
    scheduler.cached_cancelled_ids = {"cancelled-task"}

    # Configure the task_registry.should_stop_processing mock
    def mock_should_stop_processing(task_or_id, cancelled_ids=None):
        task_id = task_or_id.task_id if isinstance(task_or_id, Task) else task_or_id
        return task_id in {"cancelled-task"}

    scheduler.task_registry.should_stop_processing.side_effect = mock_should_stop_processing

    # Test with a task ID string that is cancelled
    result = scheduler.should_stop_processing("cancelled-task")
    assert result is True, "Should return True for cancelled task (string ID)"

    # Test with a Task object that is cancelled
    task = Task(task_id="cancelled-task")
    result = scheduler.should_stop_processing(task)
    assert result is True, "Should return True for cancelled task (Task object)"

    # Test with a task that is not cancelled
    result = scheduler.should_stop_processing("active-task")
    assert result is False, "Should return False for non-cancelled task"

    # Verify the registry function was called correctly
    assert scheduler.task_registry.should_stop_processing.call_count == 3


def test_should_stop_processing_expired_task(scheduler):
    """Test that should_stop_processing returns True for expired tasks."""
    # Setup registry and cached cancelled IDs
    scheduler.task_registry = Mock()
    scheduler.cached_cancelled_ids = set()  # No cancelled tasks in cache

    # Configure the task_registry.should_stop_processing mock
    def mock_should_stop_processing(task_or_id, cancelled_ids=None):
        task_id = task_or_id.task_id if isinstance(task_or_id, Task) else task_or_id
        return task_id == "expired-task"

    scheduler.task_registry.should_stop_processing.side_effect = mock_should_stop_processing

    # Test with a task ID string that is expired
    result = scheduler.should_stop_processing("expired-task")
    assert result is True, "Should return True for expired task (string ID)"

    # Test with a Task object that is expired
    task = Task(task_id="expired-task")
    result = scheduler.should_stop_processing(task)
    assert result is True, "Should return True for expired task (Task object)"

    # Test with a task that is not expired
    result = scheduler.should_stop_processing("active-task")
    assert result is False, "Should return False for non-expired task"

    # Verify the registry function was called correctly
    assert scheduler.task_registry.should_stop_processing.call_count == 3


def test_should_stop_processing_wrapper(scheduler):
    """Test that scheduler's should_stop_processing correctly calls the registry function."""
    # Set up the task registry and cached cancelled IDs
    scheduler.task_registry = Mock()
    scheduler.cached_cancelled_ids = {"cached-cancelled-1", "cached-cancelled-2"}

    # Configure the mock to return different values for different calls
    scheduler.task_registry.should_stop_processing.side_effect = [True, False]

    # Call with a task ID
    result1 = scheduler.should_stop_processing("task-id")
    assert result1 is True, "Should return what the registry function returns"

    # Call with a Task object
    task = Task(task_id="task-123")
    result2 = scheduler.should_stop_processing(task)
    assert result2 is False, "Should return what the registry function returns"

    # Verify the wrapper correctly passes all arguments to the registry function
    assert scheduler.task_registry.should_stop_processing.call_count == 2
    scheduler.task_registry.should_stop_processing.assert_any_call("task-id", scheduler.cached_cancelled_ids)
    scheduler.task_registry.should_stop_processing.assert_any_call(task, scheduler.cached_cancelled_ids)


# This test is no longer needed since we're testing the wrapper function
# and the actual logic is now in the registry module


def test_serve_item_processes_cancellations_then_updates_cache(scheduler):
    """Test that serve_item runs process_cancellations first, then updates the cached cancelled IDs."""
    # Setup
    scheduler.cancellation.process_cancellations = Mock(return_value=True)
    scheduler.update_cached_cancelled_ids = Mock(return_value=True)
    scheduler.serve_ready_task = Mock(return_value=False)
    scheduler.serve_build_output = Mock(return_value=False)
    scheduler.serve_index_output = Mock(return_value=False)
    scheduler.vulnerabilities.process_traced_vulnerabilities = Mock(return_value=False)
    scheduler.patches.process_patches = Mock(return_value=False)
    scheduler.update_expired_task_weights = Mock(return_value=False)
    scheduler.competition_api_interactions = Mock(return_value=False)

    # Execute
    result = scheduler.serve_item()

    # Verify
    assert result is True
    scheduler.cancellation.process_cancellations.assert_called_once()
    scheduler.update_cached_cancelled_ids.assert_called_once()
    scheduler.serve_ready_task.assert_called_once()
    scheduler.serve_build_output.assert_called_once()
    scheduler.serve_index_output.assert_called_once()
    scheduler.vulnerabilities.process_traced_vulnerabilities.assert_called_once()
    scheduler.patches.process_patches.assert_called_once()
    scheduler.update_expired_task_weights.assert_called_once()
    scheduler.competition_api_interactions.assert_called_once()


def test_update_cached_cancelled_ids(scheduler):
    """Test that update_cached_cancelled_ids correctly updates the cached set."""
    # Set up the task registry
    scheduler.task_registry = Mock()

    # Configure get_cancelled_task_ids to return a list of task IDs
    cancelled_ids = ["task1", "task2", "task3"]
    scheduler.task_registry.get_cancelled_task_ids.return_value = cancelled_ids

    # Call the method
    result = scheduler.update_cached_cancelled_ids()

    # Verify the result and that the cache was updated
    assert result is True, "Should return True as there are cancelled task IDs"
    assert scheduler.cached_cancelled_ids == set(cancelled_ids), "cached_cancelled_ids should be updated"

    # Test with empty set of cancelled IDs
    scheduler.task_registry.get_cancelled_task_ids.return_value = []

    # Call the method again
    result = scheduler.update_cached_cancelled_ids()

    # Verify the result and that the cache was updated
    assert result is False, "Should return False as there are no cancelled task IDs"
    assert scheduler.cached_cancelled_ids == set(), "cached_cancelled_ids should be empty"

    # Test with null registry
    scheduler.task_registry = None

    # Call the method again
    result = scheduler.update_cached_cancelled_ids()

    # Verify the result
    assert result is False, "Should return False when task_registry is None"


def test_serve_build_output_cancelled_task(scheduler):
    """Test that serve_build_output skips processing for cancelled tasks."""
    # Create a build output for a cancelled task
    build_output = BuildOutput(
        engine="libfuzzer",
        sanitizer="address",
        task_dir="/path/to/task",
        task_id="cancelled-task-id",
        build_type=BUILD_TYPES.FUZZER.value,
    )

    # Create a mock RQItem
    mock_item = RQItem(item_id="build-item-1", deserialized=build_output)

    # Mock the queue operations
    scheduler.build_output_queue = Mock()
    scheduler.build_output_queue.pop.return_value = mock_item

    # Set up the task registry and cached_cancelled_ids
    scheduler.task_registry = Mock()
    scheduler.cached_cancelled_ids = {build_output.task_id}

    # Mock build_map and harness_map to ensure they're not called
    scheduler.build_map = Mock()
    scheduler.harness_map = Mock()

    # Mock should_stop_processing to return True for our cancelled task
    original_should_stop_processing = scheduler.should_stop_processing
    scheduler.should_stop_processing = Mock(return_value=True)

    # Call the method being tested
    result = scheduler.serve_build_output()

    # Verify that processing was skipped and item was acked
    assert result is True, "serve_build_output should return True"
    scheduler.should_stop_processing.assert_called_once_with(build_output.task_id)
    scheduler.build_output_queue.ack_item.assert_called_once_with(mock_item.item_id)

    # Verify that build was not processed
    scheduler.build_map.add_build.assert_not_called()
    scheduler.harness_map.push_harness.assert_not_called()

    # Restore the original method
    scheduler.should_stop_processing = original_should_stop_processing


@patch("buttercup.orchestrator.scheduler.scheduler.ChallengeTask")
def test_serve_ready_task_cancelled_task(mock_challenge_task, scheduler):
    """Test that serve_ready_task skips processing for cancelled tasks."""
    # Create a task with cancelled status
    task = Task(task_id="cancelled-ready-task-id", project_name="test-project", cancelled=True)
    task_ready = TaskReady(task=task)

    # Create a mock RQItem
    mock_item = RQItem(item_id="ready-item-1", deserialized=task_ready)

    # Mock the queue operations
    scheduler.ready_queue = Mock()
    scheduler.ready_queue.pop.return_value = mock_item

    # Mock other queues to ensure they're not called
    scheduler.index_queue = Mock()
    scheduler.build_requests_queue = Mock()

    # Set up the task registry and cached_cancelled_ids
    scheduler.task_registry = Mock()
    scheduler.cached_cancelled_ids = {task.task_id}

    # Mock the should_stop_processing method to return True for our cancelled task
    original_should_stop_processing = scheduler.should_stop_processing
    scheduler.should_stop_processing = Mock(return_value=True)

    # Call the method being tested
    result = scheduler.serve_ready_task()

    # Verify that processing was skipped and item was acked
    assert result is True, "serve_ready_task should return True"
    scheduler.should_stop_processing.assert_called_once_with(task)
    scheduler.ready_queue.ack_item.assert_called_once_with(mock_item.item_id)

    # Verify that task was not processed
    scheduler.index_queue.push.assert_not_called()
    scheduler.build_requests_queue.push.assert_not_called()

    # Verify that ChallengeTask was not instantiated
    mock_challenge_task.assert_not_called()

    # Restore the original method
    scheduler.should_stop_processing = original_should_stop_processing


def test_competition_api_interactions(scheduler):
    """Test that competition_api_interactions calls all components."""
    # Set up mocks
    scheduler.vulnerabilities.check_pending_statuses.return_value = True
    scheduler.patches.check_pending_statuses.return_value = False
    scheduler.bundles.process_bundles.return_value = False

    # Call competition_api_interactions
    result = scheduler.competition_api_interactions()

    # Verify all components were called
    scheduler.vulnerabilities.check_pending_statuses.assert_called_once()
    scheduler.patches.check_pending_statuses.assert_called_once()
    scheduler.bundles.process_bundles.assert_called_once()
    assert result is True


def test_competition_api_interactions_no_work(scheduler):
    """Test that competition_api_interactions returns False when no work is done."""
    # Set up mocks
    scheduler.vulnerabilities.check_pending_statuses.return_value = False
    scheduler.patches.check_pending_statuses.return_value = False
    scheduler.bundles.process_bundles.return_value = False

    # Call competition_api_interactions
    result = scheduler.competition_api_interactions()

    # Verify all components were called
    scheduler.vulnerabilities.check_pending_statuses.assert_called_once()
    scheduler.patches.check_pending_statuses.assert_called_once()
    scheduler.bundles.process_bundles.assert_called_once()
    assert result is False
