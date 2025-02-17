import logging
from redis import Redis
from buttercup.common.datastructures.msg_pb2 import SystemStatus, SystemState, TasksState
from buttercup.orchestrator.registry import TaskRegistry

logger = logging.getLogger(__name__)


class StatusCollector:
    """
    Collects and maintains system status information.
    """

    def __init__(self, redis: Redis):
        self.registry = TaskRegistry(redis)

    def get_status(self) -> SystemStatus:
        """
        Get current system status by analyzing tasks in the registry.

        Returns:
            SystemStatus: Current system state including task counts
        """
        # Initialize counters
        running = 0
        cancelled = 0
        succeeded = 0

        # Enumerate all tasks from registry
        for task in self.registry:
            if self.registry.is_cancelled(task):
                cancelled += 1
            elif not self.registry.is_stale(task):
                running += 1
            else:
                # Count expired but not cancelled tasks as succeeded
                succeeded += 1

        # Create and return status
        return SystemStatus(
            ready=True,  # Assuming system is ready if we can query the registry
            state=SystemState(
                tasks=TasksState(
                    running=running,
                    canceled=cancelled,  # Using the canceled field for cancelled tasks
                    pending=0,  # Not tracking pending state in current implementation
                    errored=0,  # Not tracking error state in current implementation
                    succeeded=succeeded,  # Count expired but not cancelled tasks as succeeded
                )
            ),
            version="0.1",  # TODO: Get version from package metadata or config file
        )
