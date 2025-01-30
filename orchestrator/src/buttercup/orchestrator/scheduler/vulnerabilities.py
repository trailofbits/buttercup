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
from buttercup.common.datastructures.msg_pb2 import ConfirmedVulnerability, Crash
import uuid

logger = logging.getLogger(__name__)


@dataclass
class Vulnerabilities:
    redis: Redis
    sleep_time: float = 1.0
    crash_queue: ReliableQueue = field(init=False)
    unique_vulnerabilities_queue: ReliableQueue = field(init=False)
    confirmed_vulnerabilities_queue: ReliableQueue = field(init=False)

    def __post_init__(self):
        queue_factory = QueueFactory(self.redis)
        self.crash_queue = queue_factory.create(QueueNames.CRASH, GroupNames.ORCHESTRATOR, block_time=None)
        self.unique_vulnerabilities_queue = queue_factory.create(
            QueueNames.UNIQUE_VULNERABILITIES, GroupNames.UNIQUE_VULNERABILITIES, block_time=None
        )
        self.confirmed_vulnerabilities_queue = queue_factory.create(
            QueueNames.CONFIRMED_VULNERABILITIES, block_time=None
        )

    def process_crashes(self) -> bool:
        """Process crashes from the crash queue"""
        crash_item: RQItem[Crash] | None = self.crash_queue.pop()
        if crash_item is not None:
            try:
                crash: Crash = crash_item.deserialized
                unique_crash = self.dedup_crash(crash)
                if unique_crash is not None:
                    self.unique_vulnerabilities_queue.push(unique_crash)
                self.crash_queue.ack_item(crash_item.item_id)
                return True
            except Exception as e:
                logger.error(f"Failed to process crash: {e}")
                return False
        return False

    def process_unique_vulnerabilities(self) -> bool:
        """Process unique vulnerabilities from the unique vulnerabilities queue"""
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
        logger.info(f"Submitting confirmed vulnerability for crash in {crash.target.package_name}")
        # TODO: This is where we would submit the vulnerability to the competition api and get the vuln_id back
        confirmed_vuln = ConfirmedVulnerability()
        confirmed_vuln.crash.CopyFrom(crash)
        confirmed_vuln.vuln_id = str(uuid.uuid4())  # TODO: ID got from the Competition API
        self.confirmed_vulnerabilities_queue.push(confirmed_vuln)
