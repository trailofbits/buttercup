import pytest
import json
from redis import Redis
from buttercup.common.sarif_store import SARIFStore, SARIFBroadcastDetail


@pytest.fixture
def redis_client():
    return Redis(host="localhost", port=6379, db=9)


@pytest.fixture
def sarif_store(redis_client):
    # Create a SARIFStore instance for testing
    store = SARIFStore(redis_client)

    # Clean any existing test data
    for key in redis_client.keys(f"{store.key_prefix}*"):
        redis_client.delete(key)

    yield store

    # Clean up after tests
    for key in redis_client.keys(f"{store.key_prefix}*"):
        redis_client.delete(key)


@pytest.fixture
def sample_sarif_detail():
    """Create a sample SARIFBroadcastDetail for testing"""
    return SARIFBroadcastDetail(
        metadata={"source": "test", "version": "1.0"},
        sarif={"version": "2.1.0", "runs": []},
        sarif_id="test-sarif-id",
        task_id="test-task-id",
    )


def test_sarif_store_store_and_get_by_task_id(sarif_store, sample_sarif_detail):
    """Test storing a SARIF detail and retrieving it by task ID"""
    # Store the SARIF detail
    sarif_store.store(sample_sarif_detail)

    # Retrieve it by task ID
    retrieved_sarifs = sarif_store.get_by_task_id(sample_sarif_detail.task_id)

    # Verify we got exactly one SARIF detail
    assert len(retrieved_sarifs) == 1

    # Verify the retrieved SARIF detail matches the original
    retrieved = retrieved_sarifs[0]
    assert retrieved.sarif_id == sample_sarif_detail.sarif_id
    assert retrieved.task_id == sample_sarif_detail.task_id
    assert retrieved.metadata == sample_sarif_detail.metadata
    assert retrieved.sarif == sample_sarif_detail.sarif


def test_sarif_store_get_all(sarif_store, sample_sarif_detail):
    """Test retrieving all SARIF details"""
    # Create a second SARIF detail with a different task ID
    second_sarif = SARIFBroadcastDetail(
        metadata={"source": "test2", "version": "1.0"},
        sarif={"version": "2.1.0", "runs": []},
        sarif_id="test-sarif-id-2",
        task_id="test-task-id-2",
    )

    # Store both SARIF details
    sarif_store.store(sample_sarif_detail)
    sarif_store.store(second_sarif)

    # Retrieve all SARIF details
    all_sarifs = sarif_store.get_all()

    # Verify we got both SARIF details
    assert len(all_sarifs) == 2

    # Verify the task IDs of the retrieved SARIF details
    task_ids = {sarif.task_id for sarif in all_sarifs}
    assert sample_sarif_detail.task_id in task_ids
    assert second_sarif.task_id in task_ids


def test_sarif_store_multiple_sarifs_per_task(sarif_store, sample_sarif_detail):
    """Test storing multiple SARIF details for the same task"""
    # Create a second SARIF detail with the same task ID but different SARIF ID
    second_sarif = SARIFBroadcastDetail(
        metadata={"source": "test2", "version": "1.0"},
        sarif={"version": "2.1.0", "runs": []},
        sarif_id="test-sarif-id-2",
        task_id=sample_sarif_detail.task_id,  # Same task ID
    )

    # Store both SARIF details
    sarif_store.store(sample_sarif_detail)
    sarif_store.store(second_sarif)

    # Retrieve SARIF details for the task
    retrieved_sarifs = sarif_store.get_by_task_id(sample_sarif_detail.task_id)

    # Verify we got both SARIF details
    assert len(retrieved_sarifs) == 2

    # Verify the SARIF IDs of the retrieved SARIF details
    sarif_ids = {sarif.sarif_id for sarif in retrieved_sarifs}
    assert sample_sarif_detail.sarif_id in sarif_ids
    assert second_sarif.sarif_id in sarif_ids


def test_sarif_store_delete_by_task_id(sarif_store, sample_sarif_detail):
    """Test deleting SARIF details by task ID"""
    # Create a second SARIF detail with a different task ID
    second_sarif = SARIFBroadcastDetail(
        metadata={"source": "test2", "version": "1.0"},
        sarif={"version": "2.1.0", "runs": []},
        sarif_id="test-sarif-id-2",
        task_id="test-task-id-2",
    )

    # Store both SARIF details
    sarif_store.store(sample_sarif_detail)
    sarif_store.store(second_sarif)

    # Delete SARIF details for the first task
    deleted = sarif_store.delete_by_task_id(sample_sarif_detail.task_id)

    # Verify deletion was successful
    assert deleted == 1

    # Retrieve all SARIF details
    all_sarifs = sarif_store.get_all()

    # Verify we only have the second SARIF detail
    assert len(all_sarifs) == 1
    assert all_sarifs[0].task_id == second_sarif.task_id


def test_sarif_store_nonexistent_task_id(sarif_store):
    """Test retrieving and deleting SARIF details for a nonexistent task ID"""
    # Attempt to retrieve SARIF details for a nonexistent task ID
    retrieved_sarifs = sarif_store.get_by_task_id("nonexistent-task-id")

    # Verify we got an empty list
    assert retrieved_sarifs == []

    # Attempt to delete SARIF details for a nonexistent task ID
    deleted = sarif_store.delete_by_task_id("nonexistent-task-id")

    # Verify no keys were deleted
    assert deleted == 0


def test_sarif_store_case_insensitive_task_id(sarif_store, sample_sarif_detail):
    """Test that task IDs are case-insensitive"""
    # Store a SARIF detail with a lowercase task ID
    lowercase_task_id = sample_sarif_detail.task_id.lower()
    sample_sarif_detail.task_id = lowercase_task_id
    sarif_store.store(sample_sarif_detail)

    # Retrieve the SARIF detail using an uppercase task ID
    uppercase_task_id = lowercase_task_id.upper()
    retrieved_sarifs = sarif_store.get_by_task_id(uppercase_task_id)

    # Verify we got the SARIF detail
    assert len(retrieved_sarifs) == 1
    assert retrieved_sarifs[0].sarif_id == sample_sarif_detail.sarif_id


def test_sarif_store_json_serialization(sarif_store, sample_sarif_detail):
    """Test that SARIF details are properly serialized and deserialized"""
    # Store a SARIF detail
    sarif_store.store(sample_sarif_detail)

    # Retrieve the raw JSON from Redis
    key = sarif_store._get_key(sample_sarif_detail.task_id)
    raw_json = sarif_store.redis.lrange(key, 0, -1)[0]

    # Parse the JSON
    parsed_json = json.loads(raw_json)

    # Verify the parsed JSON matches the original SARIF detail
    assert parsed_json["sarif_id"] == sample_sarif_detail.sarif_id
    assert parsed_json["task_id"] == sample_sarif_detail.task_id
    assert parsed_json["metadata"] == sample_sarif_detail.metadata
    assert parsed_json["sarif"] == sample_sarif_detail.sarif
