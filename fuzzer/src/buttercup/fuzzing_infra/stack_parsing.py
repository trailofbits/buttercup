from clusterfuzz.stacktraces import StackParser
import logging
from buttercup.common.sets import RedisSet
from redis import Redis
from bson.json_util import dumps, CANONICAL_JSON_OPTIONS

logger = logging.getLogger(__name__)

class CrashSet:
    def __init__(self, redis: Redis):
        self.redis = redis
        self.set_name = "crash_set"
        self.set = RedisSet(redis, self.set_name)

    # Returns True if the crash was already in the set
    def add(self, project:str, harness_name:str, stacktrace: str) -> bool:
        crash_data = get_crash_data(stacktrace)
        key = dumps([project, harness_name, crash_data], json_options=CANONICAL_JSON_OPTIONS)
        return self.redis.sadd(self.set_name, key)


def get_crash_data(stacktrace: str) -> str:
    parser = StackParser(symbolized=False, detect_ooms_and_hangs=True, detect_v8_runtime_errors=False)
    prs = parser.parse(stacktrace)
    logger.info(f"Crash data: {prs.crash_state}")
    return prs.crash_state