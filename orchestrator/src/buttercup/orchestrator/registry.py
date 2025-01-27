import time
from buttercup.common.datastructures.orchestrator_pb2 import Task
from redis import Redis
from buttercup.common.queues import HashNames
from dataclasses import dataclass, field
from google.protobuf import text_format


@dataclass
class TaskRegistry:
    """Keep track of all tasks in the system"""

    # How often to refresh the live tasks cache (in seconds)
    CACHE_REFRESH_INTERVAL = 60

    redis: Redis
    hash_name: str = HashNames.TASKS_REGISTRY

    # A cache for task ids that are currently live, this isn't necessarily
    # coherent across all instatiations of the TaskRegistry. The cache is
    # a best-effort cache and may not be up-to-date.
    # We track live task IDs since this is expected to be the most common scenario.
    # Requests for cancelled tasks may happen but should be infrequent.
    _live_task_ids: set[str] = field(default_factory=set)
    _last_cache_refresh: float = field(default_factory=time.time)

    def __len__(self):
        """Number of tasks in the registry"""
        return self.redis.hlen(self.hash_name)

    def __iter__(self):
        """Iterate over all tasks in the registry"""
        tasks_dict = self.redis.hgetall(self.hash_name)
        return (Task.FromString(task_bytes) for task_bytes in tasks_dict.values())

    def __contains__(self, task_id: str) -> bool:
        """Check if a task ID exists in the registry"""
        return self.redis.hexists(self.hash_name, self._prepare_key(task_id))

    def _prepare_key(self, task_id: str) -> str:
        return task_id.upper()

    def set(self, task: Task):
        """Update a task in the registry"""
        self.redis.hset(self.hash_name, self._prepare_key(task.task_id), task.SerializeToString())
        if not task.cancelled:
            self._live_task_ids.add(task.task_id)

    def get(self, task_id: str) -> Task | None:
        """Get a task from the registry"""
        task_bytes = self.redis.hget(self.hash_name, self._prepare_key(task_id))
        if task_bytes is None:
            return None

        task = Task.FromString(task_bytes)
        if not task.cancelled:
            self._live_task_ids.add(task_id)
        else:
            self._live_task_ids.discard(task_id)
        return task

    def delete(self, task_id: str):
        """Delete a task from the registry"""
        self.redis.hdel(self.hash_name, self._prepare_key(task_id))
        self._live_task_ids.discard(task_id)

    def mark_cancelled(self, task: Task):
        """Mark a task as cancelled in the registry"""
        task.cancelled = True
        self.set(task)

    def is_cancelled(self, task_id: str) -> bool:
        """Check if a task is cancelled

        Args:
            task_id: The task ID string

        Returns:
            True if the task is cancelled, False otherwise
        """
        task = self.get(task_id)
        return task.cancelled if task else True


def task_registry_cli():
    """CLI for the task registry"""
    from pydantic_settings import BaseSettings
    from typing import Annotated
    from pydantic import Field

    class TaskRegistrySettings(BaseSettings):
        redis_url: Annotated[str, Field(default="redis://localhost:6379", description="Redis URL")]

        class Config:
            env_prefix = "BUTTERCUP_TASK_REGISTRY_"
            env_file = ".env"
            cli_parse_args = True
            extra = "allow"

    settings = TaskRegistrySettings()
    redis = Redis.from_url(settings.redis_url, decode_responses=False)
    registry = TaskRegistry(redis)
    print("Number of tasks in registry:", len(registry))
    for task in registry:
        print()
        print("-" * 80)
        print("Task ID:", task.task_id)
        print(text_format.MessageToString(task, print_unknown_fields=True, indent=2))
        print("-" * 80)
