import logging
from dataclasses import dataclass
from redis import Redis, RedisError
from typing import Optional, List, Tuple
from buttercup.orchestrator.competition_api_client.models.types_submission_status import TypesSubmissionStatus
import time

logger = logging.getLogger(__name__)


class SubmissionTrackerError(Exception):
    """Base exception for submission tracker errors."""

    pass


@dataclass
class SubmissionTracker:
    """Tracks the status of vulnerability PoVs and patch submissions using Redis.

    This class manages:
    - Status tracking for PoVs and patches
    - Mapping between vulnerabilities and patches
    - Bundle submission tracking
    - Pending submission management
    """

    redis: Redis

    # Redis key prefixes
    POV_STATUS_PREFIX = "pov_status:"
    PATCH_STATUS_PREFIX = "patch_status:"
    VULNERABILITY_TO_PATCH_MAPPING_PREFIX = "bundle_mapping:"
    BUNDLE_SUBMISSION_PREFIX = "bundle_submission:"

    def _get_pov_key(self, task_id: str, vulnerability_id: str) -> str:
        """Get Redis key for vulnerability PoV status."""
        return f"{self.POV_STATUS_PREFIX}{task_id}:{vulnerability_id}"

    def _get_patch_key(self, task_id: str, patch_id: str) -> str:
        """Get Redis key for patch status."""
        return f"{self.PATCH_STATUS_PREFIX}{task_id}:{patch_id}"

    def _get_vulnerability_to_patch_mapping_key(self, task_id: str, vulnerability_id: str) -> str:
        """Get Redis key for vulnerability-to-patch mapping."""
        return f"{self.VULNERABILITY_TO_PATCH_MAPPING_PREFIX}{task_id}:{vulnerability_id}"

    def _get_bundle_submission_key(self, task_id: str, vulnerability_id: str, patch_id: str) -> str:
        """Get Redis key for bundle submission tracking."""
        return f"{self.BUNDLE_SUBMISSION_PREFIX}{task_id}:{vulnerability_id}:{patch_id}"

    def update_pov_status(self, task_id: str, pov_id: str, status: TypesSubmissionStatus) -> None:
        """Update the status of a PoV submission.

        Args:
            task_id: The task ID
            pov_id: The PoV ID
            status: The new status
        """
        try:
            key = self._get_pov_key(task_id, pov_id)
            mapping = {"status": status, "last_updated": str(time.time())}
            self.redis.hset(key, mapping=mapping)
            logger.info(f"[{task_id}] Updated PoV {pov_id} status to {status}")
        except RedisError as e:
            raise SubmissionTrackerError(f"Failed to update PoV status: {e}")

    def update_patch_status(self, task_id: str, patch_id: str, status: TypesSubmissionStatus) -> None:
        """Update the status of a patch submission.

        Args:
            task_id: The task ID
            patch_id: The patch ID
            status: The new status
        """
        try:
            key = self._get_patch_key(task_id, patch_id)
            mapping = {"status": status, "last_updated": str(time.time())}
            self.redis.hset(key, mapping=mapping)
            logger.info(f"[{task_id}] Updated patch {patch_id} status to {status}")
        except RedisError as e:
            raise SubmissionTrackerError(f"Failed to update patch status: {e}")

    def get_pov_status(self, task_id: str, pov_id: str) -> Optional[TypesSubmissionStatus]:
        """Get the current status of a PoV submission.

        Args:
            task_id: The task ID
            pov_id: The PoV ID

        Returns:
            Optional[TypesSubmissionStatus]: The current status if found, None otherwise
        """
        try:
            key = self._get_pov_key(task_id, pov_id)
            data = self.redis.hgetall(key)
            # Decode bytes to string if needed
            status = data.get(b"status" if isinstance(next(iter(data), b""), bytes) else "status")
            if isinstance(status, bytes):
                status = status.decode("utf-8")
            return TypesSubmissionStatus(status) if status else None
        except RedisError as e:
            raise SubmissionTrackerError(f"Failed to get PoV status: {e}")

    def get_patch_status(self, task_id: str, patch_id: str) -> Optional[TypesSubmissionStatus]:
        """Get the current status of a patch submission.

        Args:
            task_id: The task ID
            patch_id: The patch ID

        Returns:
            Optional[TypesSubmissionStatus]: The current status if found, None otherwise
        """
        try:
            key = self._get_patch_key(task_id, patch_id)
            data = self.redis.hgetall(key)
            # Decode bytes to string if needed
            status = data.get(b"status" if isinstance(next(iter(data), b""), bytes) else "status")
            if isinstance(status, bytes):
                status = status.decode("utf-8")
            return TypesSubmissionStatus(status) if status else None
        except RedisError as e:
            raise SubmissionTrackerError(f"Failed to get patch status: {e}")

    def map_patch_to_vulnerability(self, task_id: str, patch_id: str, vuln_id: str) -> None:
        """Create a mapping between a patch and its corresponding vulnerability.

        Args:
            task_id: The task ID
            patch_id: The patch ID
            vuln_id: The vulnerability ID
        """
        try:
            key = self._get_vulnerability_to_patch_mapping_key(task_id, vuln_id)
            self.redis.set(key, patch_id)
            logger.info(f"[{task_id}] Mapped patch {patch_id} to vulnerability {vuln_id}")
        except RedisError as e:
            raise SubmissionTrackerError(f"Failed to map patch to vulnerability: {e}")

    def get_vulnerability_for_patch(self, task_id: str, patch_id: str) -> Optional[str]:
        """Get the vulnerability ID associated with a patch.

        Args:
            task_id: The task ID
            patch_id: The patch ID

        Returns:
            Optional[str]: The vulnerability ID if found, None otherwise
        """
        try:
            # Scan for the bundle mapping key that contains this patch_id
            for key in self.redis.scan_iter(f"{self.VULNERABILITY_TO_PATCH_MAPPING_PREFIX}{task_id}:*"):
                key_str = key.decode("utf-8") if isinstance(key, bytes) else key
                value = self.redis.get(key)
                if value:
                    value = value.decode("utf-8") if isinstance(value, bytes) else value
                    if value == patch_id:
                        return key_str.split(":")[-1]
            return None
        except RedisError as e:
            raise SubmissionTrackerError(f"Failed to get vulnerability for patch: {e}")

    def get_pending_pov_submissions(self) -> List[Tuple[str, str]]:
        """Get all pending PoV submissions."""
        return self.get_pending_submissions(self.POV_STATUS_PREFIX)

    def get_pending_patch_submissions(self) -> List[Tuple[str, str]]:
        """Get all pending patch submissions."""
        return self.get_pending_submissions(self.PATCH_STATUS_PREFIX)

    def get_pending_submissions(self, prefix: str) -> List[Tuple[str, str]]:
        """Get all submissions that are not in a terminal state.

        Args:
            prefix: The Redis key prefix to scan for (POV_STATUS_PREFIX or PATCH_STATUS_PREFIX)

        Returns:
            List of (task_id, submission_id) tuples for submissions that are not in a terminal state
        """
        try:
            pending_submissions = []
            for key in self.redis.scan_iter(f"{prefix}*"):
                # Decode the key from bytes to string
                key_str = key.decode("utf-8") if isinstance(key, bytes) else key
                _, task_id, submission_id = key_str.split(":", 2)
                status = (
                    self.get_pov_status(task_id, submission_id)
                    if prefix == self.POV_STATUS_PREFIX
                    else self.get_patch_status(task_id, submission_id)
                )

                if status not in [
                    TypesSubmissionStatus.PASSED,
                    TypesSubmissionStatus.FAILED,
                    TypesSubmissionStatus.DEADLINE_EXCEEDED,
                    TypesSubmissionStatus.ERRORED,
                ]:
                    pending_submissions.append((task_id, submission_id))
            return pending_submissions
        except RedisError as e:
            raise SubmissionTrackerError(f"Failed to get pending submissions: {e}")

    def mark_bundle_submitted(self, task_id: str, vulnerability_id: str, patch_id: str) -> None:
        """Mark a bundle as submitted to prevent duplicate submissions.

        Args:
            task_id: The task ID
            vulnerability_id: The vulnerability ID
            patch_id: The patch ID
        """
        try:
            key = self._get_bundle_submission_key(task_id, vulnerability_id, patch_id)
            self.redis.set(key, "submitted")
            logger.info(
                f"[{task_id}] Marked bundle for vulnerability {vulnerability_id} and patch {patch_id} as submitted"
            )
        except RedisError as e:
            raise SubmissionTrackerError(f"Failed to mark bundle as submitted: {e}")

    def is_bundle_submitted(self, task_id: str, vulnerability_id: str, patch_id: str) -> bool:
        """Check if a bundle has been submitted.

        Args:
            task_id: The task ID
            vulnerability_id: The vulnerability ID
            patch_id: The patch ID

        Returns:
            bool: True if the bundle has been submitted, False otherwise
        """
        try:
            key = self._get_bundle_submission_key(task_id, vulnerability_id, patch_id)
            return self.redis.exists(key) == 1
        except RedisError as e:
            raise SubmissionTrackerError(f"Failed to check bundle submission status: {e}")

    def get_ready_vulnerability_patch_bundles(self) -> List[Tuple[str, str, str]]:
        """Get all vulnerability-patch pairs that are ready to be bundled.

        Returns:
            List of (task_id, vulnerability_id, patch_id) tuples for submissions
            that have both passed testing and haven't been submitted as bundles yet.
        """
        try:
            ready_bundles = []
            for key in self.redis.scan_iter(f"{self.PATCH_STATUS_PREFIX}*"):
                # Decode the key from bytes to string
                key_str = key.decode("utf-8") if isinstance(key, bytes) else key
                _, task_id, patch_id = key_str.split(":", 2)

                # Get patch status
                patch_status = self.get_patch_status(task_id, patch_id)
                if patch_status != TypesSubmissionStatus.PASSED:
                    continue

                # Get corresponding vulnerability
                vuln_id = self.get_vulnerability_for_patch(task_id, patch_id)
                if not vuln_id:
                    continue

                # No need to check vulnerability status as we already know it passed once the patch passed

                # Skip if bundle has already been submitted
                if self.is_bundle_submitted(task_id, vuln_id, patch_id):
                    continue

                ready_bundles.append((task_id, vuln_id, patch_id))
            return ready_bundles
        except RedisError as e:
            raise SubmissionTrackerError(f"Failed to get ready bundles: {e}")
