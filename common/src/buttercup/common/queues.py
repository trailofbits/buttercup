from dataclasses import dataclass
from abc import ABC, abstractmethod
from redis import Redis
from google.protobuf.message import Message
import logging
import uuid
from redis.exceptions import ResponseError

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
    def pop(self):
        ...

    def push(self, _):
        ...

    @abstractmethod
    def __iter__(self):
        ...

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
        for it in  iter(self.subq):
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
        self.redis.lpush(self.qname,it)

    def pop(self):
        return self.redis.rpop(self.qname)
    
    def __iter__(self):
        return super().__iter__()
 

INAME = b"item"


class RQItem:
    def __init__(self, item_id, deserialized):
        self.item_id = item_id
        self.deserialized = deserialized

class ReliableQueue:
    def __init__(self, qname: str, gname:str, redis: Redis, task_timeout: int, msg_builder):
        super().__init__()
        self.qname = qname
        self.redis = redis
        self.gname = gname
        self.task_timeout = task_timeout
        # TODO(Ian): Idempotent afaik
        try:
            self.redis.xgroup_create(qname,gname,mkstream=True)
        except ResponseError:
            pass

        self.reader_name = f"rqueue_{str(uuid.uuid4())}"
        self.msg_builder = msg_builder

    def size(self):
        return self.redis.xlen(self.qname)

    def push(self, item):
        bts = item.SerializeToString()
        self.redis.xadd(self.qname, {INAME : bts})

    def pop(self):
        elem = self.redis.xreadgroup(self.gname, self.reader_name, {self.qname: ">"}, block=200, count=1)
        
        if len(elem) <= 0:
            # the first element is the stream id scanned, the second is the results, the third is stale elemes 
            elem = self.redis.xautoclaim(self.qname, self.gname, self.reader_name, self.task_timeout, count=1)[1]
        else:
            # this is gnarly. Basics here xreadgroup supports reading multiple streams at once so gives output
            #[[b'fuzzer_build_queue', [(b'1736893605878-0', {b'item': b'\n\x05nginx\x12\tlibfuzzer\x1a\x07address"\x18/home/iansmith/oss-fuzz/'})]]]
            # we want the first stream, second elem 
            elem = elem[0][1]
        if len(elem) <= 0:
            return None
        print(elem)
        print(elem[0][1])
        msg = self.msg_builder()
        # aand again we index here to get the first elem for the stream
        felem = elem[0]
        identifier, it_dict = felem
        msg.ParseFromString(it_dict[INAME])
        return RQItem(identifier, msg)
    
    def ack_item(self, rq_item: RQItem):
        self.redis.xack(self.qname, self.gname, rq_item.item_id)

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


