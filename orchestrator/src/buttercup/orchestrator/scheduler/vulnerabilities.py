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
from buttercup.orchestrator.competition_api_client.api.vulnerability_api import VulnerabilityApi
from buttercup.orchestrator.competition_api_client.models.types_vuln_submission import TypesVulnSubmission
from buttercup.orchestrator.competition_api_client.models.types_submission_status import TypesSubmissionStatus

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
                # TODO: Once provenance is implemented, check if the task is cancelled
                # before submitting the vulnerability. Issue #36.
                crash: Crash = vuln_item.deserialized
                confirmed_vuln = self.submit_vulnerability(crash)
                # Acknowledge the item regardless of submission result
                self.unique_vulnerabilities_queue.ack_item(vuln_item.item_id)
                if confirmed_vuln is not None:
                    self.confirmed_vulnerabilities_queue.push(confirmed_vuln)
                return confirmed_vuln is not None
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

    def submit_vulnerability(self, crash: Crash) -> ConfirmedVulnerability | None:
        """
        Submit the vulnerability to the competition API

        Returns:
            ConfirmedVulnerability | None: The confirmed vulnerability with API-provided ID if successful,
                                          None if submission was not accepted

        Raises:
            Exception: If there is an error communicating with the API
        """
        logger.info(f"Submitting confirmed vulnerability for crash in {crash.target.package_name}")
        try:
            # Create vulnerability API client
            vuln_api = VulnerabilityApi()

            # Create submission payload from crash data
            submission = TypesVulnSubmission(
                architecture="x86_64",  # TODO: Issue #50
                data_file=crash.crash_input_path,  # TODO: Read the contents of the file instead
                harness_name=crash.harness_path,
                sanitizer=crash.target.sanitizer,
                sarif=None,  # Optional, not provided in crash data
            )

            # Submit vulnerability and get response
            response = vuln_api.v1_task_task_id_vuln_post(
                task_id=crash.target.source_path,  # TODO: Issue #36, provenance of crashes
                payload=submission,
            )

            # Check submission status before proceeding
            if response.status != TypesSubmissionStatus.ACCEPTED:
                logger.error(
                    f"Vulnerability submission not accepted. Status: {response.status}\n"
                    f"Task ID: {crash.target.source_path}\n"
                    f"Package: {crash.target.package_name}"
                )
                return None

            # Create confirmed vulnerability with API-provided ID
            confirmed_vuln = ConfirmedVulnerability()
            confirmed_vuln.crash.CopyFrom(crash)
            confirmed_vuln.vuln_id = response.vuln_id

            return confirmed_vuln

        except Exception as e:
            logger.error(
                f"Failed to submit vulnerability to competition API: {str(e)}\n"
                f"Task ID: {crash.target.source_path}\n"
                f"Package: {crash.target.package_name}\n"
                f"Crash details: {crash}"
            )
            raise
