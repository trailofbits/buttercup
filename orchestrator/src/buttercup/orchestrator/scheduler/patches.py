import logging
from dataclasses import dataclass, field
from redis import Redis
from buttercup.common.queues import (
    QueueFactory,
    RQItem,
    QueueNames,
    GroupNames,
)
from buttercup.common.datastructures.msg_pb2 import Patch
from buttercup.orchestrator.competition_api_client.api.patch_api import PatchApi
from buttercup.orchestrator.competition_api_client.api_client import ApiClient
from buttercup.orchestrator.competition_api_client.models.types_patch_submission import TypesPatchSubmission
from buttercup.orchestrator.competition_api_client.models.types_patch_submission_response import (
    TypesPatchSubmissionResponse,
)
from buttercup.orchestrator.competition_api_client.models.types_submission_status import TypesSubmissionStatus
from buttercup.orchestrator.registry import TaskRegistry
from buttercup.orchestrator.scheduler.submission_tracker import SubmissionTracker
import base64

logger = logging.getLogger(__name__)


@dataclass
class Patches:
    """Manages patch submissions and their status tracking.

    This class handles:
    - Submitting patches to the competition API
    - Storing and processing pending patches
    - Tracking patch submission status
    - Mapping patches to their corresponding vulnerabilities
    """

    redis: Redis
    api_client: ApiClient
    patch_api: PatchApi = field(init=False)
    task_registry: TaskRegistry = field(init=False)
    submission_tracker: SubmissionTracker = field(init=False)

    # Redis key prefix for pending patches
    PENDING_PATCHES_PREFIX = "pending_patches:"

    # Redis set of vulnerabilities that have seen a patch
    SEEN_PATCHES_PREFIX = "seen_patches:"

    def __post_init__(self):
        queue_factory = QueueFactory(self.redis)
        self.patches_queue = queue_factory.create(QueueNames.PATCHES, GroupNames.ORCHESTRATOR, block_time=None)
        self.patch_api = PatchApi(api_client=self.api_client)
        self.task_registry = TaskRegistry(self.redis)
        self.submission_tracker = SubmissionTracker(self.redis)

    def _get_pending_patch_key(self, task_id: str, vulnerability_id: str) -> str:
        """Get Redis key for pending patch."""
        return f"{self.PENDING_PATCHES_PREFIX}{task_id}:{vulnerability_id}"

    def _is_patched(self, vulnerability_id: str) -> bool:
        """Check if a vulnerability has seen a patch."""
        return self.redis.sismember(self.SEEN_PATCHES_PREFIX, vulnerability_id)

    def _set_patched(self, vulnerability_id: str) -> None:
        """Set a vulnerability as patched."""
        self.redis.sadd(self.SEEN_PATCHES_PREFIX, vulnerability_id)

    def store_pending_patch(self, patch: Patch) -> None:
        """Store a patch as pending until its vulnerability is ready.

        Args:
            patch: The patch to store
        """
        try:
            key = self._get_pending_patch_key(patch.task_id, patch.vulnerability_id)
            # Store the patch as a protobuf message
            patch_data = patch.SerializeToString()
            self.redis.set(key, patch_data)
            logger.info(f"[{patch.task_id}] Stored pending patch for vulnerability {patch.vulnerability_id}")
        except Exception as e:
            logger.error(f"Failed to store pending patch: {e}")
            raise

    def get_pending_patches(self) -> list[Patch]:
        """Get all pending patches.

        Returns:
            list[Patch]: List of pending patches
        """
        try:
            pending_patches = []
            for key in self.redis.scan_iter(f"{self.PENDING_PATCHES_PREFIX}*"):
                # Decode the key from bytes to string
                key_str = key.decode("utf-8") if isinstance(key, bytes) else key
                _, task_id, vulnerability_id = key_str.split(":", 2)

                # Get the patch data
                patch_data = self.redis.get(key)
                if patch_data:
                    # Parse the protobuf message
                    patch = Patch()
                    patch.ParseFromString(patch_data)
                    pending_patches.append(patch)

            return pending_patches
        except Exception as e:
            logger.error(f"Failed to get pending patches: {e}")
            raise

    def remove_pending_patch(self, task_id: str, vulnerability_id: str) -> None:
        """Remove a pending patch.

        Args:
            task_id: The task ID
            vulnerability_id: The vulnerability ID
        """
        try:
            key = self._get_pending_patch_key(task_id, vulnerability_id)
            self.redis.delete(key)
            logger.info(f"[{task_id}] Removed pending patch for vulnerability {vulnerability_id}")
        except Exception as e:
            logger.error(f"Failed to remove pending patch: {e}")
            raise

    def process_patches(self) -> bool:
        """Process patches from the patches queue.

        This method:
        1. Pops a patch from the patches queue
        2. Checks if the associated task is cancelled or expired
        3. If not cancelled or expired, checks vulnerability status:
           - If PASSED: Submit the patch
           - If ACCEPTED: Store as pending
           - If FAILED/ERRORED: Skip
        4. Acknowledges the processed item (unless there was an error)

        Returns:
            bool: True if a patch was processed (even if storage failed), False if queue was empty
        """
        patch_item: RQItem[Patch] | None = self.patches_queue.pop()

        if patch_item is None:
            return False

        patch: Patch = patch_item.deserialized
        try:
            # First check if we should stop processing this task (cancelled or expired)
            if self.task_registry.should_stop_processing(patch.task_id):
                logger.info(
                    f"[{patch.task_id}] Skipping patch processing for vulnerability {patch.vulnerability_id} - task cancelled or expired"
                )
                self.patches_queue.ack_item(patch_item.item_id)
                return True

            # Check if there's already a submitted or pending patch for this vulnerability
            if self._is_patched(patch.vulnerability_id):
                logger.info(
                    f"[{patch.task_id}] Already seen a patch for vulnerability {patch.vulnerability_id}, skipping"
                )
                self.patches_queue.ack_item(patch_item.item_id)
                return True

            # Check vulnerability status
            vuln_status = self.submission_tracker.get_pov_status(patch.task_id, patch.vulnerability_id)

            if vuln_status == TypesSubmissionStatus.PASSED:
                # Submit the patch
                response = self.submit_patch(patch)
                self._set_patched(patch.vulnerability_id)
                if response.status in [TypesSubmissionStatus.ACCEPTED, TypesSubmissionStatus.PASSED]:
                    logger.info(f"Successfully submitted patch: task={patch.task_id} vuln={patch.vulnerability_id}")
                    self.patches_queue.ack_item(patch_item.item_id)
                else:
                    logger.error(
                        f"Failed to submit patch: task={patch.task_id} vuln={patch.vulnerability_id} status={response.status}"
                    )
            elif vuln_status == TypesSubmissionStatus.ACCEPTED:
                # Store patch as pending
                self.store_pending_patch(patch)
                self._set_patched(patch.vulnerability_id)
                logger.info(f"[{patch.task_id}] Stored patch as pending for vulnerability {patch.vulnerability_id}")
                self.patches_queue.ack_item(patch_item.item_id)
            elif vuln_status in [TypesSubmissionStatus.FAILED, TypesSubmissionStatus.ERRORED]:
                logger.error(
                    f"Vulnerability failed or errored, skipping patch: task={patch.task_id} vuln={patch.vulnerability_id}"
                )
                self.patches_queue.ack_item(patch_item.item_id)

        except Exception as e:
            # Only leave patch unacknowledged if we had an error storing it
            logger.error(f"Storage error: task={patch.task_id} vuln={patch.vulnerability_id} error={e}")
            # Don't acknowledge on error so it can be retried

        return True

    def process_pending_patches(self) -> bool:
        """Process any pending patches that are ready to be submitted.

        This method:
        1. Gets all pending patches
        2. For each patch:
           - Checks if the task is cancelled or expired
           - If not cancelled/expired, checks vulnerability status:
             - If PASSED: Submit the patch
             - If FAILED/ERRORED: Remove from pending
             - If ACCEPTED: Keep pending
           - Acknowledges the processed item (unless there was an error)

        Returns:
            bool: True if any patches were processed, False otherwise
        """
        processed = False
        pending_patches = self.get_pending_patches()

        for patch in pending_patches:
            try:
                # First check if we should stop processing this task (cancelled or expired)
                if self.task_registry.should_stop_processing(patch.task_id):
                    logger.info(
                        f"[{patch.task_id}] Skipping pending patch for vulnerability {patch.vulnerability_id} - task cancelled or expired"
                    )
                    # Remove cancelled/expired tasks from pending
                    self.remove_pending_patch(patch.task_id, patch.vulnerability_id)
                    processed = True
                    continue

                # Check vulnerability status
                vuln_status = self.submission_tracker.get_pov_status(patch.task_id, patch.vulnerability_id)

                if vuln_status == TypesSubmissionStatus.PASSED:
                    # Submit the patch
                    response = self.submit_patch(patch)

                    if response.status in [TypesSubmissionStatus.ACCEPTED, TypesSubmissionStatus.PASSED]:
                        logger.info(
                            f"Successfully submitted pending patch: task={patch.task_id} vuln={patch.vulnerability_id}"
                        )
                        # Remove from pending patches
                        self.remove_pending_patch(patch.task_id, patch.vulnerability_id)
                        processed = True
                    else:
                        logger.error(
                            f"Failed to submit pending patch: task={patch.task_id} vuln={patch.vulnerability_id} status={response.status}"
                        )
                elif vuln_status in [TypesSubmissionStatus.FAILED, TypesSubmissionStatus.ERRORED]:
                    logger.error(
                        f"Vulnerability failed or errored, removing pending patch: task={patch.task_id} vuln={patch.vulnerability_id}"
                    )
                    self.remove_pending_patch(patch.task_id, patch.vulnerability_id)
                    # TODO: Consider issuing a new patch creation request here
                    processed = True

            except Exception as e:
                logger.error(
                    f"Error processing pending patch: task={patch.task_id} vuln={patch.vulnerability_id} error={e}"
                )

        return processed

    def submit_patch(self, patch: Patch) -> TypesPatchSubmissionResponse:
        """Submit a patch to the competition API.

        Args:
            patch: The patch to submit

        Returns:
            TypesPatchSubmissionResponse: The API response containing patch_id and status

        Raises:
            Exception: If there is an error communicating with the API
        """
        logger.info(f"[{patch.task_id}] Submitting patch for vulnerability {patch.vulnerability_id}")

        try:
            # Base64 encode the patch content
            encoded_patch = base64.b64encode(patch.patch.encode()).decode()

            # Create submission payload from patch data
            submission = TypesPatchSubmission(
                patch=encoded_patch,
            )

            # Submit patch and get response
            response = self.patch_api.v1_task_task_id_patch_post(
                task_id=patch.task_id,
                payload=submission,
            )

            # Map the patch to the vulnerability and track its status
            if response.status == TypesSubmissionStatus.ACCEPTED or response.status == TypesSubmissionStatus.PASSED:
                self.submission_tracker.map_patch_to_vulnerability(
                    patch.task_id, response.patch_id, patch.vulnerability_id
                )
                self.submission_tracker.update_patch_status(patch.task_id, response.patch_id, response.status)

            return response

        except Exception as e:
            logger.error(
                f"[{patch.task_id}] Failed to submit patch for vulnerability {patch.vulnerability_id}: {str(e)}"
            )
            raise

    def check_pending_statuses(self) -> bool:
        """Check status of all pending submissions.

        This method:
        1. Processes any pending patches that are ready to be submitted
        2. Checks status of all pending patch submissions
        3. Updates submission status in Redis

        Returns:
            bool: True if any work was done, False otherwise. Returns False on error to slow down submission rate.
        """
        did_work = self.process_pending_patches()

        # Get all pending submissions
        pending_submissions = self.submission_tracker.get_pending_patch_submissions()

        # Process each pending submission
        for task_id, patch_id in pending_submissions:
            try:
                # Check submission status
                status = self.patch_api.v1_task_task_id_patch_patch_id_get(task_id=task_id, patch_id=patch_id)

                # Status is initially ACCEPTED, only log if it changes
                if status.status != TypesSubmissionStatus.ACCEPTED:
                    self.submission_tracker.update_patch_status(task_id, patch_id, status.status)

                did_work = True

            except Exception as e:
                logger.error(f"Error checking submission status for task {task_id}, submission {patch_id}: {e}")
                did_work = False  # Slow down the submission rate
                continue

        return did_work
