import pytest
from redis import Redis
from buttercup.common.maps import RedisMap
from buttercup.common.datastructures.fuzzer_msg_pb2 import WeightedTarget

@pytest.fixture
def redis_client():
    return Redis(host="localhost", port=6379, db=0)

def test_redis_map_set_and_get(redis_client):
    # Create a RedisMap instance
    redis_map = RedisMap(redis_client, "test_hash", WeightedTarget)
    
    # Create a WeightedTarget
    target = WeightedTarget()
    target.target.package_name = "test_package"
    target.target.engine = "test_engine"
    target.target.sanitizer = "test_sanitizer"
    target.target.output_ossfuzz_path = "/path/to/output"
    target.target.source_path = "/path/to/source"
    target.weight = 1.0

    # Set the target with a key
    test_key = "test_key"
    redis_map.set(test_key, target)

    # Retrieve the target
    retrieved_target = redis_map.get(test_key)

    # Verify the retrieved target matches the original
    assert retrieved_target.target.package_name == target.target.package_name
    assert retrieved_target.target.engine == target.target.engine
    assert retrieved_target.target.sanitizer == target.target.sanitizer
    assert retrieved_target.target.output_ossfuzz_path == target.target.output_ossfuzz_path
    assert retrieved_target.target.source_path == target.target.source_path
    assert retrieved_target.weight == target.weight

    # Clean up
    redis_client.delete("test_hash")

def test_redis_map_iteration(redis_client):
    # Create a RedisMap instance
    redis_map = RedisMap(redis_client, "test_hash_iter", WeightedTarget)
    
    # Create a WeightedTarget
    target = WeightedTarget()
    target.target.package_name = "test_package"
    target.target.engine = "test_engine"
    target.target.sanitizer = "test_sanitizer"
    target.target.output_ossfuzz_path = "/path/to/output"
    target.target.source_path = "/path/to/source"
    target.weight = 1.0

    # Set the target with a key
    test_key = "test_key"
    redis_map.set(test_key, target)

    # Iterate over the map and collect results
    targets = list(redis_map)
    
    # Verify we got exactly one target
    assert len(targets) == 1
    
    # Verify the iterated target matches the original
    retrieved_target = targets[0]
    assert retrieved_target.target.package_name == target.target.package_name
    assert retrieved_target.target.engine == target.target.engine
    assert retrieved_target.target.sanitizer == target.target.sanitizer
    assert retrieved_target.target.output_ossfuzz_path == target.target.output_ossfuzz_path
    assert retrieved_target.target.source_path == target.target.source_path
    assert retrieved_target.weight == target.weight

    # Clean up
    redis_client.delete("test_hash_iter")

