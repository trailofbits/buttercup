import pytest
from redis import Redis
from buttercup.common.sets import RedisSet, PoVReproduceStatus
from buttercup.common.datastructures.msg_pb2 import POVReproduceRequest, POVReproduceResponse
from unittest.mock import MagicMock


@pytest.fixture
def redis_client():
    return Redis(host="localhost", port=6379, db=0)


@pytest.fixture
def pov_status(redis_client):
    """Fixture for PoVReproduceStatus instance with real Redis client."""
    return PoVReproduceStatus(redis_client)


@pytest.fixture
def sample_params():
    """Fixture with sample parameters for PoV reproduction testing."""
    return {
        "task_id": "task-123",
        "internal_patch_id": "0/1",
        "pov_path": "/path/to/pov.bin",
        "sanitizer": "asan",
        "harness_name": "test_harness",
    }


@pytest.fixture
def sample_request(sample_params):
    """Fixture with sample POVReproduceRequest for testing."""
    request = POVReproduceRequest()
    request.task_id = sample_params["task_id"]
    request.internal_patch_id = sample_params["internal_patch_id"]
    request.pov_path = sample_params["pov_path"]
    request.sanitizer = sample_params["sanitizer"]
    request.harness_name = sample_params["harness_name"]
    return request


def _create_request_from_params(params):
    """Helper function to create POVReproduceRequest from parameter dict."""
    request = POVReproduceRequest()
    request.task_id = params["task_id"]
    request.internal_patch_id = params["internal_patch_id"]
    request.pov_path = params["pov_path"]
    request.sanitizer = params["sanitizer"]
    request.harness_name = params["harness_name"]
    return request


@pytest.fixture(autouse=True)
def cleanup_redis(redis_client):
    """Fixture to clean up Redis sets after each test."""
    yield
    # Clean up all PoV reproduce sets after each test
    redis_client.delete("pov_reproduce_pending")
    redis_client.delete("pov_reproduce_mitigated")
    redis_client.delete("pov_reproduce_non_mitigated")
    redis_client.delete("pov_reproduce_non_expired")  # Clean up expired set too


def test_redis_set_add_and_contains(redis_client):
    # Create a RedisSet instance
    redis_set = RedisSet(redis_client, "test_set")

    # Test adding a value
    test_value = "test_value"
    was_present = redis_set.add(test_value)
    assert not was_present  # Should return False since value wasn't already in set

    # Verify the value is in the set
    assert redis_set.contains(test_value)

    # Add same value again
    was_present = redis_set.add(test_value)
    assert was_present  # Should return True since value was already in set

    # Clean up
    redis_client.delete("test_set")


def test_redis_set_remove(redis_client):
    # Create a RedisSet instance
    redis_set = RedisSet(redis_client, "test_set_remove")

    # Add a value
    test_value = "test_value"
    redis_set.add(test_value)

    # Test removing the value
    was_present = redis_set.remove(test_value)
    assert was_present  # Should return True since value was in set

    # Verify value was removed
    assert not redis_set.contains(test_value)

    # Try removing non-existent value
    was_present = redis_set.remove("nonexistent")
    assert not was_present  # Should return False since value wasn't in set

    # Clean up
    redis_client.delete("test_set_remove")


def test_redis_set_iteration_and_length(redis_client):
    # Create a RedisSet instance
    redis_set = RedisSet(redis_client, "test_set_iter")

    # Add some values
    test_values = ["value1", "value2", "value3"]
    for value in test_values:
        redis_set.add(value)

    # Test length
    assert len(redis_set) == len(test_values)

    # Test iteration
    retrieved_values = list(redis_set)
    assert len(retrieved_values) == len(test_values)
    for value in test_values:
        assert value in retrieved_values

    # Clean up
    redis_client.delete("test_set_iter")


# Tests for PoVReproduceStatus class
class TestPoVReproduceStatus:
    """Test suite for PoVReproduceStatus class."""

    def test_initialization(self, redis_client):
        """Test PoVReproduceStatus initialization."""
        pov_status = PoVReproduceStatus(redis_client)
        assert pov_status.redis == redis_client

    def test_request_status_first_time_returns_none(self, pov_status, sample_request):
        """Test request_status for first time - should return None (pending)."""
        result = pov_status.request_status(sample_request)
        assert result is None  # Indicates pending status

    def test_request_status_pending_returns_none(self, pov_status, sample_request):
        """Test request_status when already pending - should return None."""
        # First request creates pending status
        first_result = pov_status.request_status(sample_request)
        assert first_result is None

        # Second request should still return None (pending)
        second_result = pov_status.request_status(sample_request)
        assert second_result is None

    def test_mark_mitigated_then_request_status(self, pov_status, sample_request):
        """Test marking PoV as mitigated and then checking status."""
        # First request to create pending status
        pov_status.request_status(sample_request)

        # Mark as mitigated - should return True since item was pending
        result = pov_status.mark_mitigated(sample_request)
        assert result is True

        # Request status should now return POVReproduceResponse with did_crash=False
        result = pov_status.request_status(sample_request)
        assert isinstance(result, POVReproduceResponse)
        assert result.did_crash is False

    def test_mark_non_mitigated_then_request_status(self, pov_status, sample_request):
        """Test marking PoV as non-mitigated and then checking status."""
        # First request to create pending status
        pov_status.request_status(sample_request)

        # Mark as non-mitigated - should return True since item was pending
        result = pov_status.mark_non_mitigated(sample_request)
        assert result is True

        # Request status should now return POVReproduceResponse with did_crash=True
        result = pov_status.request_status(sample_request)
        assert isinstance(result, POVReproduceResponse)
        assert result.did_crash is True

    def test_mark_expired_then_request_status(self, pov_status, sample_request):
        """Test marking PoV as expired and then checking status."""
        # First request to create pending status
        pov_status.request_status(sample_request)

        # Mark as expired - should return True since item was pending
        result = pov_status.mark_expired(sample_request)
        assert result is True

        # Request status should create a new pending item (since expired items are not checked)
        result = pov_status.request_status(sample_request)
        assert result is None  # Should be pending again

    def test_mitigated_status_persists(self, pov_status, sample_request):
        """Test that mitigated status persists across multiple requests."""
        # Create pending and mark as mitigated
        pov_status.request_status(sample_request)
        pov_status.mark_mitigated(sample_request)

        # Multiple status requests should all return POVReproduceResponse with did_crash=False
        for _ in range(3):
            result = pov_status.request_status(sample_request)
            assert isinstance(result, POVReproduceResponse)
            assert result.did_crash is False

    def test_non_mitigated_status_persists(self, pov_status, sample_request):
        """Test that non-mitigated status persists across multiple requests."""
        # Create pending and mark as non-mitigated
        pov_status.request_status(sample_request)
        pov_status.mark_non_mitigated(sample_request)

        # Multiple status requests should all return POVReproduceResponse with did_crash=True
        for _ in range(3):
            result = pov_status.request_status(sample_request)
            assert isinstance(result, POVReproduceResponse)
            assert result.did_crash is True

    def test_get_one_pending_empty(self, pov_status):
        """Test get_one_pending when no pending items exist."""
        result = pov_status.get_one_pending()
        assert result is None

    def test_get_one_pending_with_item(self, pov_status, sample_request):
        """Test get_one_pending when pending items exist."""
        # Create a pending item
        pov_status.request_status(sample_request)

        # Should return the pending item
        result = pov_status.get_one_pending()
        assert result is not None
        assert isinstance(result, POVReproduceRequest)
        # Compare the key fields to verify it's the same request
        assert result.task_id == sample_request.task_id
        assert result.internal_patch_id == sample_request.internal_patch_id
        assert result.pov_path == sample_request.pov_path
        assert result.sanitizer == sample_request.sanitizer
        assert result.harness_name == sample_request.harness_name

    def test_get_one_pending_multiple_items(self, pov_status, sample_params):
        """Test get_one_pending when multiple pending items exist."""
        # Create multiple pending items using different parameters
        params1 = sample_params.copy()
        params2 = sample_params.copy()
        params2["task_id"] = "different-task"
        params3 = sample_params.copy()
        params3["sanitizer"] = "msan"

        request1 = _create_request_from_params(params1)
        request2 = _create_request_from_params(params2)
        request3 = _create_request_from_params(params3)

        pov_status.request_status(request1)
        pov_status.request_status(request2)
        pov_status.request_status(request3)

        # Should return one of the pending items
        result = pov_status.get_one_pending()
        assert result is not None
        # Check that it's one of the three we created
        assert result.task_id in [request1.task_id, request2.task_id, request3.task_id]

    def test_get_one_pending_excludes_completed_items(self, pov_status, sample_params):
        """Test that get_one_pending only returns pending items, not completed ones."""
        # Create multiple items using different parameters
        params1 = sample_params.copy()
        params2 = sample_params.copy()
        params2["task_id"] = "task-2"
        params3 = sample_params.copy()
        params3["task_id"] = "task-3"
        params4 = sample_params.copy()
        params4["task_id"] = "task-4"

        request1 = _create_request_from_params(params1)
        request2 = _create_request_from_params(params2)
        request3 = _create_request_from_params(params3)
        request4 = _create_request_from_params(params4)

        # Make all pending
        pov_status.request_status(request1)
        pov_status.request_status(request2)
        pov_status.request_status(request3)
        pov_status.request_status(request4)

        # Complete some of them in different ways - all should return True since items were pending
        result1 = pov_status.mark_mitigated(request1)
        result2 = pov_status.mark_non_mitigated(request2)
        result3 = pov_status.mark_expired(request3)
        assert result1 is True
        assert result2 is True
        assert result3 is True
        # request4 remains pending

        # get_one_pending should only return the pending item
        result = pov_status.get_one_pending()
        assert result.task_id == request4.task_id

    def test_mark_expired_removes_from_pending(self, pov_status, sample_request):
        """Test that mark_expired removes item from pending list."""
        # Create a pending item
        pov_status.request_status(sample_request)

        # Verify it appears in pending
        pending = pov_status.get_one_pending()
        assert pending.task_id == sample_request.task_id

        # Mark as expired - should return True since item was pending
        result = pov_status.mark_expired(sample_request)
        assert result is True

        # Should no longer appear in pending
        pending = pov_status.get_one_pending()
        assert pending is None

    def test_mark_expired_allows_new_request(self, pov_status, sample_request):
        """Test that after marking expired, the same parameters can be requested again."""
        # First cycle: request and mark expired
        pov_status.request_status(sample_request)
        result = pov_status.mark_expired(sample_request)
        assert result is True

        # Second cycle: should be able to request again
        result = pov_status.request_status(sample_request)
        assert result is None  # Should be pending

        # Should appear in pending again
        pending = pov_status.get_one_pending()
        assert pending.task_id == sample_request.task_id

        # Can complete normally this time
        result = pov_status.mark_mitigated(sample_request)
        assert result is True
        result = pov_status.request_status(sample_request)
        assert isinstance(result, POVReproduceResponse)
        assert result.did_crash is False  # Mitigated

    def test_different_parameters_are_tracked_separately(self, pov_status):
        """Test that different parameter sets are tracked as separate items."""
        params1 = {
            "task_id": "task-1",
            "internal_patch_id": "0/1",
            "pov_path": "/path1.bin",
            "sanitizer": "asan",
            "harness_name": "harness1",
        }

        params2 = {
            "task_id": "task-2",
            "internal_patch_id": "0/2",
            "pov_path": "/path2.bin",
            "sanitizer": "msan",
            "harness_name": "harness2",
        }

        request1 = _create_request_from_params(params1)
        request2 = _create_request_from_params(params2)

        # Create pending status for both
        result1 = pov_status.request_status(request1)
        result2 = pov_status.request_status(request2)
        assert result1 is None  # Pending
        assert result2 is None  # Pending

        # Mark them differently - both should return True since items were pending
        mark_result1 = pov_status.mark_mitigated(request1)
        mark_result2 = pov_status.mark_non_mitigated(request2)
        assert mark_result1 is True
        assert mark_result2 is True

        # Check they have different statuses
        status1 = pov_status.request_status(request1)
        status2 = pov_status.request_status(request2)
        assert isinstance(status1, POVReproduceResponse)
        assert status1.did_crash is False  # Mitigated
        assert isinstance(status2, POVReproduceResponse)
        assert status2.did_crash is True  # Non-mitigated

    def test_parameter_sensitivity(self, pov_status, sample_params):
        """Test that changing any parameter creates a different tracking entry."""
        # Create baseline pending item
        base_request = _create_request_from_params(sample_params)
        pov_status.request_status(base_request)
        pov_status.mark_mitigated(base_request)

        # Test that changing each parameter individually creates new entries
        for param_name in sample_params.keys():
            modified_params = sample_params.copy()
            if param_name == "internal_patch_id":
                modified_params[param_name] = f"modified_{sample_params[param_name]}"
            else:
                modified_params[param_name] = f"modified_{sample_params[param_name]}"

            modified_request = _create_request_from_params(modified_params)

            # New parameters should start as pending
            result = pov_status.request_status(modified_request)
            assert result is None  # Should be pending, not mitigated

            # Original parameters should still be mitigated
            original_result = pov_status.request_status(base_request)
            assert isinstance(original_result, POVReproduceResponse)
            assert original_result.did_crash is False  # Mitigated

    def test_complete_workflow(self, pov_status, sample_request):
        """Test a complete workflow from request to completion."""
        # Step 1: Initial request should return None (pending)
        result = pov_status.request_status(sample_request)
        assert result is None

        # Step 2: Subsequent requests while pending should return None
        result = pov_status.request_status(sample_request)
        assert result is None

        # Step 3: Item should appear in pending list
        pending = pov_status.get_one_pending()
        assert pending.task_id == sample_request.task_id

        # Step 4: Mark as mitigated - should return True since item was pending
        mark_result = pov_status.mark_mitigated(sample_request)
        assert mark_result is True

        # Step 5: Status should now be MITIGATED
        result = pov_status.request_status(sample_request)
        assert isinstance(result, POVReproduceResponse)
        assert result.did_crash is False  # Mitigated

        # Step 6: Should no longer appear in pending list
        # (Create another pending item to test this)
        other_params = {
            "task_id": "other-task",
            "internal_patch_id": "0/1",
            "pov_path": "/path/to/pov.bin",
            "sanitizer": "asan",
            "harness_name": "test_harness",
        }
        other_request = _create_request_from_params(other_params)
        pov_status.request_status(other_request)

        pending = pov_status.get_one_pending()
        assert pending.task_id == other_request.task_id  # Should be the other item, not the completed one

    def test_alternative_workflow_non_mitigated(self, pov_status, sample_request):
        """Test workflow ending with non-mitigated status."""
        # Create pending item
        pov_status.request_status(sample_request)

        # Mark as non-mitigated instead of mitigated - should return True since item was pending
        mark_result = pov_status.mark_non_mitigated(sample_request)
        assert mark_result is True

        # Status should be NON_MITIGATED
        result = pov_status.request_status(sample_request)
        assert isinstance(result, POVReproduceResponse)
        assert result.did_crash is True  # Non-mitigated

        # Should not appear in pending anymore
        pending = pov_status.get_one_pending()
        assert pending is None

    def test_alternative_workflow_expired(self, pov_status, sample_request):
        """Test workflow ending with expired status."""
        # Create pending item
        pov_status.request_status(sample_request)

        # Mark as expired instead of completed - should return True since item was pending
        mark_result = pov_status.mark_expired(sample_request)
        assert mark_result is True

        # Should not appear in pending anymore
        pending = pov_status.get_one_pending()
        assert pending is None

        # Status request should create new pending item (expired items are not tracked)
        result = pov_status.request_status(sample_request)
        assert result is None  # Pending again

    def test_marking_without_pending_request(self, pov_status, sample_params):
        """Test behavior when marking items that were never requested."""
        request1 = _create_request_from_params(sample_params)

        # Try to mark as mitigated without first requesting - should return False
        mark_result1 = pov_status.mark_mitigated(request1)
        assert mark_result1 is False

        # Try to mark as non-mitigated without first requesting - should return False
        other_params = sample_params.copy()
        other_params["task_id"] = "other-task"
        request2 = _create_request_from_params(other_params)
        mark_result2 = pov_status.mark_non_mitigated(request2)
        assert mark_result2 is False

        # Try to mark as expired without first requesting - should return False
        third_params = sample_params.copy()
        third_params["task_id"] = "third-task"
        request3 = _create_request_from_params(third_params)
        mark_result3 = pov_status.mark_expired(request3)
        assert mark_result3 is False

        # Check what status returns (implementation dependent)
        _result1 = pov_status.request_status(request1)
        _result2 = pov_status.request_status(request2)
        _result3 = pov_status.request_status(request3)
        # The exact behavior here depends on implementation,
        # but it should be consistent and not crash

    def test_concurrent_operations_simulation(self, pov_status):
        """Test simulated concurrent operations on different items."""
        # Simulate multiple items being processed concurrently
        items = []
        requests = []
        for i in range(6):  # Increased to 6 to test expired status
            params = {
                "task_id": f"task-{i}",
                "internal_patch_id": f"0/{i}",
                "pov_path": f"/path/{i}.bin",
                "sanitizer": "asan",
                "harness_name": f"harness-{i}",
            }
            items.append(params)
            request = _create_request_from_params(params)
            requests.append(request)

            # Request status for each (should all be pending)
            result = pov_status.request_status(request)
            assert result is None

        # Mark items with different outcomes - all should return True since items were pending
        mark_result1 = pov_status.mark_mitigated(requests[0])
        mark_result2 = pov_status.mark_mitigated(requests[1])
        mark_result3 = pov_status.mark_non_mitigated(requests[2])
        mark_result4 = pov_status.mark_non_mitigated(requests[3])
        mark_result5 = pov_status.mark_expired(requests[4])
        assert mark_result1 is True
        assert mark_result2 is True
        assert mark_result3 is True
        assert mark_result4 is True
        assert mark_result5 is True
        # requests[5] remains pending

        # Verify final states
        result0 = pov_status.request_status(requests[0])
        result1 = pov_status.request_status(requests[1])
        result2 = pov_status.request_status(requests[2])
        result3 = pov_status.request_status(requests[3])
        result4 = pov_status.request_status(requests[4])
        result5 = pov_status.request_status(requests[5])

        assert isinstance(result0, POVReproduceResponse)
        assert result0.did_crash is False  # Mitigated
        assert isinstance(result1, POVReproduceResponse)
        assert result1.did_crash is False  # Mitigated
        assert isinstance(result2, POVReproduceResponse)
        assert result2.did_crash is True  # Non-mitigated
        assert isinstance(result3, POVReproduceResponse)
        assert result3.did_crash is True  # Non-mitigated
        assert result4 is None  # Expired item creates new pending
        assert result5 is None  # Still pending

        # Should have 2 pending items now (requests[4] and requests[5])
        pending1 = pov_status.get_one_pending()
        assert pending1.task_id in [requests[4].task_id, requests[5].task_id]


class TestPoVReproduceStatusCaching:
    """Test suite for PoVReproduceStatus caching functionality."""

    def _create_mock_redis(self):
        """Helper to create properly mocked Redis client with pipeline support."""
        mock_redis = MagicMock()
        mock_pipeline = MagicMock()
        mock_redis.pipeline.return_value = mock_pipeline
        mock_pipeline.__enter__.return_value = mock_pipeline
        mock_pipeline.__exit__.return_value = None
        return mock_redis, mock_pipeline

    def test_cache_hit_for_mitigated_status(self):
        """Test that repeated requests for mitigated status hit cache, not Redis."""
        # Create mock Redis client
        mock_redis, mock_pipeline = self._create_mock_redis()

        # Mock the final states check to return mitigated
        mock_pipeline.execute.return_value = [True, False]  # mitigated=True, non_mitigated=False

        pov_status = PoVReproduceStatus(mock_redis)

        # Create sample request
        request = POVReproduceRequest()
        request.task_id = "test-task"
        request.internal_patch_id = "0"
        request.pov_path = "/test/path"
        request.sanitizer = "asan"
        request.harness_name = "test_harness"

        # First call should hit Redis
        result1 = pov_status.request_status(request)
        assert isinstance(result1, POVReproduceResponse)
        assert result1.did_crash is False

        # Second call should hit cache, not Redis
        result2 = pov_status.request_status(request)
        assert isinstance(result2, POVReproduceResponse)
        assert result2.did_crash is False

        # Third call should also hit cache
        result3 = pov_status.request_status(request)
        assert isinstance(result3, POVReproduceResponse)
        assert result3.did_crash is False

        # Redis should only be called once (for the first request)
        assert mock_redis.pipeline.call_count == 1

    def test_cache_hit_for_non_mitigated_status(self):
        """Test that repeated requests for non-mitigated status hit cache, not Redis."""
        # Create mock Redis client
        mock_redis, mock_pipeline = self._create_mock_redis()

        # Mock the final states check to return non-mitigated
        mock_pipeline.execute.return_value = [False, True]  # mitigated=False, non_mitigated=True

        pov_status = PoVReproduceStatus(mock_redis)

        # Create sample request
        request = POVReproduceRequest()
        request.task_id = "test-task"
        request.internal_patch_id = "0"
        request.pov_path = "/test/path"
        request.sanitizer = "asan"
        request.harness_name = "test_harness"

        # First call should hit Redis
        result1 = pov_status.request_status(request)
        assert isinstance(result1, POVReproduceResponse)
        assert result1.did_crash is True

        # Second call should hit cache, not Redis
        result2 = pov_status.request_status(request)
        assert isinstance(result2, POVReproduceResponse)
        assert result2.did_crash is True

        # Redis should only be called once (for the first request)
        assert mock_redis.pipeline.call_count == 1

    def test_cache_miss_for_pending_status(self):
        """Test that pending status doesn't get cached and always hits Redis."""
        # Create mock Redis client
        mock_redis, mock_pipeline = self._create_mock_redis()
        mock_redis.sadd.return_value = 1  # Mock successful add to pending set

        # Mock responses:
        # First call: _did_crash returns [False, False], then full check returns [True, False, False]
        # Second call: _did_crash hits cache (no Redis call), then full check returns [True, False, False]
        mock_pipeline.execute.side_effect = [
            [False, False],  # First request: _did_crash: not in final states
            [
                True,
                False,
                False,
            ],  # First request: request_status full check: pending=True, mitigated=False, non_mitigated=False
            [True, False, False],  # Second request: request_status full check: still pending (cache hit for _did_crash)
        ]

        pov_status = PoVReproduceStatus(mock_redis)

        # Create sample request
        request = POVReproduceRequest()
        request.task_id = "test-task"
        request.internal_patch_id = "0"
        request.pov_path = "/test/path"
        request.sanitizer = "asan"
        request.harness_name = "test_harness"

        # First call should return None (pending)
        result1 = pov_status.request_status(request)
        assert result1 is None

        # Second call should also return None (pending) and hit Redis again for full check
        # but _did_crash should hit cache
        result2 = pov_status.request_status(request)
        assert result2 is None

        # Redis should be called 3 times total: 1 for first _did_crash + 2 for full checks
        # (second _did_crash hits cache)
        assert mock_redis.pipeline.call_count == 3

    def test_cache_works_with_different_requests(self):
        """Test that cache works correctly for different requests."""
        # Create mock Redis client
        mock_redis, mock_pipeline = self._create_mock_redis()

        # Mock different responses for different requests
        mock_pipeline.execute.side_effect = [
            [True, False],  # request1: mitigated
            [False, True],  # request2: non-mitigated
            # Subsequent calls should hit cache
        ]

        pov_status = PoVReproduceStatus(mock_redis)

        # Create two different requests
        request1 = POVReproduceRequest()
        request1.task_id = "test-task-1"
        request1.internal_patch_id = "0"
        request1.pov_path = "/test/path1"
        request1.sanitizer = "asan"
        request1.harness_name = "test_harness"

        request2 = POVReproduceRequest()
        request2.task_id = "test-task-2"
        request2.internal_patch_id = "0"
        request2.pov_path = "/test/path2"
        request2.sanitizer = "msan"
        request2.harness_name = "test_harness"

        # First calls should hit Redis
        result1 = pov_status.request_status(request1)
        assert isinstance(result1, POVReproduceResponse)
        assert result1.did_crash is False  # mitigated

        result2 = pov_status.request_status(request2)
        assert isinstance(result2, POVReproduceResponse)
        assert result2.did_crash is True  # non-mitigated

        # Repeat calls should hit cache
        result1_cached = pov_status.request_status(request1)
        assert isinstance(result1_cached, POVReproduceResponse)
        assert result1_cached.did_crash is False

        result2_cached = pov_status.request_status(request2)
        assert isinstance(result2_cached, POVReproduceResponse)
        assert result2_cached.did_crash is True

        # Redis should only be called twice (once for each unique request)
        assert mock_redis.pipeline.call_count == 2

    def test_cache_respects_maxsize(self):
        """Test that cache behavior is consistent (simplified test without maxsize override)."""
        # Create mock Redis client
        mock_redis, mock_pipeline = self._create_mock_redis()

        # Mock all responses as mitigated
        mock_pipeline.execute.return_value = [True, False]  # mitigated=True, non_mitigated=False

        pov_status = PoVReproduceStatus(mock_redis)

        # Create multiple different requests
        requests = []
        for i in range(3):
            request = POVReproduceRequest()
            request.task_id = f"test-task-{i}"
            request.internal_patch_id = "0"
            request.pov_path = f"/test/path{i}"
            request.sanitizer = "asan"
            request.harness_name = "test_harness"
            requests.append(request)

        # First requests should hit Redis
        result1 = pov_status.request_status(requests[0])
        result2 = pov_status.request_status(requests[1])
        result3 = pov_status.request_status(requests[2])
        assert isinstance(result1, POVReproduceResponse)
        assert isinstance(result2, POVReproduceResponse)
        assert isinstance(result3, POVReproduceResponse)
        assert mock_redis.pipeline.call_count == 3

        # Repeated requests should hit cache
        result1_cached = pov_status.request_status(requests[0])
        result2_cached = pov_status.request_status(requests[1])
        result3_cached = pov_status.request_status(requests[2])
        assert isinstance(result1_cached, POVReproduceResponse)
        assert isinstance(result2_cached, POVReproduceResponse)
        assert isinstance(result3_cached, POVReproduceResponse)
        # Should not have increased - all cache hits
        assert mock_redis.pipeline.call_count == 3

    def test_separate_instances_have_separate_caches(self):
        """Test that different PoVReproduceStatus instances have separate caches."""
        # Create two mock Redis clients
        mock_redis1 = MagicMock()
        mock_pipeline1 = MagicMock()
        mock_redis1.pipeline.return_value = mock_pipeline1
        mock_pipeline1.__enter__.return_value = mock_pipeline1
        mock_pipeline1.__exit__.return_value = None
        mock_pipeline1.execute.return_value = [True, False]  # mitigated

        mock_redis2 = MagicMock()
        mock_pipeline2 = MagicMock()
        mock_redis2.pipeline.return_value = mock_pipeline2
        mock_pipeline2.__enter__.return_value = mock_pipeline2
        mock_pipeline2.__exit__.return_value = None
        mock_pipeline2.execute.return_value = [False, True]  # non-mitigated

        # Create two instances
        pov_status1 = PoVReproduceStatus(mock_redis1)
        pov_status2 = PoVReproduceStatus(mock_redis2)

        # Create same request for both
        request = POVReproduceRequest()
        request.task_id = "test-task"
        request.internal_patch_id = "0"
        request.pov_path = "/test/path"
        request.sanitizer = "asan"
        request.harness_name = "test_harness"

        # First calls should hit respective Redis instances
        result1 = pov_status1.request_status(request)
        result2 = pov_status2.request_status(request)

        assert isinstance(result1, POVReproduceResponse)
        assert result1.did_crash is False  # mitigated
        assert isinstance(result2, POVReproduceResponse)
        assert result2.did_crash is True  # non-mitigated

        # Each instance should have hit its Redis once
        assert mock_redis1.pipeline.call_count == 1
        assert mock_redis2.pipeline.call_count == 1

        # Repeat calls should hit respective caches
        result1_cached = pov_status1.request_status(request)
        result2_cached = pov_status2.request_status(request)

        assert isinstance(result1_cached, POVReproduceResponse)
        assert result1_cached.did_crash is False
        assert isinstance(result2_cached, POVReproduceResponse)
        assert result2_cached.did_crash is True

        # Redis call counts should not increase (cache hits)
        assert mock_redis1.pipeline.call_count == 1
        assert mock_redis2.pipeline.call_count == 1

    def test_cache_integration_with_real_workflow(self, pov_status, sample_request):
        """Test that caching works correctly in a real workflow with Redis."""
        # This test uses real Redis and validates the cache behavior

        # Initial request should return None (pending)
        result1 = pov_status.request_status(sample_request)
        assert result1 is None

        # Mark as mitigated
        mark_result = pov_status.mark_mitigated(sample_request)
        assert mark_result is True

        # Now test caching: multiple requests should return same result
        # We can't easily test Redis call count with real Redis, but we can
        # verify that the behavior is consistent
        results = []
        for _ in range(5):
            result = pov_status.request_status(sample_request)
            results.append(result)

        # All results should be identical POVReproduceResponse objects
        for result in results:
            assert isinstance(result, POVReproduceResponse)
            assert result.did_crash is False  # mitigated
            assert result.request.task_id == sample_request.task_id
            assert result.request.internal_patch_id == sample_request.internal_patch_id
            assert result.request.pov_path == sample_request.pov_path
            assert result.request.sanitizer == sample_request.sanitizer
            assert result.request.harness_name == sample_request.harness_name

    def test_cache_clears_across_different_final_states(self):
        """Test that moving between final states works correctly with caching."""
        # Create mock Redis client
        mock_redis, mock_pipeline = self._create_mock_redis()

        pov_status = PoVReproduceStatus(mock_redis)

        # Create sample request
        request = POVReproduceRequest()
        request.task_id = "test-task"
        request.internal_patch_id = "0"
        request.pov_path = "/test/path"
        request.sanitizer = "asan"
        request.harness_name = "test_harness"

        # First: mock as mitigated
        mock_pipeline.execute.return_value = [True, False]
        result1 = pov_status.request_status(request)
        assert isinstance(result1, POVReproduceResponse)
        assert result1.did_crash is False

        # Second call should hit cache
        result2 = pov_status.request_status(request)
        assert isinstance(result2, POVReproduceResponse)
        assert result2.did_crash is False
        assert mock_redis.pipeline.call_count == 1  # Only first call hit Redis

        # Now simulate the state changing in Redis (e.g., due to another process)
        # This would require cache invalidation in a real system, but our current
        # implementation doesn't handle this case - the cache will return stale data
        # This test documents the current behavior
        mock_pipeline.execute.return_value = [False, True]  # Now non-mitigated

        # This call will still return cached (stale) mitigated result
        result3 = pov_status.request_status(request)
        assert isinstance(result3, POVReproduceResponse)
        assert result3.did_crash is False  # Still cached mitigated result
        assert mock_redis.pipeline.call_count == 1  # No new Redis calls
