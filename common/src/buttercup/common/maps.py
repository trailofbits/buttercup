from typing import Generic, TypeVar, Type, Iterator
from buttercup.common.datastructures.msg_pb2 import WeightedHarness, BuildOutput
from redis import Redis
from bson.json_util import dumps, CANONICAL_JSON_OPTIONS
from google.protobuf.message import Message
from enum import Enum

MsgType = TypeVar("MsgType", bound=Message)
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


HARNESS_WEIGHTS_MAP_NAME = "harness_weights"
BUILD_MAP_NAME = "build_list"


class BUILD_TYPES(str, Enum):
    FUZZER = "fuzzer"
    COVERAGE = "coverage"


# A build map makes it effecient to find for a given task_id + harness a build type
# we currently only support a single item of a given type
# add a new type if you want to support different builds
class BuildMap:
    def __init__(self, redis: Redis):
        self.redis = redis

    def map_key_from_task_id(self, task_id: str) -> str:
        return dumps([task_id, BUILD_MAP_NAME], json_options=CANONICAL_JSON_OPTIONS)

    def build_map_key(self, build: BuildOutput) -> str:
        return self.map_key_from_task_id(build.task_id)

    def output_key_from_build_type(self, build_type: str) -> str:
        return dumps(
            [
                build_type,
            ],
            json_options=CANONICAL_JSON_OPTIONS,
        )

    def build_output_key(self, build: BuildOutput) -> str:
        return self.output_key_from_build_type(build.build_type)

    def add_build(self, build: BuildOutput) -> None:
        mp = RedisMap(self.redis, self.build_map_key(build), BuildOutput)
        mp.set(self.build_output_key(build), build)

    def get_build(self, task_id: str, build_type: BUILD_TYPES) -> BuildOutput | None:
        mp = RedisMap(self.redis, self.map_key_from_task_id(task_id), BuildOutput)
        return mp.get(self.output_key_from_build_type(build_type.value))


class HarnessWeights:
    def __init__(self, redis: Redis):
        self.mp: RedisMap[WeightedHarness] = RedisMap(redis, HARNESS_WEIGHTS_MAP_NAME, WeightedHarness)

    def list_harnesses(self) -> list[WeightedHarness]:
        return list(iter(self.mp))

    def push_harness(self, harness: WeightedHarness) -> None:
        key = [
            harness.package_name,
            harness.harness_name,
            harness.task_id,
        ]
        key_str = dumps(key, json_options=CANONICAL_JSON_OPTIONS)
        self.mp.set(key_str, harness)
