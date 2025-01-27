from typing import Generic, TypeVar, Type, Iterator
from buttercup.common.datastructures.fuzzer_msg_pb2 import WeightedTarget
from redis import Redis
from bson.json_util import dumps, CANONICAL_JSON_OPTIONS


MsgType = TypeVar("MsgType")
MSG_FIELD_NAME = b"msg"


class RedisMap(Generic[MsgType]):
    def __init__(self, redis: Redis, hash_name: str, msg_builder: Type[MsgType]):
        self.redis = redis
        self.msg_builder = msg_builder
        self.hash_name = hash_name

    def get(self, key: str) -> MsgType | None:
        it = self.redis.hget(self.hash_name, key)
        if it is None:
            return None

        msg = self.msg_builder()
        msg.ParseFromString(it)
        return msg

    def set(self, key: str, value: MsgType) -> None:
        self.redis.hset(self.hash_name, key, value.SerializeToString())

    def __iter__(self) -> Iterator[MsgType]:
        for key in self.redis.hkeys(self.hash_name):
            yield self.get(key)


FUZZER_MAP_NAME = "fuzzer_target_list"


class FuzzerMap:
    def __init__(self, redis: Redis):
        self.mp: RedisMap[WeightedTarget] = RedisMap(redis, FUZZER_MAP_NAME, WeightedTarget)

    def list_targets(self) -> list[WeightedTarget]:
        return list(iter(self.mp))

    def push_target(self, target: WeightedTarget) -> None:
        key = [
            target.target.package_name,
            target.target.engine,
            target.target.sanitizer,
            target.target.output_ossfuzz_path,
            target.target.source_path,
        ]
        key_str = dumps(key, json_options=CANONICAL_JSON_OPTIONS)
        self.mp.set(key_str, target)
