from typing import Generic, TypeVar, Type, Iterator
from buttercup.common.datastructures.msg_pb2 import WeightedHarness, BuildOutput, FunctionCoverage, BuildType
from redis import Redis
from bson.json_util import dumps, CANONICAL_JSON_OPTIONS
from google.protobuf.message import Message
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
COVERAGE_MAP_PREFIX = "coverage_map"


# A build map makes it effecient to find for a given task_id + harness a build type
# we currently only support a single item of a given type
# add a new type if you want to support different builds
class BuildMap:
    def __init__(self, redis: Redis):
        self.redis = redis

    def _san_set_key(self, task_id: str, build_type: BuildType) -> str:
        return dumps([task_id, BUILD_MAP_NAME, build_type], json_options=CANONICAL_JSON_OPTIONS)

    def _build_output_key(self, task_id: str, build_type: BuildType, san: str, internal_patch_id: str) -> str:
        return dumps(
            [task_id, BUILD_SAN_MAP_NAME, build_type, san, internal_patch_id], json_options=CANONICAL_JSON_OPTIONS
        )

    def add_build(self, build: BuildOutput) -> None:
        btype = build.build_type
        san_set = self._san_set_key(build.task_id, btype)
        pipe = self.redis.pipeline()
        pipe.sadd(san_set, build.sanitizer)
        serialized = build.SerializeToString()
        boutput_key = self._build_output_key(build.task_id, btype, build.sanitizer, build.internal_patch_id)
        pipe.set(boutput_key, serialized)
        pipe.execute()

    def get_builds(self, task_id: str, build_type: BuildType, internal_patch_id: str = "") -> list[BuildOutput]:
        if internal_patch_id != "":
            assert build_type == BuildType.PATCH, "internal_patch_id is only valid for PATCH builds"

        sanitizer_set = RedisSet(self.redis, self._san_set_key(task_id, build_type))
        builds = []
        for san in list(sanitizer_set):
            build = self.get_build_from_san(task_id, build_type, san, internal_patch_id)
            if build is not None:
                builds.append(build)
        return builds

    def get_build_from_san(
        self, task_id: str, build_type: BuildType, san: str, internal_patch_id: str = ""
    ) -> BuildOutput | None:
        if internal_patch_id != "":
            assert build_type == BuildType.PATCH, "internal_patch_id is only valid for PATCH builds"

        build_output_key = self._build_output_key(task_id, build_type, san, internal_patch_id)
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


class CoverageMap:
    def __init__(self, redis: Redis, harness_name: str, package_name: str, task_id: str):
        self.redis = redis
        self.harness_name = harness_name
        self.package_name = package_name
        self.task_id = task_id
        hash_name = [
            COVERAGE_MAP_PREFIX,
            harness_name,
            package_name,
            task_id,
        ]
        hash_name_str = dumps(hash_name, json_options=CANONICAL_JSON_OPTIONS)
        self.mp: RedisMap[FunctionCoverage] = RedisMap(redis, hash_name_str, FunctionCoverage)

    def set_function_coverage(self, function_coverage: FunctionCoverage) -> None:
        # function paths should be sorted and unique
        function_paths_list = list(function_coverage.function_paths)
        key = [
            function_coverage.function_name,
            function_paths_list,
        ]
        key_str = dumps(key, json_options=CANONICAL_JSON_OPTIONS)
        self.mp.set(key_str, function_coverage)

    def get_function_coverage(self, function_name: str, function_paths: list[str]) -> FunctionCoverage | None:
        # function paths should be sorted and unique
        key = [
            function_name,
            function_paths,
        ]
        key_str = dumps(key, json_options=CANONICAL_JSON_OPTIONS)
        return self.mp.get(key_str)

    def list_function_coverage(self) -> list[FunctionCoverage]:
        return list(iter(self.mp))
