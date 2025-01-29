import logging
import time
from dataclasses import dataclass, field
from redis import Redis

from buttercup.common.queues import ReliableQueue, QueueFactory, RQItem
from buttercup.common.datastructures.orchestrator_pb2 import TaskDelete
from buttercup.orchestrator.registry import TaskRegistry

logger = logging.getLogger(__name__)


@dataclass
class Cancellation:
    """Handles task cancellation and timeout detection.

    This class is responsible for:
    1. Processing task deletion requests from a queue
    2. Checking for and handling timed out tasks
    3. Maintaining the task registry state

    Attributes:
        sleep_time (float): Safety delay between processing cycles, defaults to 1.0s
        redis (Redis | None): Redis connection, will use default if None
        delete_queue (ReliableQueue | None): Queue for processing deletion requests
        registry (TaskRegistry | None): Registry for tracking task state
    """

    sleep_time: float = 1.0
    redis: Redis | None = None
    delete_queue: ReliableQueue | None = field(init=False, default=None)
    registry: TaskRegistry | None = field(init=False, default=None)

    def __post_init__(self):
        """Initialize Redis connection, deletion queue and task registry."""
        if self.redis is None:
            raise ValueError("Redis connection is not initialized")

        self.delete_queue = QueueFactory(self.redis).create_delete_task_queue(block_time=None)
        self.registry = TaskRegistry(self.redis)

    def process_delete_request(self, delete_request: TaskDelete) -> bool:
        """Process a task deletion request by marking it as cancelled in the registry.

        Args:
            delete_request: The TaskDelete request containing the task_id to cancel

        Returns:
            bool: True if the task was successfully marked as cancelled, False otherwise
        """
        logger.info(f"Processing delete request for task {delete_request.task_id}")
        task = self.registry.get(delete_request.task_id)
        if task:
            self.registry.mark_cancelled(task)
            logger.info(
                f"Task {delete_request.task_id}, cancel request received at {task.received_at}, marked as cancelled"
            )
            return True
        else:
            logger.info(f"No task found for task_id {delete_request.task_id}")
            return False

    def check_timeouts(self) -> bool:
        """Check for timed out tasks and mark them as cancelled in the registry.

        Iterates through all tasks in the registry and marks any as cancelled that have passed
        their deadline timestamp.

        Returns:
            bool: True if any task was cancelled, False otherwise
        """
        current_time = time.time()
        any_cancelled = False

        for task in self.registry:
            if task.deadline < current_time:
                logger.info(f"Task {task.task_id} has timed out, marking as cancelled")
                self.registry.mark_cancelled(task)
                any_cancelled = True

        return any_cancelled

    def process_cancellations(self) -> bool:
        """Process one iteration of the cancellation loop.

        Handles:
        1. Processing any deletion requests from the queue
        2. Checking for and handling any timed out tasks

        Returns:
            bool: True if any task was cancelled (via delete request or timeout), False otherwise
        """
        any_cancellation = False

        # Process any delete requests
        delete_request: RQItem[TaskDelete] | None = self.delete_queue.pop()
        if delete_request:
            was_cancelled = self.process_delete_request(delete_request.deserialized)
            if was_cancelled:
                self.delete_queue.ack_item(delete_request.item_id)
                any_cancellation = True

        # Check for timed out tasks
        any_cancellation |= self.check_timeouts()
        return any_cancellation
