from typing import Generic, TypeVar, Type, Iterator
from buttercup.common.datastructures.msg_pb2 import WeightedHarness, BuildOutput
from redis import Redis
from bson.json_util import dumps, CANONICAL_JSON_OPTIONS
from google.protobuf.message import Message
from enum import Enum
from buttercup.common.sets import RedisSet

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
BUILD_SAN_MAP_NAME = "build_san_list"


class BUILD_TYPES(str, Enum):
    FUZZER = "fuzzer"
    COVERAGE = "coverage"
    TRACER_NO_DIFF = "tracer_no_diff"


# A build map makes it effecient to find for a given task_id + harness a build type
# we currently only support a single item of a given type
# add a new type if you want to support different builds
class BuildMap:
    def __init__(self, redis: Redis):
        self.redis = redis

    def san_set_key(self, task_id: str, build_type: str) -> str:
        return dumps([task_id, BUILD_MAP_NAME, build_type], json_options=CANONICAL_JSON_OPTIONS)

    def build_output_key(self, task_id: str, build_type: str, san: str) -> str:
        return dumps([task_id, BUILD_SAN_MAP_NAME, build_type, san], json_options=CANONICAL_JSON_OPTIONS)

    def add_build(self, build: BuildOutput) -> None:
        btype = build.build_type
        san_set = self.san_set_key(build.task_id, btype)
        pipe = self.redis.pipeline()
        pipe.sadd(san_set, build.sanitizer)
        serialized = build.SerializeToString()
        boutput_key = self.build_output_key(build.task_id, btype, build.sanitizer)
        pipe.set(boutput_key, serialized)
        pipe.execute()

    def get_builds(self, task_id: str, build_type: BUILD_TYPES) -> list[BuildOutput]:
        sanitizer_set = RedisSet(self.redis, self.san_set_key(task_id, build_type.value))
        builds = []
        for san in list(sanitizer_set):
            build = self.get_build_from_san(task_id, build_type, san)
            if build is not None:
                builds.append(build)
        return builds

    def get_build_from_san(self, task_id: str, build_type: BUILD_TYPES, san: str) -> BuildOutput | None:
        build_output_key = self.build_output_key(task_id, build_type.value, san)
        it = self.redis.get(build_output_key)
        if it is None:
            return None
        msg = BuildOutput()
        msg.ParseFromString(it)
        return msg


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
