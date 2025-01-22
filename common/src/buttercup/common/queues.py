from __future__ import annotations

from dataclasses import dataclass
from abc import ABC, abstractmethod
from redis import Redis, RedisError
from google.protobuf.message import Message
from buttercup.common.datastructures.fuzzer_msg_pb2 import BuildRequest, BuildOutput
from buttercup.common.datastructures.orchestrator_pb2 import TaskDownload
import logging
from typing import Type, Generic, TypeVar
import uuid
from enum import Enum
from typing import Any

class QueueNames(str, Enum):
    BUILD = "fuzzer_build_queue"
    BUILD_OUTPUT = "fuzzer_build_output_queue"
    TARGET_LIST = "fuzzer_target_list"
    DOWNLOAD_TASKS = "orchestrator_download_tasks_queue"


class GroupNames(str, Enum):
    BUILDER_BOT = "build_bot_consumers"
    ORCHESTRATOR = "orchestrator_group"
    DOWNLOAD_TASKS = "orchestrator_download_tasks_group"


class HashNames(str, Enum):
    TASKS_REGISTRY = "tasks_registry"

BUILD_TASK_TIMEOUT_MS = 15 * 60 * 1000
BUILD_OUTPUT_TASK_TIMEOUT_MS = 3 * 60 * 1000
DOWNLOAD_TASK_TIMEOUT_MS = 10 * 60 * 1000

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


# Type variable for protobuf Message subclasses
# Used for type-hinting of reliable queue items
MsgType = TypeVar("MsgType", bound=Message)


@dataclass
class RQItem(Generic[MsgType]):
    """
    A single item in a reliable queue.
    """

    item_id: str
    deserialized: MsgType
    consumer_name: str


@dataclass
class ReliableQueue(Generic[MsgType]):
    """
    A queue that is reliable and can be used to process tasks in a distributed environment.
    """

    queue_name: str
    group_name: str
    redis: Redis
    msg_builder: Type[MsgType]
    task_timeout_ms: int = 180000
    reader_name: str | None = None
    last_stream_id: str | None = ">"
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

    def push(self, item: MsgType) -> None:
        bts = item.SerializeToString()
        self.redis.xadd(self.queue_name, {self.INAME: bts})

    def pop(self) -> RQItem[MsgType] | None:
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
                min_idle_time=self.task_timeout_ms,
                count=1,
            )
            if res is None or len(res[1]) == 0:
                return None

            stream_item = res[1]
        else:
            stream_item = streams_items[0][1]

        if len(stream_item) == 0 and self.last_stream_id != ">":
            # If the queue was created with a last_stream_id that is not `>`, it
            # means the pending items for this reader were desired. In case
            # that's the case and no items were found in the pending queue, look
            # at new messages
            self.last_stream_id = ">"
            return self.pop()

        # Extract message ID and data
        message_id = stream_item[0][0]
        message_data = stream_item[0][1]

        # Create and parse protobuf message
        msg = self.msg_builder()
        msg.ParseFromString(message_data[self.INAME])

        return RQItem[MsgType](
            item_id=message_id, deserialized=msg, consumer_name=self.reader_name
        )

    def ack_item(self, item_id: str) -> None:
        self.redis.xack(self.queue_name, self.group_name, item_id)

    def claim_item(self, item_id: str, min_idle_time: int = 0) -> None:
        self.redis.xclaim(
            self.queue_name, self.group_name, self.reader_name, min_idle_time, [item_id]
        )


@dataclass
class QueueFactory:
    """Factory for creating common reliable queues"""

    redis: Redis

    def create_build_queue(self, **kwargs: Any) -> ReliableQueue[BuildRequest]:
        return ReliableQueue(
            queue_name=QueueNames.BUILD,
            group_name=GroupNames.BUILDER_BOT,
            redis=self.redis,
            msg_builder=BuildRequest,
            task_timeout_ms=BUILD_TASK_TIMEOUT_MS,
            **kwargs,
        )

    def create_build_output_queue(self, **kwargs: Any) -> ReliableQueue[BuildOutput]:
        return ReliableQueue(
            queue_name=QueueNames.BUILD_OUTPUT,
            group_name=GroupNames.ORCHESTRATOR,
            redis=self.redis,
            msg_builder=BuildOutput,
            task_timeout_ms=BUILD_OUTPUT_TASK_TIMEOUT_MS,
            **kwargs,
        )
    
    def create_download_tasks_queue(self, **kwargs: Any) -> ReliableQueue[TaskDownload]:
        return ReliableQueue(
            queue_name=QueueNames.DOWNLOAD_TASKS,
            group_name=GroupNames.DOWNLOAD_TASKS,
            redis=self.redis,
            msg_builder=TaskDownload,
            task_timeout_ms=DOWNLOAD_TASK_TIMEOUT_MS,
            **kwargs,
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
