import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from redis import Redis
from buttercup.common.queues import ReliableQueue, QueueFactory, RQItem, QueueNames, GroupNames
from buttercup.common.datastructures.orchestrator_pb2 import TaskReady, Task, SourceDetail
from buttercup.common.datastructures.fuzzer_msg_pb2 import BuildRequest

logger = logging.getLogger(__name__)


@dataclass
class Scheduler:
    download_dir: Path
    redis: Redis
    sleep_time: float = 0.1
    mock_mode: bool = False
    ready_queue: ReliableQueue | None = field(init=False, default=None)
    build_requests_queue: ReliableQueue | None = field(init=False, default=None)

    def __post_init__(self):
        if self.redis is not None:
            queue_factory = QueueFactory(self.redis)
            self.ready_queue = queue_factory.create(QueueNames.READY_TASKS, GroupNames.SCHEDULER_READY_TASKS)
            self.build_requests_queue = queue_factory.create(QueueNames.BUILD)

    def mock_process_ready_task(self, task: Task) -> BuildRequest:
        """Mock a ready task processing"""
        repo_source = next(
            (source for source in task.sources if source.source_type == SourceDetail.SourceType.SOURCE_TYPE_REPO), None
        )
        if repo_source is not None and repo_source.path == "example-libpng":
            logger.info(f"Mocking task {task.task_id} / example-libpng")
            return BuildRequest(
                package_name="libpng",
                engine="libfuzzer",
                sanitizer="address",
                ossfuzz=f"/tasks_storage/{task.task_id}/fuzz-tooling",
            )

        raise RuntimeError(f"Couldn't handle task {task.task_id}")

    def process_ready_task(self, task: Task) -> BuildRequest:
        """Parse a task that has been downloaded and is ready to be built"""
        logger.info(f"Processing task {task.task_id}")
        if self.mock_mode:
            logger.info(f"Mock mode enabled, checking if {task.task_id} can be mocked")
            return self.mock_process_ready_task(task)

        raise RuntimeError(f"Couldn't handle task {task.task_id}")

    def serve_ready_task(self) -> bool:
        """Handle a ready task"""
        task_ready_item: RQItem[TaskReady] | None = self.ready_queue.pop()

        if task_ready_item is not None:
            task_ready: TaskReady = task_ready_item.deserialized
            try:
                build_request = self.process_ready_task(task_ready.task)
                self.build_requests_queue.push(build_request)
                self.ready_queue.ack_item(task_ready_item.item_id)
                logger.info(f"Pushed build request for task {task_ready.task.task_id} to build requests queue")
                return True
            except Exception as e:
                logger.error(f"Failed to process task {task_ready.task.task_id}: {e}")
                return False

        return False

    def serve(self):
        """Main loop to process tasks from queue"""
        if self.ready_queue is None:
            raise ValueError("Ready queue is not initialized")

        if self.build_requests_queue is None:
            raise ValueError("Build requests queue is not initialized")

        logger.info("Starting scheduler service")

        while True:
            self.serve_ready_task()
            # TODO: do other scheduler logic here

            logger.info(f"Sleeping for {self.sleep_time} seconds")
            time.sleep(self.sleep_time)
