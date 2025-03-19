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
import base64

logger = logging.getLogger(__name__)


@dataclass
class Patches:
    redis: Redis
    api_client: ApiClient
    patch_api: PatchApi = field(init=False)
    task_registry: TaskRegistry = field(init=False)

    def __post_init__(self):
        queue_factory = QueueFactory(self.redis)
        self.patches_queue = queue_factory.create(QueueNames.PATCHES, GroupNames.ORCHESTRATOR, block_time=None)
        self.patch_api = PatchApi(api_client=self.api_client)
        self.task_registry = TaskRegistry(self.redis)

    def submit_patch(self, patch: Patch) -> TypesPatchSubmissionResponse:
        """Submit a patch to the competition API

        Args:
            patch: The patch to submit

        Returns:
            TypesPatchSubmissionResponse: The API response

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

            return response

        except Exception as e:
            logger.error(
                f"[{patch.task_id}] Failed to submit patch for vulnerability {patch.vulnerability_id}: {str(e)}"
            )
            raise

    def process_patches(self) -> bool:
        """Process patches from the patches queue.

        This method:
        1. Pops a patch from the patches queue
        2. Checks if the associated task is cancelled or expired
        3. If not cancelled or expired, submits the patch to the competition API
        4. Acknowledges the processed item (unless there was an error)

        Returns:
            bool: True if a patch was processed (even if submission failed), False if queue was empty
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
            else:
                # Only submit the patch if the task is not cancelled or expired
                response = self.submit_patch(patch)

                if response.status not in [TypesSubmissionStatus.ACCEPTED, TypesSubmissionStatus.PASSED]:
                    logger.error(
                        f"Patch rejected: task={patch.task_id} vuln={patch.vulnerability_id} status={response.status}"
                    )
                else:
                    logger.info(
                        f"Patch accepted: task={patch.task_id} vuln={patch.vulnerability_id} patch_id={response.patch_id} status={response.status}"
                    )

            # Acknowledge the patch since it was processed, regardless of acceptance or cancellation
            self.patches_queue.ack_item(patch_item.item_id)

        except Exception as e:
            # Only leave patch unacknowledged if we had an error submitting it
            logger.error(f"Submit error: task={patch.task_id} vuln={patch.vulnerability_id} error={e}")

        return True
