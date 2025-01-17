import logging
import redis
from redis import Redis
from functools import lru_cache
from buttercup.orchestrator.config import Settings
from buttercup.common.queues import ReliableQueue, TASKS_QUEUE_NAME, TASKS_GROUP_NAME
from buttercup.common.datastructures.orchestrator_pb2 import TaskDownload
from buttercup.orchestrator.data import TaskRegistry

logger = logging.getLogger(__name__)


@lru_cache
def get_settings():
    return Settings()


@lru_cache
def get_redis() -> Redis:
    logger.debug(f"Connecting to Redis at {get_settings().redis_url}")
    return redis.Redis.from_url(get_settings().redis_url, decode_responses=False)


@lru_cache
def get_task_queue() -> ReliableQueue:
    logger.debug(f"Connecting to task queue at {TASKS_QUEUE_NAME}")
    return ReliableQueue(TASKS_QUEUE_NAME, TASKS_GROUP_NAME, get_redis(), 108000, TaskDownload)


@lru_cache
def get_task_registry() -> TaskRegistry:
    return TaskRegistry(get_redis())
