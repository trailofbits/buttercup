from typing import Iterator
from redis import Redis
from redis.exceptions import ResponseError
from bson.json_util import dumps, CANONICAL_JSON_OPTIONS
from contextlib import contextmanager
import logging

MERGED_CORPUS_SET_NAME = "merged_corpus_set"
MERGED_CORPUS_SET_LOCK_NAME = "merged_corpus_set_lock"
logger = logging.getLogger(__name__)


class RedisSet:
    def __init__(self, redis: Redis, set_name: str):
        self.redis = redis
        self.set_name = set_name

    # Returns True if the value was already in the set
    def add(self, value: str) -> bool:
        return self.redis.sadd(self.set_name, value) == 0

    # Returns True if the value was already in the set
    def remove(self, value: str) -> bool:
        return self.redis.srem(self.set_name, value) == 1

    def contains(self, value: str) -> bool:
        return self.redis.sismember(self.set_name, value)

    def __iter__(self) -> Iterator[str]:
        logger.info(f"Iterating over {self.set_name}")
        try:
            for member in self.redis.smembers(self.set_name):
                yield member.decode("utf-8")
        except ResponseError as _:
            return

    def __len__(self) -> int:
        return self.redis.scard(self.set_name)


# A set that tracks all merged hashes.
# This set acts as a filter on the local corpus.
class MergedCorpusSet(RedisSet):
    def __init__(self, redis: Redis, task_id: str, harness_name: str):
        self.redis = redis
        self.set_name = dumps([task_id, MERGED_CORPUS_SET_NAME, harness_name], json_options=CANONICAL_JSON_OPTIONS)
        super().__init__(redis, self.set_name)


class FailedToAcquireLock(Exception):
    pass


class RedisLock:
    def __init__(self, redis: Redis, key: str, lock_timeout_seconds: int = 10):
        self.redis = redis
        self.key = key
        self.lock_timeout_seconds = lock_timeout_seconds

    @contextmanager
    def acquire(self):
        if not self.redis.set(self.key, "1", ex=self.lock_timeout_seconds, nx=True):
            raise FailedToAcquireLock()
        try:
            yield
        finally:
            self._release()

    def _release(self):
        self.redis.delete(self.key)


# We give it roughly a fuzzing cycle to finish up 15 mins
MERGING_LOCK_TIMEOUT_SECONDS = 15 * 60


class MergedCorpusSetLock(RedisLock):
    def __init__(self, redis: Redis, task_id: str, harness_name: str, lock_timeout_seconds: int = 10):
        self.redis = redis
        self.set_name = dumps([task_id, MERGED_CORPUS_SET_LOCK_NAME, harness_name], json_options=CANONICAL_JSON_OPTIONS)
        super().__init__(redis, self.set_name, lock_timeout_seconds)
