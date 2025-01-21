from buttercup.common.datastructures.orchestrator_pb2 import Task
from redis import Redis
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
