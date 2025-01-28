from buttercup.common.datastructures.orchestrator_pb2 import Task
from redis import Redis
from buttercup.common.queues import HashNames
from dataclasses import dataclass
from google.protobuf import text_format


@dataclass
class TaskRegistry:
    """Keep track of all tasks in the system"""

    redis: Redis
    hash_name: str = HashNames.TASKS_REGISTRY

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

    def get(self, task_id: str) -> Task | None:
        """Get a task from the registry"""
        task_bytes = self.redis.hget(self.hash_name, self._prepare_key(task_id))
        if task_bytes is None:
            return None
        return Task.FromString(task_bytes)

    def delete(self, task_id: str):
        """Delete a task from the registry"""
        self.redis.hdel(self.hash_name, self._prepare_key(task_id))

    def mark_cancelled(self, task: Task):
        """Mark a task as cancelled in the registry"""
        task.cancelled = True
        self.set(task)

    def is_cancelled(self, task_or_id: str | Task) -> bool:
        """Check if a task is cancelled

        Args:
            task_or_id: Either a Task object or task ID string

        Returns:
            True if the task is cancelled, False otherwise
        """
        # Get task_id
        task_id = task_or_id.task_id if isinstance(task_or_id, Task) else task_or_id

        # Check Redis
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
