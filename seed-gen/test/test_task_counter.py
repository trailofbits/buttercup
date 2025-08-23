import pytest
from redis import Redis

from buttercup.seed_gen.task import TaskName
from buttercup.seed_gen.task_counter import TaskCounter


@pytest.fixture
def redis_client():
    res = Redis(host="localhost", port=6379, db=14)
    yield res
    res.flushdb()


def test_task_counter_increment_and_get(redis_client):
    # Create a TaskCounter instance
    counter = TaskCounter(redis_client)

    # Test incrementing and getting count
    harness_name = "test_harness"
    package_name = "test_package"
    task_id = "test_task"
    task_name = TaskName.SEED_INIT.value

    assert counter.get_count(harness_name, package_name, task_id, task_name) == 0

    new_count = counter.increment(harness_name, package_name, task_id, task_name)
    assert new_count == 1
    assert counter.get_count(harness_name, package_name, task_id, task_name) == 1

    new_count = counter.increment(harness_name, package_name, task_id, task_name)
    assert new_count == 2
    assert counter.get_count(harness_name, package_name, task_id, task_name) == 2


def test_task_counter_concurrent_access(redis_client):
    # Create two TaskCounter instances to simulate concurrent access
    counter1 = TaskCounter(redis_client)
    counter2 = TaskCounter(redis_client)

    harness_name = "test_harness"
    package_name = "test_package"
    task_id = "test_task"
    task_name = TaskName.SEED_INIT.value

    assert counter1.get_count(harness_name, package_name, task_id, task_name) == 0
    assert counter2.get_count(harness_name, package_name, task_id, task_name) == 0

    count1 = counter1.increment(harness_name, package_name, task_id, task_name)
    count2 = counter2.increment(harness_name, package_name, task_id, task_name)

    assert count1 == 1
    assert count2 == 2
    assert counter1.get_count(harness_name, package_name, task_id, task_name) == 2
    assert counter2.get_count(harness_name, package_name, task_id, task_name) == 2


def test_task_counter_get_all_counts(redis_client):
    counter = TaskCounter(redis_client)

    harness_name = "test_harness"
    package_name = "test_package"
    task_id = "test_task"

    counts = counter.get_all_counts(harness_name, package_name, task_id)
    for task_name in TaskName:
        assert counts[task_name.value] == 0

    counter.increment(harness_name, package_name, task_id, TaskName.SEED_INIT.value)
    counter.increment(harness_name, package_name, task_id, TaskName.SEED_INIT.value)
    counter.increment(harness_name, package_name, task_id, TaskName.VULN_DISCOVERY.value)

    counts = counter.get_all_counts(harness_name, package_name, task_id)
    assert counts[TaskName.SEED_INIT.value] == 2
    assert counts[TaskName.VULN_DISCOVERY.value] == 1
    assert counts[TaskName.SEED_EXPLORE.value] == 0
