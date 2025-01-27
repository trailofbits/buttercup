import logging
import time
from dataclasses import dataclass, field
from redis import Redis

from buttercup.common.queues import ReliableQueue, QueueFactory
from buttercup.common.datastructures.orchestrator_pb2 import TaskDelete
from buttercup.orchestrator.registry import TaskRegistry
from buttercup.orchestrator.task_server.dependencies import get_redis

logger = logging.getLogger(__name__)


@dataclass
class Cancellation:
    """Handles task cancellation and timeout detection.

    This class is responsible for:
    1. Processing task deletion requests from a queue
    2. Checking for and handling timed out tasks
    3. Maintaining the task registry state

    Attributes:
        DELETE_QUEUE_BLOCK_TIME_MS (int): Block time in milliseconds for checking delete requests.
            Set to 10 seconds to reduce load on task registry since cancellation is not time-critical.
        sleep_time (float): Safety delay between processing cycles, defaults to 0.1s
        redis (Redis | None): Redis connection, will use default if None
        delete_queue (ReliableQueue | None): Queue for processing deletion requests
        registry (TaskRegistry | None): Registry for tracking task state
    """

    DELETE_QUEUE_BLOCK_TIME_MS = 10 * 1000

    sleep_time: float = 0.1
    redis: Redis | None = None
    delete_queue: ReliableQueue | None = field(init=False, default=None)
    registry: TaskRegistry | None = field(init=False, default=None)

    def __post_init__(self):
        """Initialize Redis connection, deletion queue and task registry."""
        if self.redis is None:
            self.redis = get_redis()

        # TODO: If we end up integrating this into the main event loop, we should use a non-blocking queue
        self.delete_queue = QueueFactory(self.redis).create_delete_task_queue(
            block_time=self.DELETE_QUEUE_BLOCK_TIME_MS
        )
        self.registry = TaskRegistry(self.redis)

    def process_delete_request(self, delete_request: TaskDelete):
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
            return True
        else:
            logger.info(f"No task found for task_id {delete_request.task_id}")
            return False

    def check_timeouts(self):
        """Check for timed out tasks and mark them as cancelled in the registry.

        Iterates through all tasks in the registry and marks any as cancelled that have passed
        their deadline timestamp.
        """
        current_time = time.time()

        for task in self.registry:
            if task.deadline < current_time:
                logger.info(f"Task {task.task_id} has timed out, marking as cancelled")
                self.registry.mark_cancelled(task)

    def process_iteration(self):
        """Process one iteration of the cancellation loop.

        Handles:
        1. Processing any deletion requests from the queue
        2. Checking for and handling any timed out tasks

        Note: Consider whether this processing could be integrated into the orchestrator's
        main event loop rather than running in its own loop. If so, the queue pop() would
        need to be non-blocking to avoid stalling other operations.
        """
        # Process any delete requests
        delete_request = self.delete_queue.pop()
        if delete_request:
            was_cancelled = self.process_delete_request(delete_request.deserialized)
            if was_cancelled:
                self.delete_queue.ack_item(delete_request.item_id)

        # Check for timed out tasks
        self.check_timeouts()

    def run(self):
        """Main processing loop that handles deletions and timeouts.

        Continuously runs process_iteration() to:
        1. Check for and process any deletion requests from the queue
        2. Check for and handle any timed out tasks
        3. Sleep briefly to prevent excessive CPU usage
        """
        while True:
            self.process_iteration()
            # Safety check to prevent the process from running too fast
            time.sleep(self.sleep_time)


def main():
    """Main entry point for the cancellation service.

    Initializes and runs the Cancellation service which handles task deletions
    and timeout detection.
    """
    logging.basicConfig(level=logging.INFO)
    logger.info("Starting cancellation service")

    cancellation = Cancellation()
    cancellation.run()


if __name__ == "__main__":
    main()
