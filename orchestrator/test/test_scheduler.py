import pytest
from unittest.mock import Mock, patch
from redis import Redis

from buttercup.common.datastructures.msg_pb2 import Task, TaskReady, SourceDetail, BuildOutput, WeightedTarget

from buttercup.common.queues import RQItem
from buttercup.orchestrator.scheduler.scheduler import Scheduler


@pytest.fixture
def mock_redis():
    return Mock(spec=Redis)


@pytest.fixture
def scheduler(mock_redis, tmp_path):
    return Scheduler(tasks_storage_dir=tmp_path, redis=mock_redis)


@pytest.mark.skip(reason="Not implemented")
def test_process_ready_task(scheduler):
    # Create a mock task with example-libpng source
    source = SourceDetail(source_type=SourceDetail.SourceType.SOURCE_TYPE_REPO, path="example-libpng")
    task = Task(task_id="test-task-1", sources=[source])

    build_request = scheduler.process_ready_task(task)

    assert build_request.package_name == "libpng"
    assert build_request.engine == "libfuzzer"
    assert build_request.sanitizer == "address"
    assert build_request.ossfuzz == "/tasks_storage/test-task-1/fuzz-tooling"


def test_process_ready_task_mock_mode_invalid_source(scheduler):
    # Create a mock task with invalid source
    source = SourceDetail(source_type=SourceDetail.SourceType.SOURCE_TYPE_REPO, path="invalid-source")
    task = Task(task_id="test-task-2", sources=[source])

    with pytest.raises(RuntimeError, match="Couldn't handle task test-task-2"):
        scheduler.process_ready_task(task)


@patch("buttercup.orchestrator.scheduler.scheduler.get_fuzz_targets")
def test_process_build_output(mock_get_fuzz_targets, scheduler):
    mock_get_fuzz_targets.return_value = ["target1", "target2"]

    build_output = BuildOutput(
        package_name="test-package",
        engine="libfuzzer",
        sanitizer="address",
        output_ossfuzz_path="/path/to/output",
        source_path="/path/to/source",
    )

    targets = scheduler.process_build_output(build_output)

    assert len(targets) == 2
    assert all(isinstance(t, WeightedTarget) for t in targets)
    assert all(t.weight == 1.0 for t in targets)
    assert all(t.target == build_output for t in targets)
    assert [t.harness_path for t in targets] == ["target1", "target2"]


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
