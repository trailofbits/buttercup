import base64
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
from buttercup.orchestrator.competition_api_client.configuration import Configuration
from buttercup.orchestrator.competition_api_client.api_client import ApiClient
from buttercup.orchestrator.competition_api_client.models.types_vuln_submission import TypesVulnSubmission
from buttercup.orchestrator.competition_api_client.models.types_submission_status import TypesSubmissionStatus
from buttercup.orchestrator.registry import TaskRegistry
from common.src.buttercup.common.constants import ARCHITECTURE

logger = logging.getLogger(__name__)


@dataclass
class Vulnerabilities:
    redis: Redis
    competition_api_url: str
    sleep_time: float = 1.0
    crash_queue: ReliableQueue = field(init=False)
    unique_vulnerabilities_queue: ReliableQueue = field(init=False)
    confirmed_vulnerabilities_queue: ReliableQueue = field(init=False)
    task_registry: TaskRegistry = field(init=False)
    competition_vulnerability_api: VulnerabilityApi = field(init=False)

    def __setup_vulnerability_api(self) -> VulnerabilityApi:
        """Initialize the competition vulnerability API client."""
        configuration = Configuration(
            host=self.competition_api_url,
            username="api_key_id",  # TODO: Make configurable
            password="api_key_token",  # TODO: Make configurable
        )
        logger.info(f"Initializing vulnerability API client with URL: {self.competition_api_url}")
        api_client = ApiClient(configuration=configuration)
        return VulnerabilityApi(api_client=api_client)

    def __post_init__(self):
        queue_factory = QueueFactory(self.redis)
        self.crash_queue = queue_factory.create(QueueNames.CRASH, GroupNames.ORCHESTRATOR, block_time=None)
        self.unique_vulnerabilities_queue = queue_factory.create(
            QueueNames.UNIQUE_VULNERABILITIES, GroupNames.UNIQUE_VULNERABILITIES, block_time=None
        )
        self.confirmed_vulnerabilities_queue = queue_factory.create(
            QueueNames.CONFIRMED_VULNERABILITIES, block_time=None
        )
        self.task_registry = TaskRegistry(self.redis)
        self.competition_vulnerability_api = self.__setup_vulnerability_api()
        logger.info(
            f"Competition vulnerability API client initialized: {self.competition_vulnerability_api is not None}"
        )

    def process_crashes(self) -> bool:
        """Process crashes from the crash queue"""
        crash_item: RQItem[Crash] | None = self.crash_queue.pop()
        if crash_item is not None:
            try:
                crash: Crash = crash_item.deserialized
                logger.info(
                    f"Received crash:\n"
                    f"Task ID: {crash.target.task_id}\n"
                    f"Package: {crash.target.package_name}\n"
                    f"Harness: {crash.harness_name}"
                )
                unique_crash = self.dedup_crash(crash)
                if unique_crash is not None:
                    logger.info(
                        f"Crash determined to be unique, pushing to unique vulnerabilities queue:\n"
                        f"Task ID: {crash.target.task_id}\n"
                        f"Package: {crash.target.package_name}\n"
                        f"Harness: {crash.harness_name}"
                    )
                    self.unique_vulnerabilities_queue.push(unique_crash)
                else:
                    logger.info(
                        f"Crash determined to be duplicate, skipping:\n"
                        f"Task ID: {crash.target.task_id}\n"
                        f"Package: {crash.target.package_name}\n"
                        f"Harness: {crash.harness_name}"
                    )
                self.crash_queue.ack_item(crash_item.item_id)
                return True
            except Exception as e:
                logger.error(f"Failed to process crash: {e}")
                return False
        return False

    def process_unique_vulnerabilities(self) -> bool:
        """Process unique vulnerabilities from the unique vulnerabilities queue.

        This method:
        1. Pops a vulnerability from the unique vulnerabilities queue
        2. Checks if the associated task is cancelled
        3. If not cancelled, submits the vulnerability to the competition API
        4. If submission is successful, pushes to confirmed vulnerabilities queue
        5. Acknowledges the processed item

        Returns:
            bool: True if an item was processed (even if it failed), False if queue was empty
        """
        """Process unique vulnerabilities from the unique vulnerabilities queue"""
        vuln_item: RQItem[Crash] | None = self.unique_vulnerabilities_queue.pop()
        if vuln_item is None:
            return False

        try:
            crash: Crash = vuln_item.deserialized

            if self.task_registry.is_cancelled(crash.target.task_id):
                logger.info(
                    f"Skipping vulnerability submission for cancelled task:\n"
                    f"Task ID: {crash.target.task_id}\n"
                    f"Package: {crash.target.package_name}\n"
                    f"Harness: {crash.harness_name}"
                )
            else:
                confirmed_vuln = self.submit_vulnerability(crash)
                if confirmed_vuln is not None:
                    self.confirmed_vulnerabilities_queue.push(confirmed_vuln)

            self.unique_vulnerabilities_queue.ack_item(vuln_item.item_id)
        except Exception as e:
            logger.error(f"Failed to process unique vulnerability: {e}")

        return True

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
            # Read crash input file contents and encode as base64
            with open(crash.crash_input_path, "rb") as f:
                crash_data = base64.b64encode(f.read()).decode()

            # Create submission payload from crash data
            submission = TypesVulnSubmission(
                architecture=ARCHITECTURE,
                data_file=crash_data,
                harness_name=crash.harness_name,
                sanitizer=crash.target.sanitizer,
                sarif=None,  # Optional, not provided in crash data
            )

            # Submit vulnerability and get response
            response = self.competition_vulnerability_api.v1_task_task_id_vuln_post(
                task_id=crash.target.task_id,
                payload=submission,
            )

            # Check submission status before proceeding
            # Currently allowing both ACCEPTED and PASSED submissions to continue,
            # as we don't know if the competition API can return PASSED immediately on submission.
            # If we don't acknowledge the PASSED status, we may miss a successful submission.
            if response.status not in [TypesSubmissionStatus.ACCEPTED, TypesSubmissionStatus.PASSED]:
                logger.error(
                    f"Vulnerability submission not accepted. Status: {response.status}\n"
                    f"Task ID: {crash.target.task_id}\n"
                    f"Package: {crash.target.package_name}"
                )
                return None

            # TODO: Could a successful response be PASSED?

            logger.info(
                f"Vulnerability submission accepted. Status: {response.status}\n"
                f"Task ID: {crash.target.task_id}\n"
                f"Package: {crash.target.package_name}\n"
                f"Vulnerability ID: {response.vuln_id}"
            )

            # Create confirmed vulnerability with API-provided ID
            confirmed_vuln = ConfirmedVulnerability()
            confirmed_vuln.crash.CopyFrom(crash)
            confirmed_vuln.vuln_id = response.vuln_id

            return confirmed_vuln

        except Exception as e:
            logger.error(
                f"Failed to submit vulnerability to competition API: {str(e)}\n"
                f"Task ID: {crash.target.task_id}\n"
                f"Package: {crash.target.package_name}\n"
                f"Crash details: {crash}"
            )
            raise
