import logging
from dataclasses import dataclass, field
from redis import Redis
from buttercup.common.queues import ReliableQueue, QueueFactory, RQItem, QueueNames, GroupNames
from buttercup.common.datastructures.msg_pb2 import TaskDelete
from buttercup.orchestrator.registry import TaskRegistry

logger = logging.getLogger(__name__)


@dataclass
class Cancellation:
    """Handles task cancellation requests in the orchestrator.

    This class processes task cancellation requests from a dedicated deletion queue.
    When a cancellation request is received, it updates the task's state in the registry
    to mark it as cancelled.

    Attributes:
        redis (Redis): Redis connection used for queue and registry operations
        delete_queue (ReliableQueue | None): Queue that receives task deletion requests
        registry (TaskRegistry | None): Registry for tracking and updating task states

    The class provides methods to:
    - Process individual deletion requests
    - Run a single iteration of the cancellation processing loop
    - Mark tasks as cancelled in the registry
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

    def process_cancellations(self) -> bool:
        """Process one iteration of the cancellation loop.

        Handles processing deletion requests from the queue.

        Returns:
            bool: True if any task was cancelled via delete request, False otherwise
        """
        # Process any delete requests
        delete_request: RQItem[TaskDelete] | None = self.delete_queue.pop()
        if delete_request:
            was_cancelled = self.process_delete_request(delete_request.deserialized)
            if was_cancelled:
                self.delete_queue.ack_item(delete_request.item_id)
                return True
        return False
