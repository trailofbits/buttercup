from functools import lru_cache
from buttercup.common.datastructures.msg_pb2 import Task
from redis import Redis
from buttercup.common.queues import HashNames
from dataclasses import dataclass
from google.protobuf import text_format
import time
from typing import Set

# Redis set keys for tracking task states
CANCELLED_TASKS_SET = "cancelled_tasks"
SUCCEEDED_TASKS_SET = "succeeded_tasks"
ERRORED_TASKS_SET = "errored_tasks"


@dataclass
class TaskRegistry:
    """Keep track of all tasks in the system"""

    redis: Redis
    hash_name: str = HashNames.TASKS_REGISTRY

    def __len__(self):
        """Number of tasks in the registry"""
        return self.redis.hlen(self.hash_name)

    def __iter__(self):
        """Iterate over all tasks in the registry

        Returns tasks with their cancelled status set according to the cancelled tasks set.
        """
        tasks_dict = self.redis.hgetall(self.hash_name)

        # Get all cancelled task IDs for efficient lookup
        cancelled_task_ids = {
            k.decode("utf-8") if isinstance(k, bytes) else k for k in self.redis.smembers(CANCELLED_TASKS_SET)
        }

        # Process each task to ensure cancelled flag is set correctly
        for task_bytes in tasks_dict.values():
            task = Task.FromString(task_bytes)
            # Set cancelled flag based on presence in cancelled set
            prepared_key = self._prepare_key(task.task_id)
            task.cancelled = prepared_key in cancelled_task_ids
            yield task

    def __contains__(self, task_id: str) -> bool:
        """Check if a task ID exists in the registry"""
        return self.redis.hexists(self.hash_name, self._prepare_key(task_id))

    def _prepare_key(self, task_id: str) -> str:
        return task_id.lower()

    def set(self, task: Task):
        """Update a task in the registry"""
        self.redis.hset(self.hash_name, self._prepare_key(task.task_id), task.SerializeToString())

    def get(self, task_id: str) -> Task | None:
        """Get a task from the registry

        The task will have its cancelled flag set according to the cancelled tasks set.

        Args:
            task_id: The ID of the task to retrieve

        Returns:
            Task object if found, None otherwise
        """
        prepared_key = self._prepare_key(task_id)
        task_bytes = self.redis.hget(self.hash_name, prepared_key)
        if task_bytes is None:
            return None

        task = Task.FromString(task_bytes)

        # Set the cancelled flag based on presence in the cancelled tasks set
        task.cancelled = self.redis.sismember(CANCELLED_TASKS_SET, prepared_key)

        return task

    def delete(self, task_id: str):
        """Delete a task from the registry and remove it from the cancelled tasks set

        Args:
            task_id: The ID of the task to delete
        """
        prepared_key = self._prepare_key(task_id)

        # Use a pipeline to perform both operations atomically
        pipe = self.redis.pipeline()
        pipe.hdel(self.hash_name, prepared_key)
        pipe.srem(CANCELLED_TASKS_SET, prepared_key)
        pipe.execute()

    def mark_cancelled(self, task_or_id: str | Task):
        """Add the task ID to the cancelled tasks set

        This method does not modify the task object or update it in the registry.
        It only adds the task ID to the cancelled tasks set for efficient lookup.

        Args:
            task_or_id: Either a Task object or a task ID string to be added to the cancelled set
        """
        # Extract task_id based on the type of input
        task_id = task_or_id.task_id if isinstance(task_or_id, Task) else task_or_id

        # Add the task ID to the cancelled tasks set
        self.redis.sadd(CANCELLED_TASKS_SET, self._prepare_key(task_id))

    def is_cancelled(self, task_or_id: str | Task) -> bool:
        """Check if a task is cancelled by checking if its ID is in the cancelled tasks set

        Args:
            task_or_id: Either a Task object or task ID string

        Returns:
            True if the task is in the cancelled tasks set, False otherwise
        """
        # Get task_id
        task_id = task_or_id.task_id if isinstance(task_or_id, Task) else task_or_id
        prepared_key = self._prepare_key(task_id)

        # A task is cancelled if and only if it's in the cancelled tasks set
        return self.redis.sismember(CANCELLED_TASKS_SET, prepared_key)

    def is_expired(self, task_or_id: str | Task, delta_seconds: int = 0) -> bool:
        """Check if a task is expired based on its deadline. If delta_seconds is
        provided, it will be added to the deadline to consider the task expired
        only if enough time has passed since the deadline.

        Args:
            task_or_id: Either a Task object or task ID string
            delta_seconds: Optional delta in seconds to add to the deadline (default 0)

        Returns:
            True if the task is expired (deadline has passed), False otherwise.
            Returns False if the task doesn't exist.
        """

        @lru_cache(maxsize=1000)
        def get_deadline(task_id: str) -> int | None:
            task = self.get(task_id)
            return task.deadline if task else None

        # Get task if needed
        if isinstance(task_or_id, str):
            deadline = get_deadline(task_or_id)
            if deadline is None:
                return False
        else:
            deadline = task_or_id.deadline

        current_time = int(time.time())
        return deadline + delta_seconds <= current_time

    def get_live_tasks(self) -> list[Task]:
        """Get all tasks that are not cancelled or expired

        Uses the cancelled flag (already set by __iter__ based on the cancelled tasks set)
        and the is_expired function to filter tasks.

        Returns:
            list[Task]: List of active tasks
        """
        # Iterate through all tasks, filtering out cancelled and expired ones
        # The cancelled flag is already set correctly by the __iter__ method
        return [task for task in self if not task.cancelled and not self.is_expired(task)]

    def get_cancelled_task_ids(self) -> list[str]:
        """Get the IDs of all tasks that are marked as cancelled

        Returns:
            list[str]: List of task IDs that are in the cancelled tasks set
        """
        # Get all cancelled task IDs from the Redis set
        cancelled_ids = self.redis.smembers(CANCELLED_TASKS_SET)
        # Decode bytes to strings if needed
        return [task_id.decode("utf-8") if isinstance(task_id, bytes) else task_id for task_id in cancelled_ids]

    def should_stop_processing(self, task_or_id: str | Task, cancelled_ids: Set[str] | None = None) -> bool:
        """Check if a task should no longer be processed due to cancellation or expiration.

        Args:
            task_or_id: Either a Task object or a string task ID to check
            cancelled_ids: Optional set of task IDs that are known to be cancelled
                          If provided, will be used instead of checking the registry

        Returns:
            bool: True if the task should not be processed (is cancelled or expired),
                 False otherwise
        """

        # Extract task_id for cancelled IDs check
        task_id = task_or_id.task_id if isinstance(task_or_id, Task) else task_or_id

        # Check for cancellation - either using cancelled_ids if provided
        # or using the registry's is_cancelled method
        is_cancelled = False
        if cancelled_ids is not None:
            is_cancelled = task_id in cancelled_ids
        else:
            is_cancelled = self.is_cancelled(task_or_id)

        if is_cancelled:
            return True

        # Check if expired based on deadline - pass the task object directly when available
        if self.is_expired(task_or_id):
            return True

        return False

    def mark_successful(self, task_or_id: str | Task):
        """Add the task ID to the successful tasks set

        This method does not modify the task object or update it in the registry.
        It only adds the task ID to the successful tasks set for efficient lookup.

        Args:
            task_or_id: Either a Task object or a task ID string to be added to the successful set
        """
        # Extract task_id based on the type of input
        task_id = task_or_id.task_id if isinstance(task_or_id, Task) else task_or_id

        # Add the task ID to the successful tasks set
        self.redis.sadd(SUCCEEDED_TASKS_SET, self._prepare_key(task_id))

    def is_successful(self, task_or_id: str | Task) -> bool:
        """Check if a task is successful by checking if its ID is in the successful tasks set

        Args:
            task_or_id: Either a Task object or task ID string

        Returns:
            True if the task is in the successful tasks set, False otherwise
        """
        # Get task_id
        task_id = task_or_id.task_id if isinstance(task_or_id, Task) else task_or_id
        prepared_key = self._prepare_key(task_id)

        # A task is successful if and only if it's in the successful tasks set
        return self.redis.sismember(SUCCEEDED_TASKS_SET, prepared_key)

    def mark_errored(self, task_or_id: str | Task):
        """Add the task ID to the errored tasks set

        This method does not modify the task object or update it in the registry.
        It only adds the task ID to the errored tasks set for efficient lookup.

        Args:
            task_or_id: Either a Task object or a task ID string to be added to the errored set
        """
        # Extract task_id based on the type of input
        task_id = task_or_id.task_id if isinstance(task_or_id, Task) else task_or_id

        # Add the task ID to the errored tasks set
        self.redis.sadd(ERRORED_TASKS_SET, self._prepare_key(task_id))

    def is_errored(self, task_or_id: str | Task) -> bool:
        """Check if a task is errored by checking if its ID is in the errored tasks set

        Args:
            task_or_id: Either a Task object or task ID string

        Returns:
            True if the task is in the errored tasks set, False otherwise
        """
        # Get task_id
        task_id = task_or_id.task_id if isinstance(task_or_id, Task) else task_or_id
        prepared_key = self._prepare_key(task_id)

        # A task is errored if and only if it's in the errored tasks set
        return self.redis.sismember(ERRORED_TASKS_SET, prepared_key)


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

    # Display information about cancelled tasks set
    cancelled_task_ids = redis.smembers(CANCELLED_TASKS_SET)
    cancelled_count = len(cancelled_task_ids)
    print(f"Number of tasks in registry: {len(registry)}")
    print(f"Number of cancelled tasks: {cancelled_count}")

    if cancelled_count > 0:
        print("\nCancelled tasks:")
        for task_id in cancelled_task_ids:
            decoded_id = task_id.decode("utf-8") if isinstance(task_id, bytes) else task_id
            print(f"- {decoded_id}")

    # Show task details
    for task in registry:
        print()
        print("-" * 80)
        print(f"Task ID: {task.task_id} {'(CANCELLED)' if task.cancelled else ''}")
        # Check if in cancelled set for verification
        is_in_set = redis.sismember(CANCELLED_TASKS_SET, registry._prepare_key(task.task_id))
        if is_in_set != task.cancelled:
            print(f"WARNING: Inconsistency detected! In cancelled set: {is_in_set}, Task.cancelled: {task.cancelled}")
        print(text_format.MessageToString(task, print_unknown_fields=True, indent=2))
        print("-" * 80)
