import pytest
import time
from redis import Redis
from google.protobuf.struct_pb2 import Struct
from buttercup.common.queues import ReliableQueue, RQItem


@pytest.fixture
def redis_client():
    return Redis(host="localhost", port=6379, db=0)


@pytest.fixture
def reliable_queue(redis_client):
    # Create a new queue for testing
    queue = ReliableQueue(
        queue_name="test_queue",
        group_name="test_group",
        redis=redis_client,
        task_timeout=1000,
        msg_builder=Struct,
        reader_name="test_reader",
    )

    yield queue

    # Cleanup after tests
    redis_client.delete(queue.queue_name)


def test_reliable_queue_push_pop(reliable_queue):
    # Create a test message
    test_msg = Struct()
    test_msg.update({"test_key": "test_value"})

    # Test push
    reliable_queue.push(test_msg)
    assert reliable_queue.size() == 1

    # Test pop
    result = reliable_queue.pop()
    assert isinstance(result, RQItem)
    assert isinstance(result.deserialized, Struct)
    assert result.deserialized.fields["test_key"].string_value == "test_value"

    # Test acknowledgment
    reliable_queue.ack_item(result)


def test_reliable_queue_empty_pop(reliable_queue):
    # Test pop on empty queue
    result = reliable_queue.pop()
    assert result is None


def test_reliable_queue_multiple_messages(reliable_queue):
    # Create multiple test messages
    messages = []
    for i in range(3):
        msg = Struct()
        msg.update({"key": f"value_{i}"})
        messages.append(msg)
        reliable_queue.push(msg)

    assert reliable_queue.size() == 3

    # Pop and verify all messages
    for i in range(3):
        result = reliable_queue.pop()
        assert isinstance(result, RQItem)
        assert result.deserialized.fields["key"].string_value == f"value_{i}"
        reliable_queue.ack_item(result)


def test_pending_items(reliable_queue, redis_client):
    # Create a test message
    test_msg = Struct()
    test_msg.update({"test_key": "test_value"})
    reliable_queue.push(test_msg)
    assert reliable_queue.size() == 1

    # Get item
    item = reliable_queue.pop()
    assert item is not None
    assert item.deserialized.fields["test_key"].string_value == "test_value"

    # Close the old redis connection
    reliable_queue.redis.close()

    # recreate the queue with the same name, to simulate a crash
    queue = ReliableQueue(
        queue_name="test_queue",
        group_name="test_group",
        redis=redis_client,
        task_timeout=1000,
        msg_builder=Struct,
        reader_name="test_reader",
    )

    item = queue.pop()
    assert item is not None
    assert item.deserialized.fields["test_key"].string_value == "test_value"
    reliable_queue.ack_item(item)

    # recreate again to check if the item is still pending
    queue = ReliableQueue(
        queue_name="test_queue",
        group_name="test_group",
        redis=redis_client,
        task_timeout=1000,
        msg_builder=Struct,
        reader_name="test_reader",
    )
    item = queue.pop()
    assert item is None


def test_autoclaim(reliable_queue, redis_client):
    # Push a few messages
    test_msg = Struct()
    test_msg.update({"test_key": "test_value_0"})
    reliable_queue.push(test_msg)
    assert reliable_queue.size() == 1

    # Pop the message
    item = reliable_queue.pop()
    assert item is not None
    msg_id = item.item_id
    assert item.deserialized.fields["test_key"].string_value == "test_value_0"
    # No ack, so pending

    time.sleep(2)

    # Simulate another reader
    queue = ReliableQueue(
        queue_name="test_queue",
        group_name="test_group",
        redis=redis_client,
        task_timeout=1,
        msg_builder=Struct,
        reader_name="test_reader2",
    )
    item = queue.pop()
    assert item is not None
    assert item.item_id == msg_id
    assert item.deserialized.fields["test_key"].string_value == "test_value_0"

    # Ack the message
    queue.ack_item(item)

    # Pop the message
    item = queue.pop()
    assert item is None
