import base64
import logging
from dataclasses import dataclass, field
from redis import Redis
from buttercup.common.constants import ARCHITECTURE
from buttercup.common.queues import (
    ReliableQueue,
    QueueFactory,
    RQItem,
    QueueNames,
    GroupNames,
)
from buttercup.common.datastructures.msg_pb2 import ConfirmedVulnerability, Crash, TracedCrash
from buttercup.orchestrator.competition_api_client.api.pov_api import PovApi
from buttercup.orchestrator.competition_api_client.api_client import ApiClient
from buttercup.orchestrator.competition_api_client.models.types_pov_submission import TypesPOVSubmission
from buttercup.orchestrator.competition_api_client.models.types_submission_status import TypesSubmissionStatus
from buttercup.orchestrator.competition_api_client.models.types_pov_submission_response import (
    TypesPOVSubmissionResponse,
)
from buttercup.orchestrator.registry import TaskRegistry
from buttercup.orchestrator.scheduler.submission_tracker import SubmissionTracker

logger = logging.getLogger(__name__)


@dataclass
class Vulnerabilities:
    """Manages vulnerability (PoV) submissions and their status tracking.

    This class handles:
    - Submitting vulnerabilities (PoVs) to the competition API
    - Processing traced vulnerabilities from the queue
    - Tracking PoV submission status
    - Deduplicating crashes
    """

    # Required arguments (no defaults)
    redis: Redis
    api_client: ApiClient
    task_registry: TaskRegistry = field(init=False)
    submission_tracker: SubmissionTracker = field(init=False)
    crash_queue: ReliableQueue = field(init=False)
    unique_vulnerabilities_queue: ReliableQueue = field(init=False)
    confirmed_vulnerabilities_queue: ReliableQueue = field(init=False)
    pov_api: PovApi = field(init=False)

    def __post_init__(self):
        queue_factory = QueueFactory(self.redis)
        self.traced_vulnerabilities_queue = queue_factory.create(
            QueueNames.TRACED_VULNERABILITIES, GroupNames.ORCHESTRATOR, block_time=None
        )
        self.confirmed_vulnerabilities_queue = queue_factory.create(
            QueueNames.CONFIRMED_VULNERABILITIES, block_time=None
        )
        self.task_registry = TaskRegistry(self.redis)
        self.pov_api = PovApi(api_client=self.api_client)
        self.submission_tracker = SubmissionTracker(self.redis)
        logger.info(f"Competition Pov API initialized: {self.pov_api is not None}")

    def dedup_crash(self, crash: Crash) -> Crash | None:
        """Deduplicate crashes based on their stack trace or other characteristics.

        Args:
            crash: The crash to deduplicate

        Returns:
            Crash | None: The crash if unique, None if it's a duplicate
        """
        # TODO: Implement actual deduplication logic here
        # For now, treating all crashes as unique
        return crash

    def process_traced_vulnerabilities(self) -> bool:
        """Process traced vulnerabilities from the traced vulnerabilities queue.

        This method:
        1. Pops a traced vulnerability from the queue
        2. Checks if the task is cancelled or expired
        3. If not cancelled/expired, submits the PoV
        4. If submission is successful, pushes to confirmed vulnerabilities queue
        5. Acknowledges the processed item

        Returns:
            bool: True if a vulnerability was processed, False if queue was empty
        """

        vuln_item: RQItem[TracedCrash] | None = self.traced_vulnerabilities_queue.pop()
        if vuln_item is None:
            return False

        try:
            crash: TracedCrash = vuln_item.deserialized

            # First check if we should stop processing this task (cancelled or expired)
            if self.task_registry.should_stop_processing(crash.crash.target.task_id):
                logger.info(
                    f"[{crash.crash.target.task_id}] Skipping cancelled task for harness: {crash.crash.harness_name}"
                )
            else:
                confirmed_vuln = self.submit_pov(crash)
                if confirmed_vuln is not None:
                    self.confirmed_vulnerabilities_queue.push(confirmed_vuln)
                    logger.info(
                        f"[{crash.crash.target.task_id}] Pushed Confirmed POV {confirmed_vuln.vuln_id} for harness: {crash.crash.harness_name}"
                    )

            self.traced_vulnerabilities_queue.ack_item(vuln_item.item_id)
        except Exception as e:
            logger.error(f"[{crash.crash.target.task_id}] Failed to process traced vulnerability: {e}")

        return True

    def submit_pov(self, crash: TracedCrash) -> ConfirmedVulnerability | None:
        """Submit a PoV to the competition API.

        Args:
            crash: The traced crash containing the PoV data

        Returns:
            ConfirmedVulnerability | None: The confirmed vulnerability with API-provided ID if successful,
                                         None if submission was not accepted

        Raises:
            Exception: If there is an error communicating with the API
        """
        logger.info(f"[{crash.crash.target.task_id}] Submitting vulnerability for harness: {crash.crash.harness_name}")
        try:
            # Read crash input file contents and encode as base64
            with open(crash.crash.crash_input_path, "rb") as f:
                crash_data = base64.b64encode(f.read()).decode()

            # Create submission payload from crash data
            submission = TypesPOVSubmission(
                architecture=ARCHITECTURE,
                engine=crash.crash.target.engine,
                fuzzer_name=crash.crash.harness_name,
                sanitizer=crash.crash.target.sanitizer,
                testcase=crash_data,
            )

            # Submit Pov and get response
            response = self.pov_api.v1_task_task_id_pov_post(
                task_id=crash.crash.target.task_id,
                payload=submission,
            )

            # Check submission status before proceeding
            # Currently allowing both ACCEPTED and PASSED submissions to continue,
            # as we don't know if the competition API can return PASSED immediately on submission.
            # If we don't acknowledge the PASSED status, we may miss a successful submission.
            if response.status not in [TypesSubmissionStatus.ACCEPTED, TypesSubmissionStatus.PASSED]:
                logger.error(
                    f"[{crash.crash.target.task_id}] POV submission rejected (status: {response.status}) for harness: {crash.crash.harness_name}"
                )
                return None

            # Update the submission status in Redis
            self.submission_tracker.update_pov_status(crash.crash.target.task_id, response.pov_id, response.status)

            logger.info(
                f"[{crash.crash.target.task_id}] POV {response.pov_id} accepted for harness: {crash.crash.harness_name}"
            )

            # Create confirmed vulnerability with API-provided ID
            confirmed_vuln = ConfirmedVulnerability()
            confirmed_vuln.crash.CopyFrom(crash)
            confirmed_vuln.vuln_id = response.pov_id

            return confirmed_vuln

        except Exception as e:
            logger.error(
                f"[{crash.crash.target.task_id}] Failed to submit POV: {str(e)} (harness: {crash.crash.harness_name})"
            )
            raise

    def check_pending_statuses(self) -> bool:
        """Check status of all pending PoV submissions.

        This method:
        1. Gets all pending PoV submissions
        2. Checks status for each submission
        3. Updates submission status in Redis

        Returns:
            bool: True if any work was done, False otherwise. Returns False on error to slow down submission rate.
        """
        did_work = False

        # Get all pending PoV submissions
        pending_submissions = self.submission_tracker.get_pending_pov_submissions()

        # Check status for each pending submission
        for task_id, pov_id in pending_submissions:
            try:
                self.check_pov_status(task_id, pov_id)
                did_work = True
            except Exception as e:
                logger.error(f"[{task_id}] Failed to check PoV {pov_id} status: {str(e)}")
                did_work = False  # In case of error, we want to slow down the submission rate

        return did_work

    def check_pov_status(self, task_id: str, pov_id: str) -> TypesPOVSubmissionResponse:
        """Check the status of a submitted vulnerability.

        Args:
            task_id: The task ID
            pov_id: The vulnerability ID returned from submission

        Returns:
            TypesPOVSubmissionResponse: The API response containing status
        """
        response = self.pov_api.v1_task_task_id_pov_pov_id_get(task_id=task_id, pov_id=pov_id)

        # Update status if not ACCEPTED - handles both initial PASSED/FAILED and status changes.
        # Most submissions start as ACCEPTED and later transition to PASSED/FAILED.
        if response.status != TypesSubmissionStatus.ACCEPTED:
            self.submission_tracker.update_pov_status(task_id, pov_id, response.status)

        return response
