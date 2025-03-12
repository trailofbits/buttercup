import pytest
import time
from redis import Redis
from google.protobuf.struct_pb2 import Struct
from buttercup.common.queues import (
    ReliableQueue,
    RQItem,
    QueueFactory,
    QueueNames,
    GroupNames,
    BUILD_TASK_TIMEOUT_MS,
    BUILD_OUTPUT_TASK_TIMEOUT_MS,
)
from buttercup.common.datastructures.msg_pb2 import BuildRequest, BuildOutput

GROUP_NAME = "test_group"
QUEUE_NAME = "test_queue"


@pytest.fixture
def redis_client():
    res = Redis(host="localhost", port=6379, db=15)
    yield res
    res.flushdb()


@pytest.fixture
def reliable_queue(redis_client):
    # Create a new queue for testing
    queue = ReliableQueue[Struct](
        queue_name=QUEUE_NAME,
        group_name=GROUP_NAME,
        redis=redis_client,
        task_timeout_ms=1000,
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
    reliable_queue.ack_item(result.item_id)


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
        reliable_queue.ack_item(result.item_id)


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
    queue = ReliableQueue[Struct](
        queue_name=QUEUE_NAME,
        group_name=GROUP_NAME,
        redis=redis_client,
        task_timeout_ms=1,
        msg_builder=Struct,
        reader_name="test_reader2",
    )
    item = queue.pop()
    assert item is not None
    assert item.item_id == msg_id
    assert item.deserialized.fields["test_key"].string_value == "test_value_0"

    # Ack the message
    queue.ack_item(item.item_id)

    # Pop the message
    item = queue.pop()
    assert item is None


def test_new_tasks_first(reliable_queue, redis_client):
    # Push a few messages
    for i in range(3):
        test_msg = Struct()
        test_msg.update({"key": f"value_{i}"})
        reliable_queue.push(test_msg)

    assert reliable_queue.size() == 3

    # Pop a message
    item = reliable_queue.pop()
    assert item is not None
    assert item.deserialized.fields["key"].string_value == "value_0"

    # No ack, so pending
    # Simulate a restart and a new reader
    queue = ReliableQueue[Struct](
        queue_name=QUEUE_NAME,
        group_name=GROUP_NAME,
        redis=redis_client,
        task_timeout_ms=1000,
        msg_builder=Struct,
        reader_name="test_reader2",
    )
    item = queue.pop()
    assert item is not None
    assert item.deserialized.fields["key"].string_value != "value_0"

    # Ack the message
    queue.ack_item(item.item_id)

    # Simulate another restart and a new reader
    queue = ReliableQueue[Struct](
        queue_name=QUEUE_NAME,
        group_name=GROUP_NAME,
        redis=redis_client,
        task_timeout_ms=1000,
        msg_builder=Struct,
        reader_name="test_reader3",
    )
    item = queue.pop()
    assert item is not None
    assert item.deserialized.fields["key"].string_value not in ["value_0", "value_1"]
    queue.ack_item(item.item_id)

    # Now pop again, we should get the value_0 message, autoclaimed
    time.sleep(2)
    item = queue.pop()
    assert item is not None
    assert item.deserialized.fields["key"].string_value == "value_0"
    queue.ack_item(item.item_id)


def test_queue_factory(redis_client):
    factory = QueueFactory(redis_client)

    queue = factory.create(QueueNames.BUILD_OUTPUT)
    assert isinstance(queue, ReliableQueue)
    assert queue.queue_name == QueueNames.BUILD_OUTPUT
    assert queue.group_name is None
    assert queue.redis == redis_client
    assert queue.task_timeout_ms == BUILD_OUTPUT_TASK_TIMEOUT_MS
    assert queue.msg_builder == BuildOutput

    queue = factory.create(QueueNames.BUILD_OUTPUT, GroupNames.ORCHESTRATOR)
    assert isinstance(queue, ReliableQueue)
    assert queue.queue_name == QueueNames.BUILD_OUTPUT
    assert queue.group_name == GroupNames.ORCHESTRATOR
    assert queue.redis == redis_client
    assert queue.task_timeout_ms == BUILD_OUTPUT_TASK_TIMEOUT_MS
    assert queue.msg_builder == BuildOutput

    queue = factory.create(QueueNames.BUILD, GroupNames.BUILDER_BOT)
    assert isinstance(queue, ReliableQueue)
    assert queue.queue_name == QueueNames.BUILD
    assert queue.group_name == GroupNames.BUILDER_BOT
    assert queue.redis == redis_client
    assert queue.task_timeout_ms == BUILD_TASK_TIMEOUT_MS
    assert queue.msg_builder == BuildRequest

    queue.push(
        BuildRequest(
            engine="test_engine",
            sanitizer="test_sanitizer",
            task_dir="test_task_dir",
            task_id="test_task_id",
        )
    )

    item = queue.pop()
    assert item is not None
    assert item.deserialized.engine == "test_engine"
    assert item.deserialized.sanitizer == "test_sanitizer"
    assert item.deserialized.task_dir == "test_task_dir"
    assert item.deserialized.task_id == "test_task_id"
    queue.ack_item(item.item_id)


def test_invalid_group_name():
    factory = QueueFactory(redis_client)
    with pytest.raises(ValueError):
        factory.create(QueueNames.BUILD_OUTPUT, "invalid_group")


def test_consumer_group_race(redis_client):
    outonly_queue = ReliableQueue[Struct](
        redis_client,
        "test_queue2",
        Struct,
    )

    msg1 = Struct()
    msg1.update({"key1": "value1"})
    outonly_queue.push(msg1)

    msg2 = Struct()
    msg2.update({"key2": "value2"})
    outonly_queue.push(msg2)

    reading_queue = ReliableQueue[Struct](
        redis_client,
        "test_queue2",
        Struct,
        group_name="test_group2",
    )

    item = reading_queue.pop()
    assert item is not None
    assert item.deserialized.fields["key1"].string_value == "value1"
    reading_queue.ack_item(item.item_id)

    item = reading_queue.pop()
    assert item is not None
    assert item.deserialized.fields["key2"].string_value == "value2"
    reading_queue.ack_item(item.item_id)


def test_group_create_race2(redis_client):
    outonly_queue = ReliableQueue[Struct](
        redis_client,
        "test_queue2",
        Struct,
    )

    msg1 = Struct()
    msg1.update({"key1": "value1"})
    outonly_queue.push(msg1)

    msg2 = Struct()
    msg2.update({"key2": "value2"})
    outonly_queue.push(msg2)

    reading_queue1 = ReliableQueue[Struct](
        redis_client,
        "test_queue2",
        Struct,
        group_name="test_group2",
    )

    item = reading_queue1.pop()
    assert item is not None
    assert item.deserialized.fields["key1"].string_value == "value1"
    reading_queue1.ack_item(item.item_id)

    reading_queue2 = ReliableQueue[Struct](
        redis_client,
        "test_queue2",
        Struct,
        group_name="test_group2",
    )

    item = reading_queue2.pop()
    assert item is not None
    assert item.deserialized.fields["key2"].string_value == "value2"
    reading_queue2.ack_item(item.item_id)

    item = reading_queue1.pop()
    assert item is None

    item = reading_queue2.pop()
    assert item is None


def test_times_delivered(reliable_queue, redis_client):
    # Push a test message
    test_msg = Struct()
    test_msg.update({"test_key": "test_value"})
    reliable_queue.push(test_msg)

    # First delivery
    item = reliable_queue.pop()
    assert item is not None
    msg_id = item.item_id

    # Should be delivered once
    times = reliable_queue.times_delivered(msg_id)
    assert times == 1

    # Wait for timeout and let another consumer claim it
    time.sleep(2)

    # Create second consumer
    queue2 = ReliableQueue[Struct](
        queue_name=QUEUE_NAME,
        group_name=GROUP_NAME,
        redis=redis_client,
        task_timeout_ms=1,
        msg_builder=Struct,
        reader_name="test_reader2",
    )

    # Second delivery
    item = queue2.pop()
    assert item is not None
    assert item.item_id == msg_id

    # Should be delivered twice
    times = queue2.times_delivered(msg_id)
    assert times == 2
