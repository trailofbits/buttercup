import logging
import redis
from redis import Redis
from functools import lru_cache
from buttercup.orchestrator.task_server.config import TaskServerSettings
from buttercup.common.queues import ReliableQueue, QueueNames, QueueFactory
from buttercup.common.sarif_store import SARIFStore

logger = logging.getLogger(__name__)


@lru_cache
def get_settings():
    return TaskServerSettings()


@lru_cache
def get_redis() -> Redis:
    logger.debug(f"Connecting to Redis at {get_settings().redis_url}")
    return redis.Redis.from_url(get_settings().redis_url, decode_responses=False)


@lru_cache
def get_task_queue() -> ReliableQueue:
    """
    Get a ReliableQueue instance for task messages.

    Returns:
        ReliableQueue: Queue for task messages
    """
    logger.debug(f"Connecting to task queue at {QueueNames.DOWNLOAD_TASKS}")
    return QueueFactory(get_redis()).create(QueueNames.DOWNLOAD_TASKS)


@lru_cache
def get_delete_task_queue() -> ReliableQueue:
    """
    Get a ReliableQueue instance for task deletion messages.

    Returns:
        ReliableQueue: Queue for task deletion messages
    """
    logger.debug(f"Connecting to delete task queue at {QueueNames.DELETE_TASK}")
    return QueueFactory(get_redis()).create(QueueNames.DELETE_TASK)


def get_sarif_store() -> SARIFStore:
    """
    Get a SARIFStore instance for SARIF storage and retrieval.

    Returns:
        SARIFStore: Store for SARIF objects
    """
    return SARIFStore(get_redis())
