import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from buttercup.common.datastructures.msg_pb2 import (
    BuildOutput,
    BuildType,
    Patch,
    SourceDetail,
    Task,
    TaskReady,
    TracedCrash,
    WeightedHarness,
)
from buttercup.common.maps import BuildMap
from buttercup.common.queues import QueueFactory, RQItem
from buttercup.common.task_meta import TaskMeta
from buttercup.common.task_registry import TaskRegistry
from redis import Redis

from buttercup.orchestrator.scheduler.scheduler import Scheduler
from buttercup.orchestrator.scheduler.submissions import Submissions


@pytest.fixture
def mock_redis():
    return Mock(spec=Redis)


@pytest.fixture
def redis_client():
    res = Redis(host="localhost", port=6379, db=14)
    yield res
    res.flushdb()


@pytest.fixture
def mock_patch_api():
    return Mock()


@pytest.fixture
def mock_task_registry():
    return Mock(spec=TaskRegistry)


@pytest.fixture
def mock_api_client():
    return Mock()


@pytest.fixture
def mock_queues():
    # Create mock queues for all the queues used in the Scheduler
    build_output_queue = Mock()
    ready_queue = Mock()
    index_queue = Mock()
    build_requests_queue = Mock()
    traced_vulnerabilities_queue = Mock()
    patches_queue = Mock()
    confirmed_vulnerabilities_queue = Mock()  # Add this queue

    # Mock QueueFactory
    queue_factory = Mock(spec=QueueFactory)
    queue_factory.create.side_effect = [
        build_output_queue,  # For build_output_queue
        ready_queue,  # For ready_queue
        index_queue,  # For index_queue
        build_requests_queue,  # For build_requests_queue
        traced_vulnerabilities_queue,  # For traced_vulnerabilities_queue
        patches_queue,  # For patches_queue
        confirmed_vulnerabilities_queue,  # For confirmed_vulnerabilities_queue
    ]

    # Create a patch for QueueFactory
    with patch("buttercup.orchestrator.scheduler.scheduler.QueueFactory", return_value=queue_factory):
        yield {
            "factory": queue_factory,
            "build_output": build_output_queue,
            "ready": ready_queue,
            "index": index_queue,
            "build_requests": build_requests_queue,
            "traced": traced_vulnerabilities_queue,
            "patches": patches_queue,
            "confirmed": confirmed_vulnerabilities_queue,
        }


@pytest.fixture
def mock_submissions():
    return Mock(spec=Submissions)


@pytest.fixture
def scheduler(
    mock_redis,
    mock_patch_api,
    mock_task_registry,
    mock_api_client,
    mock_queues,
    mock_submissions,
):
    with (
        patch("buttercup.orchestrator.competition_api_client.PatchApi", return_value=mock_patch_api),
        patch("buttercup.orchestrator.scheduler.scheduler.TaskRegistry", return_value=mock_task_registry),
        patch("buttercup.orchestrator.scheduler.scheduler.Submissions", return_value=mock_submissions),
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

        # Ensure key attributes are set up correctly from the mocked queues
        scheduler.build_output_queue = mock_queues["build_output"]
        scheduler.ready_queue = mock_queues["ready"]
        scheduler.index_queue = mock_queues["index"]
        scheduler.build_requests_queue = mock_queues["build_requests"]
        scheduler.traced_vulnerabilities_queue = mock_queues["traced"]
        scheduler.patches_queue = mock_queues["patches"]
        scheduler.confirmed_vulnerabilities_queue = mock_queues["confirmed"]

        # The submissions object should already be set by patching
        assert scheduler.submissions == mock_submissions

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
        TaskMeta(
            project_name="test-package",
            focus="test-focus",
            task_id="task-id-build-output",
            metadata={"task_id": "task-id-build-output", "round_id": "testing", "team_id": "tob"},
        ).save(task_dir)

        build_output = BuildOutput(
            engine="libfuzzer",
            sanitizer="address",
            task_dir=str(task_dir),
            task_id="blah",
            build_type=BuildType.FUZZER,
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
        weight=1.0,
        harness_name="live-harness",
        package_name="test-package",
        task_id="live-task-123",
    )

    expired_harness = WeightedHarness(
        weight=1.0,
        harness_name="expired-harness",
        package_name="test-package",
        task_id="expired-task-456",
    )

    cancelled_harness = WeightedHarness(
        weight=1.0,
        harness_name="cancelled-harness",
        package_name="test-package",
        task_id="cancelled-task-789",
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
        weight=1.0,
        harness_name="live-harness",
        package_name="test-package",
        task_id="live-task-123",
    )

    zero_expired_harness = WeightedHarness(
        weight=0.0,
        harness_name="zero-expired-harness",
        package_name="test-package",
        task_id="expired-task-456",
    )

    zero_cancelled_harness = WeightedHarness(
        weight=0.0,
        harness_name="zero-cancelled-harness",
        package_name="test-package",
        task_id="cancelled-task-789",
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


def test_serve_item_processes_cancellations_then_updates_cache(scheduler):
    """Test that serve_item runs process_cancellations first, then updates the cached cancelled IDs."""
    # Setup
    scheduler.cancellation = Mock()
    scheduler.cancellation.process_cancellations = Mock(return_value=True)

    # Mock the methods called by serve_item
    scheduler.update_cached_cancelled_ids = Mock(return_value=True)
    scheduler.serve_ready_task = Mock(return_value=False)
    scheduler.serve_build_output = Mock(return_value=False)
    scheduler.serve_index_output = Mock(return_value=False)
    scheduler.competition_api_interactions = Mock(return_value=False)
    scheduler.update_expired_task_weights = Mock(return_value=False)

    # Execute
    result = scheduler.serve_item()

    # Verify
    assert result is True
    scheduler.cancellation.process_cancellations.assert_called_once()
    scheduler.update_cached_cancelled_ids.assert_called_once()
    scheduler.serve_ready_task.assert_called_once()
    scheduler.serve_build_output.assert_called_once()
    scheduler.serve_index_output.assert_called_once()
    scheduler.competition_api_interactions.assert_called_once()
    scheduler.update_expired_task_weights.assert_called_once()


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
        build_type=BuildType.FUZZER,
    )

    # Create a mock RQItem
    mock_item = RQItem(item_id="build-item-1", deserialized=build_output)

    # Mock the queue pop to return our item
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

    # Mock the queue pop to return our item
    scheduler.ready_queue.pop.return_value = mock_item

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
    """Test that competition_api_interactions processes traced crashes and patches."""
    # Create test data
    traced_crash = TracedCrash()
    traced_crash.crash.target.task_id = "test-task-id"

    patch = Patch()
    patch.task_id = "test-task-id"
    patch.internal_patch_id = "0"

    # Set up queue mocks with items
    scheduler.traced_vulnerabilities_queue.pop.return_value = RQItem(item_id="vuln-1", deserialized=traced_crash)
    scheduler.patches_queue.pop.return_value = RQItem(item_id="patch-1", deserialized=patch)

    # Set up submissions to return True for submit_vulnerability and record_patch
    scheduler.submissions.submit_vulnerability.return_value = True
    scheduler.submissions.record_patch.return_value = True

    # Call the method
    result = scheduler.competition_api_interactions()

    # Verify interactions
    scheduler.submissions.submit_vulnerability.assert_called_once_with(traced_crash)
    scheduler.traced_vulnerabilities_queue.ack_item.assert_called_once_with("vuln-1")

    scheduler.submissions.record_patch.assert_called_once_with(patch)
    scheduler.patches_queue.ack_item.assert_called_once_with("patch-1")

    scheduler.submissions.process_cycle.assert_called_once()

    assert result is True


def test_competition_api_interactions_no_work(scheduler):
    """Test that competition_api_interactions returns False when no items in queue."""
    # Set up queue mocks with no items
    scheduler.traced_vulnerabilities_queue.pop.return_value = None
    scheduler.patches_queue.pop.return_value = None

    # Call the method
    result = scheduler.competition_api_interactions()

    # Verify
    scheduler.submissions.submit_vulnerability.assert_not_called()
    scheduler.submissions.record_patch.assert_not_called()
    scheduler.submissions.process_cycle.assert_called_once()

    assert result is False


def test_competition_api_interactions_failed_submissions(scheduler):
    """Test that competition_api_interactions handles failed submissions."""
    # Create test data
    traced_crash = TracedCrash()
    traced_crash.crash.target.task_id = "test-task-id"

    patch = Patch()
    patch.task_id = "test-task-id"
    patch.internal_patch_id = "0"

    # Set up queue mocks with items
    scheduler.traced_vulnerabilities_queue.pop.return_value = RQItem(item_id="vuln-1", deserialized=traced_crash)
    scheduler.patches_queue.pop.return_value = RQItem(item_id="patch-1", deserialized=patch)

    # Set up submissions to return False for submit_vulnerability and record_patch
    scheduler.submissions.submit_vulnerability.return_value = False
    scheduler.submissions.record_patch.return_value = False

    # Call the method
    result = scheduler.competition_api_interactions()

    # Verify interactions
    scheduler.submissions.submit_vulnerability.assert_called_once_with(traced_crash)
    scheduler.traced_vulnerabilities_queue.ack_item.assert_not_called()

    scheduler.submissions.record_patch.assert_called_once_with(patch)
    scheduler.patches_queue.ack_item.assert_not_called()

    scheduler.submissions.process_cycle.assert_called_once()

    assert result is False


def test_serve_build_output_stores_patched_and_nonpatched_builds(scheduler, redis_client):
    """Test that serve_build_output correctly stores builds with and without patches and they can be retrieved."""
    # Set up a real BuildMap for testing storage and retrieval using scheduler's redis
    real_build_map = BuildMap(redis_client)
    scheduler.build_map = real_build_map

    # Create BuildOutput objects - one without patch, one with patch
    build_without_patch = BuildOutput(
        engine="libfuzzer",
        sanitizer="address",
        task_dir="/path/to/task1",
        task_id="test-task-1",
        build_type=BuildType.FUZZER,
        internal_patch_id="",  # No patch
    )

    build_with_patch = BuildOutput(
        engine="libfuzzer",
        sanitizer="address",
        task_dir="/path/to/task1",
        task_id="test-task-1",
        build_type=BuildType.PATCH,
        internal_patch_id="patch-123",  # With patch
    )

    # Create another build with different sanitizer for the same task
    build_different_san = BuildOutput(
        engine="libfuzzer",
        sanitizer="memory",
        task_dir="/path/to/task1",
        task_id="test-task-1",
        build_type=BuildType.FUZZER,
        internal_patch_id="",
    )

    # Create mock RQItems
    mock_item1 = RQItem(item_id="build-item-1", deserialized=build_without_patch)
    mock_item2 = RQItem(item_id="build-item-2", deserialized=build_with_patch)
    mock_item3 = RQItem(item_id="build-item-3", deserialized=build_different_san)

    # Mock the queue to return items sequentially, then None
    scheduler.build_output_queue.pop.side_effect = [mock_item1, mock_item2, mock_item3, None]

    # Mock should_stop_processing to return False (task is not cancelled/expired)
    original_should_stop_processing = scheduler.should_stop_processing
    scheduler.should_stop_processing = Mock(return_value=False)

    # Mock harness_map and process_build_output to focus on build storage
    scheduler.harness_map = Mock()
    scheduler.process_build_output = Mock(return_value=[])

    # Call serve_build_output multiple times to process all items
    result1 = scheduler.serve_build_output()
    result2 = scheduler.serve_build_output()
    result3 = scheduler.serve_build_output()
    result4 = scheduler.serve_build_output()  # This should return False (no more items)

    # Verify results
    assert result1 is True, "First call should return True"
    assert result2 is True, "Second call should return True"
    assert result3 is True, "Third call should return True"
    assert result4 is False, "Fourth call should return False (no items)"

    # Verify all items were acknowledged
    scheduler.build_output_queue.ack_item.assert_any_call("build-item-1")
    scheduler.build_output_queue.ack_item.assert_any_call("build-item-2")
    scheduler.build_output_queue.ack_item.assert_any_call("build-item-3")
    assert scheduler.build_output_queue.ack_item.call_count == 3

    # Test retrieval of builds from BuildMap

    # 1. Get all builds for the task (non-patched) - should return 2 builds (address and memory sanitizers)
    non_patched_builds = real_build_map.get_builds("test-task-1", BuildType.FUZZER, "")
    assert len(non_patched_builds) == 2, "Should have 2 non-patched builds"

    # Verify the builds are correct
    sanitizers = {build.sanitizer for build in non_patched_builds}
    assert sanitizers == {"address", "memory"}, "Should have address and memory sanitizer builds"

    for build in non_patched_builds:
        assert build.task_id == "test-task-1"
        assert build.build_type == BuildType.FUZZER
        assert build.internal_patch_id == ""

    # 2. Get patched builds - should return 1 build
    patched_builds = real_build_map.get_builds("test-task-1", BuildType.PATCH, "patch-123")
    assert len(patched_builds) == 1, "Should have 1 patched build"

    patched_build = patched_builds[0]
    assert patched_build.task_id == "test-task-1"
    assert patched_build.sanitizer == "address"
    assert patched_build.build_type == BuildType.PATCH
    assert patched_build.internal_patch_id == "patch-123"

    # 3. Test getting specific build by sanitizer
    specific_build = real_build_map.get_build_from_san("test-task-1", BuildType.FUZZER, "address", "")
    assert specific_build is not None
    assert specific_build.sanitizer == "address"
    assert specific_build.internal_patch_id == ""

    specific_patched_build = real_build_map.get_build_from_san("test-task-1", BuildType.PATCH, "address", "patch-123")
    assert specific_patched_build is not None
    assert specific_patched_build.sanitizer == "address"
    assert specific_patched_build.internal_patch_id == "patch-123"

    # 4. Test getting non-existent build
    non_existent = real_build_map.get_build_from_san("test-task-1", BuildType.FUZZER, "undefined", "")
    assert non_existent is None

    non_existent_patch = real_build_map.get_build_from_san(
        "test-task-1",
        BuildType.PATCH,
        "address",
        "non-existent-patch",
    )
    assert non_existent_patch is None

    # Restore original method
    scheduler.should_stop_processing = original_should_stop_processing
