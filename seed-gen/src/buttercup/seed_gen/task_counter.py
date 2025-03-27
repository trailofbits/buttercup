from bson.json_util import CANONICAL_JSON_OPTIONS, dumps
from redis import Redis

from buttercup.seed_gen.task import TaskName

TASK_COUNTER_NAME = "seed_gen_task_counter"


class TaskCounter:
    """A Redis-based counter for seed-gen task runs"""

    def __init__(self, redis: Redis):
        self.redis = redis

    def _get_counter_key(
        self, harness_name: str, package_name: str, task_id: str, task_name: str
    ) -> str:
        """Generate a unique Redis key for the counter."""
        key = [
            TASK_COUNTER_NAME,
            harness_name,
            package_name,
            task_id,
            task_name,
        ]
        return dumps(key, json_options=CANONICAL_JSON_OPTIONS)

    def increment(self, harness_name: str, package_name: str, task_id: str, task_name: str) -> int:
        """Atomically increment the counter for a specific task run.

        Args:
            harness_name: Name of the harness
            package_name: Name of the package
            task_id: ID of the task
            task_name: Name of the task (from TaskName enum)

        Returns:
            The new count after incrementing
        """
        key = self._get_counter_key(harness_name, package_name, task_id, task_name)
        return self.redis.incr(key)

    def get_count(self, harness_name: str, package_name: str, task_id: str, task_name: str) -> int:
        """Get the current count for a specific task run.

        Args:
            harness_name: Name of the harness
            package_name: Name of the package
            task_id: ID of the task
            task_name: Name of the task (from TaskName enum)

        Returns:
            The current count, or 0 if no count exists
        """
        key = self._get_counter_key(harness_name, package_name, task_id, task_name)
        count = self.redis.get(key)
        return int(count) if count is not None else 0

    def get_all_counts(self, harness_name: str, package_name: str, task_id: str) -> dict[str, int]:
        """Get counts for all task types for a specific harness/package/task combination.

        Args:
            harness_name: Name of the harness
            package_name: Name of the package
            task_id: ID of the task

        Returns:
            Dictionary mapping task names to their counts
        """
        counts = {}
        for task_name in TaskName:
            counts[task_name.value] = self.get_count(
                harness_name, package_name, task_id, task_name.value
            )
        return counts
