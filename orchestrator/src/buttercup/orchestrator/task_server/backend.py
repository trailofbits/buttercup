import time
from uuid import UUID
from buttercup.orchestrator.task_server.models.types import (
    Task,
    TaskType,
    SourceType,
    StatusTasksState,
    SARIFBroadcast,
)
from buttercup.common.datastructures.msg_pb2 import (
    Task as TaskProto,
    SourceDetail as SourceDetailProto,
    TaskDelete,
    TaskDownload,
)
from buttercup.common.queues import ReliableQueue
from buttercup.common.sarif_store import SARIFStore
from buttercup.common.task_registry import TaskRegistry
from redis import Redis
import logging


logger = logging.getLogger(__name__)


def _api_task_to_proto(task: Task) -> list[TaskProto]:
    res = []
    for task_detail in task.tasks:
        if not task_detail.harnesses_included:
            logger.debug("Skipping Unharnessed Task %s", task_detail.task_id.lower())
            continue
        task_proto = TaskProto()
        task_proto.message_id = task.message_id
        task_proto.message_time = task.message_time
        task_proto.task_id = task_detail.task_id.lower()
        task_proto.project_name = task_detail.project_name
        task_proto.focus = task_detail.focus
        match task_detail.type:
            case TaskType.TaskTypeFull:
                task_proto.task_type = TaskProto.TaskType.TASK_TYPE_FULL
            case TaskType.TaskTypeDelta:
                task_proto.task_type = TaskProto.TaskType.TASK_TYPE_DELTA

        for source in task_detail.source:
            source_detail = task_proto.sources.add()
            source_detail.sha256 = source.sha256
            match source.type:
                case SourceType.SourceTypeRepo:
                    source_detail.source_type = SourceDetailProto.SourceType.SOURCE_TYPE_REPO
                case SourceType.SourceTypeFuzzTooling:
                    source_detail.source_type = SourceDetailProto.SourceType.SOURCE_TYPE_FUZZ_TOOLING
                case SourceType.SourceTypeDiff:
                    source_detail.source_type = SourceDetailProto.SourceType.SOURCE_TYPE_DIFF
                case _:
                    logger.warning(f"Unknown source type: {source.source_type}")
            source_detail.url = source.url

        # Convert deadline from milliseconds to seconds (we don't need the precision)
        task_proto.deadline = task_detail.deadline // 1000

        # Populate metadata field
        for key, value in task_detail.metadata.items():
            task_proto.metadata[key] = str(value)

        res.append(task_proto)

    return res


def new_task(task: Task, tasks_queue: ReliableQueue) -> str:
    for task_proto in _api_task_to_proto(task):
        task_download = TaskDownload(task=task_proto)
        tasks_queue.push(task_download)
        logger.info(f"New task: {task_proto}")

    return "DONE"


def delete_task(task_id: UUID, delete_task_queue: ReliableQueue) -> str:
    """
    Delete a task by pushing a delete request to the task deletion queue.

    Args:
        task_id: The unique identifier of the task to delete
        delete_task_queue: Queue for processing task deletion requests

    Returns:
        Empty string on successful deletion request
    """
    task_delete = TaskDelete(task_id=str(task_id).lower(), received_at=time.time())
    delete_task_queue.push(task_delete)
    return ""


def delete_all_tasks(delete_task_queue: ReliableQueue) -> str:
    """
    Delete all tasks by pushing a delete request with the 'all' flag to the task deletion queue.

    Args:
        delete_task_queue: Queue for processing task deletion requests

    Returns:
        Empty string on successful deletion request
    """
    task_delete = TaskDelete(all=True, received_at=time.time())
    delete_task_queue.push(task_delete)
    return ""


def store_sarif_broadcast(broadcast: SARIFBroadcast, sarif_store: SARIFStore) -> str:
    """
    Store SARIF broadcast details in Redis.

    Args:
        broadcast: The SARIFBroadcast containing a list of SARIFBroadcastDetail
        sarif_store: SARIFStore instance for storage

    Returns:
        Empty string on successful storage
    """
    for sarif_detail in broadcast.broadcasts:
        logger.info(f"Storing SARIF detail for task {sarif_detail.task_id}, SARIF ID: {sarif_detail.sarif_id}")
        sarif_store.store(sarif_detail)

    return ""


def get_status_tasks_state(redis_url: str) -> StatusTasksState:
    """
    Get the current state of tasks in the system.

    Returns:
        StatusTasksState: The current state of tasks in the system
    """
    redis = Redis.from_url(redis_url)
    registry = TaskRegistry(redis)

    tasks_cancelled = 0
    tasks_errored = 0
    tasks_failed = 0
    tasks_processing = 0
    tasks_succeeded = 0

    for task in registry:
        if registry.is_cancelled(task):
            tasks_cancelled += 1
        elif not registry.is_expired(task):
            tasks_processing += 1
        elif registry.is_successful(task):
            tasks_succeeded += 1
        elif registry.is_errored(task):
            tasks_errored += 1
        else:
            tasks_failed += 1

    return StatusTasksState(
        canceled=tasks_cancelled,
        errored=tasks_errored,
        failed=tasks_failed,
        pending=0,
        processing=tasks_processing,
        succeeded=tasks_succeeded,
        waiting=0,
    )
