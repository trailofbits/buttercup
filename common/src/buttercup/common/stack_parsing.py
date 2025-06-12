import re
from buttercup.common.clusterfuzz_parser import StackParser, CrashInfo
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
    def add(self, project: str, harness_name: str, task_id: str, sanitizer: str, stacktrace: str) -> bool:
        crash_data = get_crash_data(stacktrace)
        inst_key: str = get_inst_key(stacktrace)

        # NOTE: Storing "exact" crash data and allowing "similar" crashes to migrate to the tracer-bot/orchestrator for
        # deduplication.
        key = dumps(
            [project, harness_name, task_id, sanitizer, crash_data, inst_key], json_options=CANONICAL_JSON_OPTIONS
        )
        return self.set.add(key)


def parse_stacktrace(stacktrace: str, symbolized: bool = False) -> CrashInfo:
    # Strip ANSI escape codes from stacktrace as parse_stacktrace doesn't like them
    ansi_escape = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
    stacktrace = ansi_escape.sub("", stacktrace)
    parser = StackParser(symbolized=symbolized, detect_ooms_and_hangs=True, detect_v8_runtime_errors=False)
    prs = parser.parse(stacktrace)
    return prs


def get_crash_data(stacktrace: str, symbolized: bool = False) -> str:
    prs = parse_stacktrace(stacktrace, symbolized)
    logger.info(f"Crash data: {prs.crash_state}")
    return prs.crash_state


def get_inst_key(stacktrace: str) -> str:
    # vendored code from afc-finals/example-crs-architecture
    inst_pattern = re.compile(pattern=r"Instrumented\s(?P<fragment>[A-Za-z0-9\.]*)\s")
    matches = inst_pattern.findall(stacktrace)
    return "\n".join(sorted(matches)) if matches else ""


# Convenience function for getting crash tokens. For a given crash we expect only one of these two functions
# to return a trace, this makes sure we get something.
def get_crash_token(stacktrace: str) -> str:
    return get_crash_data(stacktrace) + get_inst_key(stacktrace)
