from buttercup.common.datastructures.orchestrator_pb2 import Task
from redis import Redis
from typing import Dict
from buttercup.common.queues import TASKS_REGISTRY_HASH_NAME


class TaskRegistry:
    def __init__(self, redis: Redis):
        self.redis = redis
        self.hash_name = TASKS_REGISTRY_HASH_NAME

    def update_task(self, task_id: str, task: Task):
        self.redis.hset(self.hash_name, task_id.upper(), task.SerializeToString())

    def get_task(self, task_id: str) -> Task:
        task_bytes = self.redis.hget(self.hash_name, task_id.upper())
        if task_bytes is None:
            return None

        return Task.FromString(task_bytes)

    def delete_task(self, task_id: str):
        self.redis.hdel(self.hash_name, task_id.upper())

    def count_by_status(self) -> Dict[Task.TaskStatus, int]:
        # Initialize counters for each status
        counts = {
            Task.TaskStatus.TASK_STATUS_PENDING: 0,
            Task.TaskStatus.TASK_STATUS_RUNNING: 0,
            Task.TaskStatus.TASK_STATUS_SUCCEEDED: 0,
            Task.TaskStatus.TASK_STATUS_FAILED: 0,
            Task.TaskStatus.TASK_STATUS_CANCELLED: 0,
        }

        # Get all tasks and count by status
        for task_bytes in self.redis.hvals(self.hash_name):
            task = Task.FromString(task_bytes)
            counts[task.task_status] += 1

        return counts
