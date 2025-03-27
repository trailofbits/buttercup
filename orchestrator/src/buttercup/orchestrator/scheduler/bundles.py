import logging
from dataclasses import dataclass, field
from redis import Redis
from buttercup.orchestrator.competition_api_client.api.bundle_api import BundleApi
from buttercup.orchestrator.competition_api_client.api_client import ApiClient
from buttercup.orchestrator.competition_api_client.models.types_bundle_submission import TypesBundleSubmission
from buttercup.orchestrator.competition_api_client.models.types_bundle_submission_response import (
    TypesBundleSubmissionResponse,
)
from buttercup.orchestrator.competition_api_client.models.types_submission_status import TypesSubmissionStatus
from buttercup.orchestrator.registry import TaskRegistry
from buttercup.orchestrator.scheduler.submission_tracker import SubmissionTracker

logger = logging.getLogger(__name__)


@dataclass
class Bundles:
    """Manages bundle submissions for vulnerability-patch pairs.

    A bundle represents a validated vulnerability (PoV) and its corresponding patch.
    This class handles submitting bundles to the competition API and tracking their status.
    """

    redis: Redis
    api_client: ApiClient
    bundle_api: BundleApi = field(init=False)
    task_registry: TaskRegistry = field(init=False)
    submission_tracker: SubmissionTracker = field(init=False)

    # Optional arguments with defaults
    def __post_init__(self):
        self.bundle_api = BundleApi(api_client=self.api_client)
        self.task_registry = TaskRegistry(self.redis)
        self.submission_tracker = SubmissionTracker(self.redis)

    def submit_bundle(
        self, task_id: str, vulnerability_id: str, patch_id: str, description: str | None = None
    ) -> TypesBundleSubmissionResponse | None:
        """Submit a bundle to the competition API.

        Args:
            task_id: The ID of the task
            vulnerability_id: The ID of the vulnerability (PoV)
            patch_id: The ID of the patch
            description: Optional description of the bundle

        Returns:
            TypesBundleSubmissionResponse | None: The full response if submission was accepted, None otherwise
        """
        logger.info(f"[{task_id}] Submitting bundle for vulnerability {vulnerability_id} and patch {patch_id}")

        # Create submission payload from bundle data
        submission = TypesBundleSubmission(
            pov_id=vulnerability_id,
            patch_id=patch_id,
            description=description,
        )

        # Submit bundle and get response
        response = self.bundle_api.v1_task_task_id_bundle_post(
            task_id=task_id,
            payload=submission,
        )

        # Mark the bundle as submitted if it was accepted
        if response.status in [TypesSubmissionStatus.ACCEPTED, TypesSubmissionStatus.PASSED]:
            self.submission_tracker.mark_bundle_submitted(task_id, vulnerability_id, patch_id)
            return response

        return None

    def process_bundles(self) -> bool:
        """Process bundles that are ready for submission.

        This method:
        1. Gets all vulnerability-patch pairs that have both passed testing
        2. For each ready pair:
           - Checks if the task is cancelled or expired
           - If not cancelled/expired, submits the bundle
           - Marks successful submissions to prevent duplicates
        3. Returns True if any bundles were processed, False otherwise

        Returns:
            bool: True if any bundles were processed, False if no bundles were ready
        """

        # Get all ready bundles that haven't been submitted yet
        ready_bundles = self.submission_tracker.get_ready_vulnerability_patch_bundles()

        if not ready_bundles:
            return False

        processed = False
        for task_id, vulnerability_id, patch_id in ready_bundles:
            try:
                # Check if task is cancelled or expired
                if self.task_registry.should_stop_processing(task_id):
                    logger.info(
                        f"[{task_id}] Skipping bundle processing for vulnerability {vulnerability_id} and patch {patch_id} - task cancelled or expired"
                    )
                    continue

                # Submit the bundle
                bundle_id = self.submit_bundle(task_id, vulnerability_id, patch_id)

                if bundle_id is None:
                    logger.error(f"Bundle rejected: task={task_id} vuln={vulnerability_id} patch={patch_id}")
                else:
                    # For the initial round there is no point in following up the bundle once submitted as
                    # we don't have any logic to resubmit bundles or tie SARIFs to them.
                    logger.info(
                        f"Bundle accepted: task={task_id} vuln={vulnerability_id} patch={patch_id} bundle_id={bundle_id}"
                    )
                    processed = True

            except Exception as e:
                logger.error(f"Submit error: task={task_id} vuln={vulnerability_id} patch={patch_id} error={e}")
                # If there is an exception, we want to slow down the submission rate
                processed = False

        return processed
