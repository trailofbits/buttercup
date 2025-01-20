from __future__ import annotations

from dataclasses import dataclass
from abc import ABC, abstractmethod
from redis import Redis, RedisError
from google.protobuf.message import Message
import logging
from typing import Type
import uuid

BUILD_QUEUE_NAME = "fuzzer_build_queue"
BUILDER_BOT_GROUP_NAME = "build_bot_consumers"
ORCHESTRATOR_GROUP_NAME = "orchestrator_group"
BUILD_OUTPUT_NAME = "fuzzer_build_output_queue"
TARGET_LIST_NAME = "fuzzer_target_list"

TASKS_QUEUE_NAME = "orchestrator_tasks_queue"
TASKS_GROUP_NAME = "orchestrator_tasks_group"
TASKS_REGISTRY_HASH_NAME = "orchestrator_tasks_registry"

logger = logging.getLogger(__name__)


class Queue(ABC):
    def __init__(self):
        pass

    @abstractmethod
    def pop(self): ...

    def push(self, _): ...

    @abstractmethod
    def __iter__(self): ...


class SerializationDeserializationQueue(Queue):
    def __init__(self, subq: Queue, msg_builder):
        super().__init__()
        self.subq = subq
        self.msg_builder = msg_builder

    def push(self, it: Message):
        if not it.IsInitialized():
            logger.error("Uninitialized field in protobuf object")

        bts = it.SerializeToString()
        self.subq.push(bts)

    def pop(self):
        maybe_bts = self.subq.pop()
        if maybe_bts is None:
            return None

        msg = self.msg_builder()
        msg.ParseFromString(maybe_bts)
        print("parsing message")
        return msg

    def __iter__(self):
        for it in iter(self.subq):
            msg = self.msg_builder()
            msg.ParseFromString(it)
            print(msg, type(msg))
            yield msg


class QueueIterMixin:
    def __init__(self, qname: str, redis: Redis):
        self.qname = qname
        self.redis = redis

    def __iter__(self):
        return iter(self.redis.lrange(self.qname, 0, -1))


class NormalQueue(QueueIterMixin, Queue):
    def __init__(self, qname: str, redis: Redis):
        super().__init__(qname, redis)
        self.qname = qname
        self.redis = redis

    def push(self, it):
        self.redis.lpush(self.qname, it)

    def pop(self):
        return self.redis.rpop(self.qname)

    def __iter__(self):
        return super().__iter__()


@dataclass
class RQItem:
    """
    A single item in a reliable queue.
    """

    item_id: str
    deserialized: Message
    consumer_name: str


@dataclass
class PendingItem:
    """
    A single item in a pending queue.
    """

    item_id: str
    consumer_name: str
    idle_time: int
    delivery_count: int


@dataclass
class ReliableQueue:
    """
    A queue that is reliable and can be used to process tasks in a distributed environment.
    """

    queue_name: str
    group_name: str
    redis: Redis
    task_timeout: int
    msg_builder: Type[Message]
    reader_name: str | None = None
    last_stream_id: str | None = "0-0"
    block_time: int = 200

    INAME = b"item"

    def __post_init__(self) -> None:
        if self.reader_name is None:
            self.reader_name = f"rqueue_{str(uuid.uuid4())}"

        # Create consumer group if it doesn't exist
        try:
            self.redis.xgroup_create(self.queue_name, self.group_name, mkstream=True)
        except RedisError:
            # Group may already exist
            pass

    def size(self) -> int:
        return self.redis.xlen(self.queue_name)

    def push(self, item: Message) -> None:
        bts = item.SerializeToString()
        self.redis.xadd(self.queue_name, {self.INAME: bts})

    def pop(self) -> RQItem | None:
        streams_items = self.redis.xreadgroup(
            self.group_name,
            self.reader_name,
            {self.queue_name: self.last_stream_id},
            block=self.block_time,
            count=1,
        )
        # Redis xreadgroup returns a list of [stream_name, [(message_id, {field: value})]]
        if streams_items is None or len(streams_items) == 0:
            # No message found in the pending/regular queue for this reader.
            # Try to autoclaim a message
            res = self.redis.xautoclaim(
                self.queue_name,
                self.group_name,
                self.reader_name,
                min_idle_time=self.task_timeout,
                count=1,
            )
            if res is None or len(res[1]) == 0:
                return None

            stream_item = res[1]
        else:
            stream_item = streams_items[0][1]

        if len(stream_item) == 0:
            # No message found in the pending queue for this reader
            # Go to the new messages
            self.last_stream_id = ">"
            return self.pop()

        # Extract message ID and data
        message_id = stream_item[0][0]
        message_data = stream_item[0][1]

        # Create and parse protobuf message
        msg = self.msg_builder()
        msg.ParseFromString(message_data[self.INAME])

        return RQItem(
            item_id=message_id, deserialized=msg, consumer_name=self.reader_name
        )

    def ack_item(self, rq_item: RQItem) -> None:
        self.redis.xack(self.queue_name, self.group_name, rq_item.item_id)

    def claim_item(self, item_id: str, min_idle_time: int = 0) -> None:
        self.redis.xclaim(
            self.queue_name, self.group_name, self.reader_name, min_idle_time, [item_id]
        )


@dataclass
class FuzzConfiguration:
    corpus_dir: str
    target_path: str
    engine: str
    sanitizer: str


@dataclass
class BuildConfiguration:
    project_id: str
    engine: str
    sanitizer: str
