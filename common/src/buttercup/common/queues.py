from __future__ import annotations

from dataclasses import dataclass, field
from abc import ABC, abstractmethod
from redis import Redis, RedisError
from google.protobuf.message import Message
from buttercup.common.datastructures.msg_pb2 import (
    BuildRequest,
    BuildOutput,
    Crash,
    TaskDownload,
    TaskReady,
    TaskDelete,
    Patch,
    ConfirmedVulnerability,
)
import logging
from typing import Type, Generic, TypeVar, Literal, overload
import uuid
from enum import Enum
from typing import Any


class QueueNames(str, Enum):
    BUILD = "fuzzer_build_queue"
    BUILD_OUTPUT = "fuzzer_build_output_queue"
    CRASH = "fuzzer_crash_queue"
    UNIQUE_VULNERABILITIES = "unique_vulnerabilities_queue"
    CONFIRMED_VULNERABILITIES = "confirmed_vulnerabilities_queue"
    DOWNLOAD_TASKS = "orchestrator_download_tasks_queue"
    READY_TASKS = "tasks_ready_queue"
    DELETE_TASK = "orchestrator_delete_task_queue"
    PATCHES = "patches_queue"


class GroupNames(str, Enum):
    BUILDER_BOT = "build_bot_consumers"
    ORCHESTRATOR = "orchestrator_group"
    DOWNLOAD_TASKS = "orchestrator_download_tasks_group"
    SCHEDULER_READY_TASKS = "scheduler_ready_tasks_group"
    SCHEDULER_DELETE_TASK = "scheduler_delete_task_group"
    SCHEDULER_BUILD_OUTPUT = "scheduler_build_output_group"
    UNIQUE_VULNERABILITIES = "unique_vulnerabilities_group"
    CONFIRMED_VULNERABILITIES = "confirmed_vulnerabilities_group"


class HashNames(str, Enum):
    TASKS_REGISTRY = "tasks_registry"


BUILD_TASK_TIMEOUT_MS = 15 * 60 * 1000
BUILD_OUTPUT_TASK_TIMEOUT_MS = 3 * 60 * 1000
DOWNLOAD_TASK_TIMEOUT_MS = 10 * 60 * 1000
READY_TASK_TIMEOUT_MS = 3 * 60 * 1000
DELETE_TASK_TIMEOUT_MS = 5 * 60 * 1000
CRASH_TASK_TIMEOUT_MS = 10 * 60 * 1000
PATCH_TASK_TIMEOUT_MS = 10 * 60 * 1000
UNIQUE_VULNERABILITIES_TASK_TIMEOUT_MS = 10 * 60 * 1000
CONFIRMED_VULNERABILITIES_TASK_TIMEOUT_MS = 10 * 60 * 1000

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


@dataclass
class ReliableQueue(Generic[MsgType]):
    """
    A queue that is reliable and can be used to process tasks in a distributed environment.
    """

    redis: Redis
    queue_name: str
    msg_builder: Type[MsgType]
    group_name: str | None = None
    task_timeout_ms: int = 180000
    reader_name: str | None = None
    last_stream_id: str | None = ">"
    block_time: int | None = 200

    INAME = b"item"

    def __post_init__(self) -> None:
        if self.reader_name is None:
            self.reader_name = f"rqueue_{str(uuid.uuid4())}"

        if self.group_name is not None:
            # Create consumer group if it doesn't exist
            try:
                self.redis.xgroup_create(self.queue_name, self.group_name, mkstream=True, id="0")
            except RedisError:
                # Group may already exist
                pass

    def size(self) -> int:
        return self.redis.xlen(self.queue_name)

    def push(self, item: MsgType) -> None:
        bts = item.SerializeToString()
        self.redis.xadd(self.queue_name, {self.INAME: bts})

    def _ensure_group_name(func):
        def wrapper(self, *args, **kwargs):
            if self.group_name is None:
                raise ValueError("group_name must be set for this operation")
            return func(self, *args, **kwargs)

        return wrapper

    @_ensure_group_name
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

        return RQItem[MsgType](item_id=message_id, deserialized=msg)

    @_ensure_group_name
    def ack_item(self, item_id: str) -> None:
        self.redis.xack(self.queue_name, self.group_name, item_id)

    @_ensure_group_name
    def claim_item(self, item_id: str, min_idle_time: int = 0) -> None:
        self.redis.xclaim(self.queue_name, self.group_name, self.reader_name, min_idle_time, [item_id])


@dataclass
class QueueConfig:
    queue_name: QueueNames
    msg_builder: Type[MsgType]
    task_timeout_ms: int
    group_names: list[GroupNames] = field(default_factory=list)


@dataclass
class QueueFactory:
    """Factory for creating common reliable queues"""

    redis: Redis
    _config: dict[QueueNames, QueueConfig] = field(
        default_factory=lambda: {
            QueueNames.BUILD: QueueConfig(
                QueueNames.BUILD,
                BuildRequest,
                BUILD_TASK_TIMEOUT_MS,
                [GroupNames.BUILDER_BOT],
            ),
            QueueNames.BUILD_OUTPUT: QueueConfig(
                QueueNames.BUILD_OUTPUT,
                BuildOutput,
                BUILD_OUTPUT_TASK_TIMEOUT_MS,
                [GroupNames.ORCHESTRATOR, GroupNames.SCHEDULER_BUILD_OUTPUT],
            ),
            QueueNames.DOWNLOAD_TASKS: QueueConfig(
                QueueNames.DOWNLOAD_TASKS,
                TaskDownload,
                DOWNLOAD_TASK_TIMEOUT_MS,
                [GroupNames.DOWNLOAD_TASKS],
            ),
            QueueNames.READY_TASKS: QueueConfig(
                QueueNames.READY_TASKS,
                TaskReady,
                READY_TASK_TIMEOUT_MS,
                [GroupNames.SCHEDULER_READY_TASKS],
            ),
            QueueNames.CRASH: QueueConfig(
                QueueNames.CRASH,
                Crash,
                CRASH_TASK_TIMEOUT_MS,
                [GroupNames.ORCHESTRATOR],
            ),
            QueueNames.UNIQUE_VULNERABILITIES: QueueConfig(
                QueueNames.UNIQUE_VULNERABILITIES,
                Crash,
                UNIQUE_VULNERABILITIES_TASK_TIMEOUT_MS,
                [GroupNames.UNIQUE_VULNERABILITIES],
            ),
            QueueNames.CONFIRMED_VULNERABILITIES: QueueConfig(
                QueueNames.CONFIRMED_VULNERABILITIES,
                ConfirmedVulnerability,
                CONFIRMED_VULNERABILITIES_TASK_TIMEOUT_MS,
                [GroupNames.CONFIRMED_VULNERABILITIES],
            ),
            QueueNames.DELETE_TASK: QueueConfig(
                QueueNames.DELETE_TASK,
                TaskDelete,
                DELETE_TASK_TIMEOUT_MS,
                [GroupNames.SCHEDULER_DELETE_TASK],
            ),
            QueueNames.PATCHES: QueueConfig(
                QueueNames.PATCHES,
                Patch,
                PATCH_TASK_TIMEOUT_MS,
                [],
            ),
        }
    )

    @overload
    def create(
        self, queue_name: Literal[QueueNames.BUILD], group_name: GroupNames, **kwargs: Any
    ) -> ReliableQueue[BuildRequest]: ...

    @overload
    def create(
        self, queue_name: Literal[QueueNames.BUILD_OUTPUT], group_name: GroupNames, **kwargs: Any
    ) -> ReliableQueue[BuildOutput]: ...

    @overload
    def create(
        self, queue_name: Literal[QueueNames.DOWNLOAD_TASKS], group_name: GroupNames, **kwargs: Any
    ) -> ReliableQueue[TaskDownload]: ...

    @overload
    def create(
        self, queue_name: Literal[QueueNames.READY_TASKS], group_name: GroupNames, **kwargs: Any
    ) -> ReliableQueue[TaskReady]: ...

    @overload
    def create(
        self, queue_name: Literal[QueueNames.CRASH], group_name: GroupNames, **kwargs: Any
    ) -> ReliableQueue[Crash]: ...

    @overload
    def create(
        self, queue_name: Literal[QueueNames.UNIQUE_VULNERABILITIES], group_name: GroupNames, **kwargs: Any
    ) -> ReliableQueue[Crash]: ...

    @overload
    def create(
        self, queue_name: Literal[QueueNames.CONFIRMED_VULNERABILITIES], group_name: GroupNames, **kwargs: Any
    ) -> ReliableQueue[ConfirmedVulnerability]: ...

    @overload
    def create(
        self, queue_name: Literal[QueueNames.DELETE_TASK], group_name: GroupNames, **kwargs: Any
    ) -> ReliableQueue[TaskDelete]: ...

    @overload
    def create(
        self, queue_name: Literal[QueueNames.PATCHES], group_name: GroupNames, **kwargs: Any
    ) -> ReliableQueue[Patch]: ...

    def create(
        self, queue_name: QueueNames, group_name: GroupNames | None = None, **kwargs: Any
    ) -> ReliableQueue[MsgType]:
        if queue_name not in self._config:
            raise ValueError(f"Invalid queue name: {queue_name}")

        config = self._config[queue_name]
        queue_args = {
            "redis": self.redis,
            "queue_name": config.queue_name,
            "msg_builder": config.msg_builder,
            "task_timeout_ms": config.task_timeout_ms,
        }
        if group_name is not None:
            if group_name not in config.group_names:
                raise ValueError(f"Invalid group name: {group_name}")

            queue_args["group_name"] = group_name

        queue_args.update(kwargs)
        return ReliableQueue(**queue_args)


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
    source_path: str | None
