from typing import Iterator
from redis import Redis
from redis.exceptions import ResponseError
from bson.json_util import dumps, CANONICAL_JSON_OPTIONS
from contextlib import contextmanager
import random
import json
from functools import lru_cache

# Import POVReproduceRequest for the refactored PoVReproduceStatus
from buttercup.common.datastructures.msg_pb2 import POVReproduceRequest, POVReproduceResponse

MERGED_CORPUS_SET_NAME = "merged_corpus_set"
MERGED_CORPUS_SET_LOCK_NAME = "merged_corpus_set_lock"


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


POV_REPRODUCE_PENDING_SET_NAME = "pov_reproduce_pending"
POV_REPRODUCE_MITIGATED_SET_NAME = "pov_reproduce_mitigated"
POV_REPRODUCE_NON_MITIGATED_SET_NAME = "pov_reproduce_non_mitigated"
POV_REPRODUCE_EXPIRED_SET_NAME = "pov_reproduce_non_expired"


class PoVReproduceStatus:
    """Tracks the status of PoV (Proof of Vulnerability) reproduction attempts.

    This class manages sets in Redis to track whether PoVs have been reproduced against patched builds.
    For each PoV reproduction attempt, it tracks whether:
    - The attempt is pending
    - The PoV was mitigated (did not crash)
    - The PoV was not mitigated (still crashes)

    The status is tracked using a JSON-serialized key from POVReproduceRequest fields.

    """

    def __init__(self, redis: Redis):
        self.redis = redis

    @lru_cache(maxsize=1000)
    def _did_crash(self, key: str) -> bool | None:
        """Check if POV crashed (is in final states) and return crash status.

        Args:
            key: The serialized key for the POV reproduction request

        Returns:
            False if mitigated (didn't crash), True if non-mitigated (did crash), None if not in final states
        """
        pipeline = self.redis.pipeline()
        pipeline.sismember(POV_REPRODUCE_MITIGATED_SET_NAME, key)
        pipeline.sismember(POV_REPRODUCE_NON_MITIGATED_SET_NAME, key)
        result = pipeline.execute()

        if result[0]:
            return False  # Mitigated - didn't crash
        elif result[1]:
            return True  # Non-mitigated - did crash
        else:
            return None  # Not in final states

    def _make_key(self, request: POVReproduceRequest) -> str:
        """Create a unique key from a POVReproduceRequest by serializing it to string."""
        return dumps(
            [request.task_id, request.internal_patch_id, request.pov_path, request.sanitizer, request.harness_name],
            json_options=CANONICAL_JSON_OPTIONS,
        )

    def request_status(self, request: POVReproduceRequest) -> POVReproduceResponse | None:
        """Request the status of a POV reproduction attempt.

        Args:
            request: POVReproduceRequest containing task details

        Returns:
            None if pending, POVReproduceResponse if completed
        """
        key = self._make_key(request)

        # First check cache for final states only
        did_crash = self._did_crash(key)
        if did_crash is not None:
            return POVReproduceResponse(request=request, did_crash=did_crash)

        # If not in final states, do the regular logic including pending check
        pipeline = self.redis.pipeline()
        pipeline.sismember(POV_REPRODUCE_PENDING_SET_NAME, key)
        pipeline.sismember(POV_REPRODUCE_MITIGATED_SET_NAME, key)
        pipeline.sismember(POV_REPRODUCE_NON_MITIGATED_SET_NAME, key)
        result = pipeline.execute()

        if result[0]:
            return None  # Pending
        elif result[1]:
            return POVReproduceResponse(request=request, did_crash=False)  # Completed and mitigated
        elif result[2]:
            return POVReproduceResponse(request=request, did_crash=True)  # Completed and not mitigated
        else:  # First time, schedule it for testing
            self.redis.sadd(POV_REPRODUCE_PENDING_SET_NAME, key)
            return None

    def mark_mitigated(self, request: POVReproduceRequest) -> bool:
        """Mark a POV reproduction as mitigated (patch successfully prevented the crash).

        Args:
            request: POVReproduceRequest containing task details

        Returns:
            True if the item was moved from pending to mitigated, False if item wasn't pending.
        """
        key = self._make_key(request)
        moved_count = self.redis.smove(POV_REPRODUCE_PENDING_SET_NAME, POV_REPRODUCE_MITIGATED_SET_NAME, key)
        return moved_count > 0

    def mark_non_mitigated(self, request: POVReproduceRequest) -> bool:
        """Mark a POV reproduction as non-mitigated (patch did not prevent the crash).

        Args:
            request: POVReproduceRequest containing task details

        Returns:
            True if the item was moved from pending to non-mitigated, False if item wasn't pending.
        """
        key = self._make_key(request)
        moved_count = self.redis.smove(POV_REPRODUCE_PENDING_SET_NAME, POV_REPRODUCE_NON_MITIGATED_SET_NAME, key)
        return moved_count > 0

    def mark_expired(self, request: POVReproduceRequest) -> bool:
        """Mark a POV reproduction as expired (timed out or cancelled).

        Args:
            request: POVReproduceRequest containing task details

        Returns:
            True if the item was moved from pending to expired, False if item wasn't pending.
        """
        # NOTE: This function isn't strictly needed. We could just have keys expire after a certain time.
        # However, this allows us to track which items have expired.
        key = self._make_key(request)
        moved_count = self.redis.smove(POV_REPRODUCE_PENDING_SET_NAME, POV_REPRODUCE_EXPIRED_SET_NAME, key)
        return moved_count > 0

    def get_one_pending(self) -> POVReproduceRequest | None:
        """Get one pending POV reproduction request.

        Returns:
            POVReproduceRequest if one is available, None otherwise
        """
        pending_set = self.redis.smembers(POV_REPRODUCE_PENDING_SET_NAME)
        if len(pending_set) == 0:
            return None
        random_entry = random.choice(list(pending_set))

        # Parse the JSON key back to get the fields
        key_str = random_entry.decode("utf-8")
        fields = json.loads(key_str)

        # Reconstruct the POVReproduceRequest from the fields
        # The order matches _make_key: [task_id, internal_patch_id, pov_path, sanitizer, harness_name]
        request = POVReproduceRequest()
        request.task_id = fields[0]
        request.internal_patch_id = fields[1]
        request.pov_path = fields[2]
        request.sanitizer = fields[3]
        request.harness_name = fields[4]
        return request
