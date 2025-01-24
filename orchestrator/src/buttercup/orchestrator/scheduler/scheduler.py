import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from redis import Redis
from buttercup.common.queues import ReliableQueue, QueueFactory, RQItem
from buttercup.common.datastructures.orchestrator_pb2 import TaskReady, Task, SourceDetail
from buttercup.common.datastructures.orchestrator_pb2 import BuildRequest

logger = logging.getLogger(__name__)


@dataclass
class Scheduler:
    download_dir: Path
    sleep_time: float = 0.1
    redis: Redis
    mock_mode: bool = False
    ready_queue: ReliableQueue | None = field(init=False, default=None)
    build_requests_queue: ReliableQueue | None = field(init=False, default=None)

    def __post_init__(self):
        if self.redis is not None:
            queue_factory = QueueFactory(self.redis)
            self.ready_queue = queue_factory.create_ready_tasks_queue()
            self.build_requests_queue = queue_factory.create_build_queue()
    
    def mock_process_ready_task(self, task: Task) -> BuildRequest:
        """Mock a ready task processing"""
        repo_source = next((source for source in task.sources if source.source_type == SourceDetail.SourceType.SOURCE_TYPE_REPO), None)
        if repo_source is not None and repo_source.path == "example-libpng":
            # TODO: figure out what to pass here
            return BuildRequest(
                package_name=repo_source.path,
                engine="libfuzzer",
                sanitizer="address",
                ossfuzz="libpng",
            )
        
        raise RuntimeError(f"Couldn't handle task {task.task_id}")
        
    def process_ready_task(self, task: Task) -> BuildRequest:
        """Parse a task that has been downloaded and is ready to be built"""
        logger.info(f"Processing task {task.task_id}")
        if self.mock_mode:
            logger.info(f"Mock mode enabled, checking if {task.task_id} can be mocked")
            return self.mock_process_ready_task(task)

        raise RuntimeError(f"Couldn't handle task {task.task_id}")

    def serve(self):
        """Main loop to process tasks from queue"""
        if self.ready_queue is None:
            raise ValueError("Ready queue is not initialized")

        if self.build_requests_queue is None:
            raise ValueError("Build requests queue is not initialized")

        logger.info("Starting scheduler service")

        while True:
            task_ready_item: RQItem[TaskReady] | None = self.ready_queue.pop()

            if task_ready_item is not None:
                task_ready: TaskReady = task_ready_item.deserialized
                try: 
                    build_request = self.process_ready_task(task_ready.task)
                except Exception as e:
                    logger.error(f"Failed to process task {task_ready.task.task_id}: {e}")
                    continue

                self.build_requests_queue.push(build_request)
                self.ready_queue.ack_item(task_ready_item.item_id)
                logger.info(f"Pushed build request for task {task_ready.task.task_id} to build requests queue")
                continue

            logger.info("No task ready to process")
            # TODO: do other scheduler logic here

            time.sleep(self.sleep_time)
