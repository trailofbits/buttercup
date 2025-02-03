import pytest
from redis import Redis
from buttercup.common.maps import RedisMap
from buttercup.common.datastructures.msg_pb2 import WeightedHarness


@pytest.fixture
def redis_client():
    return Redis(host="localhost", port=6379, db=0)


def test_redis_map_set_and_get(redis_client):
    # Create a RedisMap instance
    redis_map = RedisMap(redis_client, "test_hash", WeightedHarness)

    # Create a WeightedHarness
    harness = WeightedHarness()
    harness.package_name = "test_package"
    harness.harness_name = "test_harness"
    harness.task_id = "test_task_id"
    harness.weight = 1.0

    # Set the target with a key
    test_key = "test_key"
    redis_map.set(test_key, harness)

    # Retrieve the target
    retrieved_target = redis_map.get(test_key)

    # Verify the retrieved target matches the original
    assert retrieved_target.package_name == harness.package_name
    assert retrieved_target.harness_name == harness.harness_name
    assert retrieved_target.task_id == harness.task_id
    assert retrieved_target.weight == harness.weight

    # Clean up
    redis_client.delete("test_hash")


def test_redis_map_iteration(redis_client):
    # Create a RedisMap instance
    redis_map = RedisMap(redis_client, "test_hash_iter", WeightedHarness)

    # Create a WeightedHarness
    harness = WeightedHarness()
    harness.package_name = "test_package"
    harness.harness_name = "test_harness"
    harness.task_id = "test_task_id"
    harness.weight = 1.0

    # Set the target with a key
    test_key = "test_key"
    redis_map.set(test_key, harness)

    # Iterate over the map and collect results
    harnesses = list(redis_map)

    # Verify we got exactly one harness
    assert len(harnesses) == 1

    # Verify the iterated target matches the original
    retrieved_harness = harnesses[0]
    assert retrieved_harness.package_name == harness.package_name
    assert retrieved_harness.harness_name == harness.harness_name
    assert retrieved_harness.task_id == harness.task_id
    assert retrieved_harness.weight == harness.weight

    # Clean up
    redis_client.delete("test_hash_iter")
