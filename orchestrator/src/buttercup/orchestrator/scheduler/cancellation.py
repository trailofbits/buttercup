import logging
from dataclasses import dataclass, field
from redis import Redis
from buttercup.common.queues import ReliableQueue, QueueFactory, RQItem, QueueNames, GroupNames
from buttercup.common.datastructures.msg_pb2 import TaskDelete
from buttercup.common.task_registry import TaskRegistry

logger = logging.getLogger(__name__)


@dataclass
class Cancellation:
    """Handles task cancellation.

    This class is responsible for:
    1. Processing task deletion requests from a queue
    2. Maintaining the task registry state by marking tasks as cancelled

    Note: Task expiration (deadline checks) is handled separately through the registry's is_expired
    method, used by the should_stop_processing utility function.

    Attributes:
        redis (Redis | None): Redis connection, will use default if None
        delete_queue (ReliableQueue | None): Queue for processing deletion requests
        registry (TaskRegistry | None): Registry for tracking task state
    """

    redis: Redis
    delete_queue: ReliableQueue | None = field(init=False, default=None)
    registry: TaskRegistry | None = field(init=False, default=None)

    def __post_init__(self):
        """Initialize Redis connection, deletion queue and task registry."""
        self.delete_queue = QueueFactory(self.redis).create(
            QueueNames.DELETE_TASK, GroupNames.ORCHESTRATOR, block_time=None
        )
        self.registry = TaskRegistry(self.redis)

    def process_delete_request(self, delete_request: TaskDelete) -> bool:
        """Process a task deletion request by marking it as cancelled in the registry.

        Args:
            delete_request: The TaskDelete request containing either a task_id to cancel
                           or a boolean 'all' flag to cancel all tasks

        Returns:
            bool: True if any task was successfully marked as cancelled, False otherwise
        """
        # Handle the case where 'all' is set to True
        if delete_request.HasField("all") and delete_request.all:
            logger.info(f"Processing delete request for ALL tasks, received at {delete_request.received_at}")
            any_cancelled = False

            # Iterate through all tasks and mark them as cancelled
            for task in self.registry:
                if not self.registry.is_cancelled(task):
                    self.registry.mark_cancelled(task)
                    logger.info(f"Task {task.task_id} marked as cancelled")
                    any_cancelled = True

            return any_cancelled

        # Handle the case where a specific task_id is provided
        elif delete_request.HasField("task_id"):
            task_id = delete_request.task_id
            logger.info(f"Processing delete request for task {task_id}")

            # Mark task as cancelled directly by ID without fetching it first
            self.registry.mark_cancelled(task_id)
            logger.info(f"Task {task_id}, cancel request received at {delete_request.received_at}, marked as cancelled")
            return True

        # Neither 'all' nor 'task_id' is set
        else:
            logger.warning("Delete request missing both 'task_id' and 'all' fields, ignoring")
            return False

    def process_cancellations(self) -> bool:
        """Process one iteration of the cancellation loop.

        Processes deletion requests from the queue and marks tasks as cancelled in the registry.
        Task expiration is handled separately through the registry.is_expired method.

        Returns:
            bool: True if any task was cancelled via delete request, False otherwise
        """
        any_cancellation = False

        # Process any delete requests
        delete_request: RQItem[TaskDelete] | None = self.delete_queue.pop()
        if delete_request:
            was_cancelled = self.process_delete_request(delete_request.deserialized)
            self.delete_queue.ack_item(delete_request.item_id)
            any_cancellation = was_cancelled

        return any_cancellation
