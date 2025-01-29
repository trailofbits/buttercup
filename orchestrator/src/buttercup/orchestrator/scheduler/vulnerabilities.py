import logging
from dataclasses import dataclass, field
from redis import Redis
from buttercup.common.queues import (
    ReliableQueue,
    QueueFactory,
    RQItem,
    QueueNames,
    GroupNames,
)
from buttercup.common.datastructures.fuzzer_msg_pb2 import Crash

logger = logging.getLogger(__name__)

@dataclass
class Vulnerabilities:
    redis: Redis
    sleep_time: float = 1.0
    crash_queue: ReliableQueue | None = field(init=False, default=None)
    unique_vulnerabilities_queue: ReliableQueue | None = field(init=False, default=None)
    confirmed_vulnerabilities_queue: ReliableQueue | None = field(init=False, default=None)

    def __post_init__(self):
        if self.redis is not None:
            queue_factory = QueueFactory(self.redis)
            self.crash_queue = queue_factory.create(
                QueueNames.CRASH,
                GroupNames.ORCHESTRATOR,
                block_time=None
            )
            self.unique_vulnerabilities_queue = queue_factory.create(
                QueueNames.UNIQUE_VULNERABILITIES,
                block_time=None
            )
            self.confirmed_vulnerabilities_queue = queue_factory.create(
                QueueNames.CONFIRMED_VULNERABILITIES,
                block_time=None
            )

    def process_crashes(self) -> bool:
        """Process crashes from the crash queue"""
        if self.crash_queue is None:
            raise ValueError("Crash queue is not initialized")

        crash_item: RQItem[Crash] | None = self.crash_queue.pop()
        if crash_item is not None:
            try:
                crash: Crash = crash_item.deserialized
                unique_crash = self.dedup_crash(crash)
                if unique_crash is not None:
                    if self.unique_vulnerabilities_queue is None:
                        raise ValueError("Unique vulnerabilities queue is not initialized")
                    self.unique_vulnerabilities_queue.push(unique_crash)
                self.crash_queue.ack_item(crash_item.item_id)
                return True
            except Exception as e:
                logger.error(f"Failed to process crash: {e}")
                return False
        return False

    def process_unique_vulnerabilities(self) -> bool:
        """Process unique vulnerabilities from the unique vulnerabilities queue"""
        if self.unique_vulnerabilities_queue is None:
            raise ValueError("Unique vulnerabilities queue is not initialized")

        vuln_item: RQItem[Crash] | None = self.unique_vulnerabilities_queue.pop()
        if vuln_item is not None:
            try:
                crash: Crash = vuln_item.deserialized
                self.submit_vulnerability(crash)
                self.unique_vulnerabilities_queue.ack_item(vuln_item.item_id)
                return True
            except Exception as e:
                logger.error(f"Failed to process unique vulnerability: {e}")
                return False
        return False

    def dedup_crash(self, crash: Crash) -> Crash | None:
        """
        Deduplicate crashes based on their stack trace or other characteristics.
        Returns the Crash if unique, None otherwise.
        """
        # TODO: Implement actual deduplication logic here
        # For now, treating all crashes as unique
        return crash

    def submit_vulnerability(self, crash: Crash) -> None:
        """
        Submit the vulnerability to the confirmed vulnerabilities queue
        """
        if self.confirmed_vulnerabilities_queue is None:
            raise ValueError("Confirmed vulnerabilities queue is not initialized")
        
        logger.info(f"Submitting confirmed vulnerability for crash in {crash.target_binary}")
        self.confirmed_vulnerabilities_queue.push(crash)