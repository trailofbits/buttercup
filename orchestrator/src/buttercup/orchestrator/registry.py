from buttercup.common.datastructures.orchestrator_pb2 import Task
from redis import Redis
from buttercup.common.queues import HashNames
from dataclasses import dataclass
from collections import UserDict


@dataclass
class TaskRegistry(UserDict):
    """Keep track of all tasks in the system. Acts as a dict-like interface to the Redis hash."""

    redis: Redis

    def __getitem__(self, task_id: str) -> Task:
        """Dict-like access: registry[task_id]"""
        task = self.get(task_id)
        if task is None:
            raise KeyError(f"Task {task_id} not found")
        return task

    def __setitem__(self, task_id: str, task: Task):
        """Dict-like assignment: registry[task_id] = task"""
        self.set(task_id, task)

    def __delitem__(self, task_id: str):
        """Dict-like deletion: del registry[task_id]"""
        self.delete(task_id)

    def __len__(self):
        """Number of tasks in the registry"""
        return self.redis.hlen(HashNames.TASKS_REGISTRY)

    def __iter__(self):
        """Iterate over task IDs in the registry"""
        return iter(self.redis.hkeys(HashNames.TASKS_REGISTRY))

    def __contains__(self, task_id: str) -> bool:
        """Check if a task ID exists in the registry"""
        return self.redis.hexists(HashNames.TASKS_REGISTRY, task_id.upper())

    def items(self):
        """Iterate over (task_id, task) pairs in the registry"""
        for task_id in self:
            yield task_id, self[task_id]

    def set(self, task_id: str, task: Task):
        """Update a task in the registry"""
        self.redis.hset(HashNames.TASKS_REGISTRY, task_id.upper(), task.SerializeToString())

    def get(self, task_id: str) -> Task | None:
        """Get a task from the registry"""
        task_bytes = self.redis.hget(HashNames.TASKS_REGISTRY, task_id.upper())
        if task_bytes is None:
            return None

        return Task.FromString(task_bytes)

    def delete(self, task_id: str):
        """Delete a task from the registry"""
        self.redis.hdel(HashNames.TASKS_REGISTRY, task_id.upper())


def task_registry_cli():
    """CLI for the task registry"""
    from pydantic_settings import BaseSettings
    from typing import Annotated
    from pydantic import Field
    from google.protobuf import text_format

    class TaskRegistrySettings(BaseSettings):
        redis_url: Annotated[str, Field(default="redis://localhost:6379", description="Redis URL")]

        class Config:
            env_prefix = "BUTTERCUP_TASK_REGISTRY_"
            env_file = ".env"
            cli_parse_args = True

    settings = TaskRegistrySettings()
    redis = Redis.from_url(settings.redis_url, decode_responses=False)
    registry = TaskRegistry(redis)
    print("Number of tasks in registry:", len(registry))
    for task_id, task in registry.items():
        print()
        print("-" * 80)
        print("Task ID:", task_id)
        print(text_format.MessageToString(task, print_unknown_fields=True, indent=2))
        print("-" * 80)
