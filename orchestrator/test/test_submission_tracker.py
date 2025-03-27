import pytest
from unittest.mock import Mock
from buttercup.orchestrator.scheduler.submission_tracker import SubmissionTracker
from buttercup.orchestrator.competition_api_client.models.types_submission_status import TypesSubmissionStatus


@pytest.fixture
def mock_redis():
    return Mock()


@pytest.fixture
def submission_tracker(mock_redis):
    return SubmissionTracker(redis=mock_redis)


class TestSubmissionTracker:
    def test_update_pov_status(self, submission_tracker, mock_redis):
        task_id = "test-task-123"
        pov_id = "test-pov-456"
        status = TypesSubmissionStatus.PASSED

        submission_tracker.update_pov_status(task_id, pov_id, status)

        # Verify Redis was called with correct key and data
        mock_redis.hset.assert_called_once()
        call_args = mock_redis.hset.call_args
        assert call_args[0][0] == f"{SubmissionTracker.POV_STATUS_PREFIX}{task_id}:{pov_id}"
        assert call_args[1]["mapping"]["status"] == status
        assert "last_updated" in call_args[1]["mapping"]

    def test_update_patch_status(self, submission_tracker, mock_redis):
        task_id = "test-task-123"
        patch_id = "test-patch-456"
        status = TypesSubmissionStatus.PASSED

        submission_tracker.update_patch_status(task_id, patch_id, status)

        # Verify Redis was called with correct key and data
        mock_redis.hset.assert_called_once()
        call_args = mock_redis.hset.call_args
        assert call_args[0][0] == f"{SubmissionTracker.PATCH_STATUS_PREFIX}{task_id}:{patch_id}"
        assert call_args[1]["mapping"]["status"] == status
        assert "last_updated" in call_args[1]["mapping"]

    def test_get_pov_status_exists(self, submission_tracker, mock_redis):
        task_id = "test-task-123"
        pov_id = "test-pov-456"
        mock_redis.hgetall.return_value = {"status": TypesSubmissionStatus.PASSED}

        status = submission_tracker.get_pov_status(task_id, pov_id)

        # Verify Redis was called with correct key
        mock_redis.hgetall.assert_called_once_with(f"{SubmissionTracker.POV_STATUS_PREFIX}{task_id}:{pov_id}")
        assert status == TypesSubmissionStatus.PASSED

    def test_get_pov_status_not_exists(self, submission_tracker, mock_redis):
        task_id = "test-task-123"
        pov_id = "test-pov-456"
        mock_redis.hgetall.return_value = {}

        status = submission_tracker.get_pov_status(task_id, pov_id)

        # Verify Redis was called with correct key
        mock_redis.hgetall.assert_called_once_with(f"{SubmissionTracker.POV_STATUS_PREFIX}{task_id}:{pov_id}")
        assert status is None

    def test_get_patch_status_exists(self, submission_tracker, mock_redis):
        task_id = "test-task-123"
        patch_id = "test-patch-456"
        mock_redis.hgetall.return_value = {"status": TypesSubmissionStatus.PASSED}

        status = submission_tracker.get_patch_status(task_id, patch_id)

        # Verify Redis was called with correct key
        mock_redis.hgetall.assert_called_once_with(f"{SubmissionTracker.PATCH_STATUS_PREFIX}{task_id}:{patch_id}")
        assert status == TypesSubmissionStatus.PASSED

    def test_get_patch_status_not_exists(self, submission_tracker, mock_redis):
        task_id = "test-task-123"
        patch_id = "test-patch-456"
        mock_redis.hgetall.return_value = {}

        status = submission_tracker.get_patch_status(task_id, patch_id)

        # Verify Redis was called with correct key
        mock_redis.hgetall.assert_called_once_with(f"{SubmissionTracker.PATCH_STATUS_PREFIX}{task_id}:{patch_id}")
        assert status is None

    def test_mark_bundle_submitted(self, submission_tracker, mock_redis):
        task_id = "test-task-123"
        vuln_id = "test-vuln-456"
        patch_id = "test-patch-789"

        submission_tracker.mark_bundle_submitted(task_id, vuln_id, patch_id)

        # Verify Redis was called with correct key and value
        mock_redis.set.assert_called_once_with(
            f"{SubmissionTracker.BUNDLE_SUBMISSION_PREFIX}{task_id}:{vuln_id}:{patch_id}", "submitted"
        )

    def test_is_bundle_submitted_exists(self, submission_tracker, mock_redis):
        task_id = "test-task-123"
        vuln_id = "test-vuln-456"
        patch_id = "test-patch-789"
        mock_redis.exists.return_value = 1

        result = submission_tracker.is_bundle_submitted(task_id, vuln_id, patch_id)

        # Verify Redis was called with correct key
        mock_redis.exists.assert_called_once_with(
            f"{SubmissionTracker.BUNDLE_SUBMISSION_PREFIX}{task_id}:{vuln_id}:{patch_id}"
        )
        assert result is True

    def test_is_bundle_submitted_not_exists(self, submission_tracker, mock_redis):
        task_id = "test-task-123"
        vuln_id = "test-vuln-456"
        patch_id = "test-patch-789"
        mock_redis.exists.return_value = 0

        result = submission_tracker.is_bundle_submitted(task_id, vuln_id, patch_id)

        # Verify Redis was called with correct key
        mock_redis.exists.assert_called_once_with(
            f"{SubmissionTracker.BUNDLE_SUBMISSION_PREFIX}{task_id}:{vuln_id}:{patch_id}"
        )
        assert result is False

    def test_get_ready_vulnerability_patch_bundles_excludes_submitted(self, submission_tracker, mock_redis):
        task_id = "test-task-123"
        patch_id = "test-patch-456"
        vuln_id = "test-vuln-789"

        # Mock patch status
        mock_redis.scan_iter.side_effect = [
            # First scan for patches
            [f"{SubmissionTracker.PATCH_STATUS_PREFIX}{task_id}:{patch_id}"],
            # Second scan for vulnerability mapping
            [f"{SubmissionTracker.VULNERABILITY_TO_PATCH_MAPPING_PREFIX}{task_id}:{vuln_id}"],
        ]

        # Mock patch status check
        mock_redis.hgetall.side_effect = [
            {"status": TypesSubmissionStatus.PASSED},  # patch status
            {"status": TypesSubmissionStatus.PASSED},  # pov status
        ]

        # Mock vulnerability lookup - should return patch_id to indicate mapping exists
        mock_redis.get.return_value = patch_id

        # Mock bundle submission check
        mock_redis.exists.return_value = 1  # bundle is submitted

        result = submission_tracker.get_ready_vulnerability_patch_bundles()

        # Verify the bundle was excluded
        assert result == []
        mock_redis.exists.assert_called_once_with(
            f"{SubmissionTracker.BUNDLE_SUBMISSION_PREFIX}{task_id}:{vuln_id}:{patch_id}"
        )
