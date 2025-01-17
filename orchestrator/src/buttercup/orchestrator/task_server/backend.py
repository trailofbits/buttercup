from buttercup.orchestrator.task_server.models.types import (
    Task,
    Status,
    VulnBroadcast,
    TaskType,
    StatusState,
    StatusTasksState,
    SourceType,
)
from uuid import UUID
from buttercup.common.datastructures.orchestrator_pb2 import (
    Task as TaskProto,
    SourceDetail as SourceDetailProto,
    TaskDownload,
)
from buttercup.common.queues import ReliableQueue
from buttercup.orchestrator.data import TaskRegistry
import logging

logger = logging.getLogger(__name__)


def _api_task_to_proto(task: Task) -> list[TaskProto]:
    res = []
    for task_detail in task.tasks:
        task_proto = TaskProto()
        task_proto.message_id = task.message_id
        task_proto.message_time = task.message_time
        task_proto.task_id = task_detail.task_id
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
        task_proto.task_status = TaskProto.TaskStatus.TASK_STATUS_PENDING
        res.append(task_proto)

    return res


def new_task(task: Task, tasks_queue: ReliableQueue, task_registry: TaskRegistry) -> str:
    for task_proto in _api_task_to_proto(task):
        # If we already have a task with the same id but it's still pending, we
        # might have crashed between the queue and the registry.
        if (task_detail := task_registry.get_task(task_proto.task_id)) is not None and task_detail.task_status != TaskProto.TaskStatus.TASK_STATUS_PENDING:
            logger.warning(f"Task {task_proto.task_id} already exists in registry, skipping")
            continue

        task_download = TaskDownload(task_id=task_proto.task_id)
        task_registry.update_task(task_proto.task_id, task_proto)
        tasks_queue.push(task_download)
        logger.info(f"New task: {task_proto}")

    return task_proto.task_id


def get_status(task_registry: TaskRegistry) -> Status:
    counts = task_registry.count_by_status()
    logger.info(f"Counts: {counts}")
    return Status(
        ready=True,
        state=StatusState(
            tasks=StatusTasksState(
                pending=counts[TaskProto.TaskStatus.TASK_STATUS_PENDING],
                running=counts[TaskProto.TaskStatus.TASK_STATUS_RUNNING],
                succeeded=counts[TaskProto.TaskStatus.TASK_STATUS_SUCCEEDED],
                errored=counts[TaskProto.TaskStatus.TASK_STATUS_FAILED],
                canceled=counts[TaskProto.TaskStatus.TASK_STATUS_CANCELLED],
            )
        ),
        version="0.0.1",
    )


def submit_sarif(sarif: VulnBroadcast) -> str:
    logger.warning("Not implemented")
    return ""


def delete_task(task_id: UUID, task_registry: TaskRegistry) -> None:
    task_registry.delete_task(str(task_id))
    return ""
