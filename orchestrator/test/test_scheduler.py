import pytest
from unittest.mock import Mock, patch
from redis import Redis

from buttercup.common.datastructures.msg_pb2 import Task, TaskReady, SourceDetail, BuildOutput, WeightedHarness
from buttercup.common.maps import BUILD_TYPES

from buttercup.common.queues import RQItem
from buttercup.orchestrator.scheduler.scheduler import Scheduler

import tempfile
from pathlib import Path


@pytest.fixture
def mock_redis():
    return Mock(spec=Redis)


@pytest.fixture
def scheduler(mock_redis, tmp_path):
    return Scheduler(tasks_storage_dir=tmp_path, scratch_dir=tmp_path, redis=mock_redis)


@pytest.mark.skip(reason="Not implemented")
def test_process_ready_task(scheduler):
    # Create a mock task with example-libpng source
    source = SourceDetail(source_type=SourceDetail.SourceType.SOURCE_TYPE_REPO, url="https://github.com/libpng/libpng")
    task = Task(task_id="test-task-1", sources=[source])

    build_request = scheduler.process_ready_task(task)

    assert build_request.package_name == "libpng"
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
        src_dir.mkdir(parents=True, exist_ok=True)
        tooling_dir.mkdir(parents=True, exist_ok=True)
        ossfuzz_dir.mkdir(parents=True, exist_ok=True)
        source_code_dir.mkdir(parents=True, exist_ok=True)
        stub_helper_py.parent.mkdir(parents=True, exist_ok=True)
        stub_helper_py.touch()

        build_output = BuildOutput(
            package_name="test-package",
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
