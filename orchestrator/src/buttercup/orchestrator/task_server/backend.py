from buttercup.orchestrator.task_server.models.types import (
    Task,
    TaskType,
    SourceType,
)
from buttercup.common.datastructures.orchestrator_pb2 import (
    Task as TaskProto,
    SourceDetail as SourceDetailProto,
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
        res.append(task_proto)

    return res


def new_task(task: Task, tasks_queue: ReliableQueue) -> str:
    for task_proto in _api_task_to_proto(task):
        task_download = TaskDownload(task=task_proto)
        tasks_queue.push(task_download)
        logger.info(f"New task: {task_proto}")

    return task_proto.task_id
