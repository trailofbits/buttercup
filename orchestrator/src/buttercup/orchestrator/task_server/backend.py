import time
from uuid import UUID
from buttercup.orchestrator.task_server.models.types import (
    Task,
    TaskType,
    SourceType,
)
from buttercup.common.datastructures.msg_pb2 import (
    Task as TaskProto,
    SourceDetail as SourceDetailProto,
    TaskDelete,
    TaskDownload,
)
from buttercup.common.queues import ReliableQueue
import logging


logger = logging.getLogger(__name__)


def _api_task_to_proto(task: Task) -> list[TaskProto]:
    res = []
    for task_detail in task.tasks:
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

        task_proto.deadline = task_detail.deadline
        res.append(task_proto)

    return res


def new_task(task: Task, tasks_queue: ReliableQueue) -> str:
    for task_proto in _api_task_to_proto(task):
        task_download = TaskDownload(task=task_proto)
        tasks_queue.push(task_download)
        logger.info(f"New task: {task_proto}")

    return task_proto.task_id


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
