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
from buttercup.common.datastructures.msg_pb2 import Patch
from buttercup.orchestrator.competition_api_client.api.vulnerability_api import VulnerabilityApi
from buttercup.orchestrator.competition_api_client.configuration import Configuration
from buttercup.orchestrator.competition_api_client.api_client import ApiClient
from buttercup.orchestrator.competition_api_client.models.types_patch_submission import TypesPatchSubmission
from buttercup.orchestrator.competition_api_client.models.types_patch_submission_response import TypesPatchSubmissionResponse
from buttercup.orchestrator.competition_api_client.models.types_submission_status import TypesSubmissionStatus

logger = logging.getLogger(__name__)

@dataclass
class Patches:
    redis: Redis
    competition_api_url: str
    patches_queue: ReliableQueue = field(init=False)
    competition_vulnerability_api: VulnerabilityApi = field(init=False)

    def __setup_vulnerability_api(self) -> VulnerabilityApi:
        """Initialize the competition vulnerability API client."""
        configuration = Configuration(
            host=self.competition_api_url,
            username="api_key_id",  # TODO: Make configurable
            password="api_key_token",  # TODO: Make configurable
        )
        logger.info(f"Init API: {self.competition_api_url}")
        api_client = ApiClient(configuration=configuration)
        return VulnerabilityApi(api_client=api_client)

    def __post_init__(self):
        queue_factory = QueueFactory(self.redis)
        self.patches_queue = queue_factory.create(
            QueueNames.PATCHES, GroupNames.PATCHES, block_time=None
        )
        self.competition_vulnerability_api = self.__setup_vulnerability_api()

    def submit_patch(self, patch: Patch) -> TypesPatchSubmissionResponse:
        """
        Submit a patch to the competition API

        Args:
            patch: The patch to submit

        Returns:
            TypesPatchSubmissionResponse: The API response

        Raises:
            Exception: If there is an error communicating with the API
        """
        logger.info(f"Submit patch: task={patch.task_id} vuln={patch.vulnerability_id}")
        submission = TypesPatchSubmission(
            patch=patch.patch,
        )

        return self.competition_vulnerability_api.v1_task_task_id_vuln_vuln_id_patch_post(
            task_id=patch.task_id,
            vuln_id=patch.vulnerability_id,
            payload=submission,
        )

    def process_patches(self) -> bool:
        """Process patches from the patches queue.
        
        Returns:
            bool: True if a patch was processed (even if submission failed), False if queue was empty
        """
        patch_item: RQItem[Patch] | None = self.patches_queue.pop()
        
        if patch_item is None:
            return False

        patch: Patch = patch_item.deserialized
        try:
            response = self.submit_patch(patch)
            
            if response.status not in [TypesSubmissionStatus.ACCEPTED, TypesSubmissionStatus.PASSED]:
                logger.error(f"Patch rejected: task={patch.task_id} vuln={patch.vulnerability_id} status={response.status}")
            else:
                logger.info(f"Patch accepted: task={patch.task_id} vuln={patch.vulnerability_id} patch_id={response.patch_id} status={response.status}")
            
            # Acknowledge the patch since it was processed, regardless of acceptance
            self.patches_queue.ack_item(patch_item.item_id)

        except Exception as e:
            # Only leave patch unacknowledged if we had an error submitting it
            logger.error(f"Submit error: task={patch.task_id} vuln={patch.vulnerability_id} error={e}")

        return True 