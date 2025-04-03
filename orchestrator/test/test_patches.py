import pytest
from unittest.mock import Mock
from buttercup.orchestrator.scheduler.patches import Patches
from buttercup.orchestrator.competition_api_client.api.patch_api import PatchApi
from buttercup.orchestrator.competition_api_client.api_client import ApiClient
from buttercup.orchestrator.competition_api_client.models.types_patch_submission_response import (
    TypesPatchSubmissionResponse,
)
from buttercup.orchestrator.competition_api_client.models.types_submission_status import TypesSubmissionStatus
from buttercup.orchestrator.registry import TaskRegistry
from buttercup.orchestrator.scheduler.submission_tracker import SubmissionTracker
from buttercup.common.queues import ReliableQueue, RQItem
from buttercup.common.datastructures.msg_pb2 import Patch
from redis import Redis


@pytest.fixture
def mock_redis():
    mock = Mock(spec=Redis)
    mock.set = Mock()
    mock.get = Mock()
    mock.delete = Mock()
    mock.scan_iter = Mock(return_value=[])  # Return empty list by default
    return mock


@pytest.fixture
def mock_api_client():
    return Mock(spec=ApiClient)


@pytest.fixture
def mock_patch_api():
    mock = Mock(spec=PatchApi)
    # Configure the mock to properly handle API calls
    mock.v1_task_task_id_patch_post = Mock()
    return mock


@pytest.fixture
def mock_task_registry():
    mock = Mock(spec=TaskRegistry)
    mock.should_stop_processing = Mock()
    return mock


@pytest.fixture
def mock_submission_tracker():
    mock = Mock(spec=SubmissionTracker)
    mock.map_patch_to_vulnerability = Mock()
    mock.get_pov_status = Mock()
    mock.get_pending_patch_submissions = Mock()
    return mock


@pytest.fixture
def mock_patches_queue():
    mock = Mock(spec=ReliableQueue)
    mock.pop = Mock()
    mock.ack_item = Mock()
    return mock


@pytest.fixture
def patches(
    mock_redis, mock_api_client, mock_patch_api, mock_task_registry, mock_submission_tracker, mock_patches_queue
):
    patches = Patches(
        redis=mock_redis,
        api_client=mock_api_client,
    )
    patches.patch_api = mock_patch_api
    patches.task_registry = mock_task_registry
    patches.submission_tracker = mock_submission_tracker
    patches.patches_queue = mock_patches_queue
    return patches


def test_submit_patch_success(patches, mock_patch_api, mock_submission_tracker):
    # Arrange
    patch = Patch(task_id="test_task", vulnerability_id="test_vuln", patch="test_patch")
    expected_response = TypesPatchSubmissionResponse(
        patch_id="test_patch_id",
        status=TypesSubmissionStatus.ACCEPTED,
    )
    mock_patch_api.v1_task_task_id_patch_post.return_value = expected_response

    # Act
    response = patches.submit_patch(patch)

    # Assert
    assert response == expected_response
    mock_patch_api.v1_task_task_id_patch_post.assert_called_once()
    mock_submission_tracker.map_patch_to_vulnerability.assert_called_once_with(
        "test_task", "test_patch_id", "test_vuln"
    )
    mock_submission_tracker.update_patch_status.assert_called_once_with(
        "test_task", "test_patch_id", TypesSubmissionStatus.ACCEPTED
    )


def test_submit_patch_not_accepted(patches, mock_patch_api, mock_submission_tracker):
    # Arrange
    patch = Patch(task_id="test_task", vulnerability_id="test_vuln", patch="test_patch")
    expected_response = TypesPatchSubmissionResponse(
        patch_id="test_patch_id",
        status=TypesSubmissionStatus.FAILED,
    )
    mock_patch_api.v1_task_task_id_patch_post.return_value = expected_response

    # Act
    response = patches.submit_patch(patch)

    # Assert
    assert response == expected_response
    mock_patch_api.v1_task_task_id_patch_post.assert_called_once()
    mock_submission_tracker.map_patch_to_vulnerability.assert_not_called()
    mock_submission_tracker.update_patch_status.assert_not_called()


def test_submit_patch_failure(patches, mock_patch_api, mock_submission_tracker):
    # Arrange
    patch = Patch(task_id="test_task", vulnerability_id="test_vuln", patch="test_patch")
    mock_patch_api.v1_task_task_id_patch_post.side_effect = Exception("API Error")

    # Act & Assert
    with pytest.raises(Exception) as exc_info:
        patches.submit_patch(patch)
    assert str(exc_info.value) == "API Error"
    mock_submission_tracker.map_patch_to_vulnerability.assert_not_called()
    mock_submission_tracker.update_patch_status.assert_not_called()


def test_process_patches_empty_queue(patches):
    # Arrange
    patches.patches_queue.pop.return_value = None

    # Act
    result = patches.process_patches()

    # Assert
    assert result is False


def test_process_patches_cancelled_task(patches):
    # Arrange
    patch = Patch(task_id="test_task", vulnerability_id="test_vuln", patch="test_patch")
    patch_item = Mock(spec=RQItem)
    patch_item.deserialized = patch
    patch_item.item_id = "test_item_id"
    patches.patches_queue.pop.return_value = patch_item
    patches.task_registry.should_stop_processing.return_value = True

    # Act
    result = patches.process_patches()

    # Assert
    assert result is True
    patches.patches_queue.ack_item.assert_called_once_with(patch_item.item_id)


def test_process_patches_success(patches, mock_submission_tracker, mock_patch_api):
    # Arrange
    patch = Patch(task_id="test_task", vulnerability_id="test_vuln", patch="test_patch")
    patch_item = Mock(spec=RQItem)
    patch_item.deserialized = patch
    patch_item.item_id = "test_item_id"
    patches.patches_queue.pop.return_value = patch_item
    patches.task_registry.should_stop_processing.return_value = False
    # Mock the _is_patched method to prevent calling the original method
    patches._is_patched = Mock(return_value=False)
    mock_submission_tracker.get_pov_status.return_value = TypesSubmissionStatus.PASSED

    response = TypesPatchSubmissionResponse(
        patch_id="test_patch_id",
        status=TypesSubmissionStatus.ACCEPTED,
    )
    mock_patch_api.v1_task_task_id_patch_post.return_value = response

    # Act
    result = patches.process_patches()

    # Assert
    assert result is True
    patches._is_patched.assert_called_once_with(patch.vulnerability_id)
    mock_submission_tracker.get_pov_status.assert_called_once_with(patch.task_id, patch.vulnerability_id)
    mock_patch_api.v1_task_task_id_patch_post.assert_called_once()
    mock_submission_tracker.map_patch_to_vulnerability.assert_called_once_with(
        patch.task_id, response.patch_id, patch.vulnerability_id
    )
    patches.patches_queue.ack_item.assert_called_once_with(patch_item.item_id)


def test_process_patches_error(patches, mock_patch_api):
    # Arrange
    patch = Patch(task_id="test_task", vulnerability_id="test_vuln", patch="test_patch")
    patch_item = Mock(spec=RQItem)
    patch_item.deserialized = patch
    patch_item.item_id = "test_item_id"
    patches.patches_queue.pop.return_value = patch_item
    patches.task_registry.should_stop_processing.return_value = False
    # Mock the _is_patched method to prevent calling the original method
    patches._is_patched = Mock(return_value=False)
    mock_patch_api.v1_task_task_id_patch_post.side_effect = Exception("API Error")

    # Act
    result = patches.process_patches()

    # Assert
    assert result is True
    patches.patches_queue.ack_item.assert_not_called()


def test_store_pending_patch(patches, mock_redis):
    # Arrange
    patch = Patch(task_id="test_task", vulnerability_id="test_vuln", patch="test_patch")
    patch_data = patch.SerializeToString()
    mock_redis.set.return_value = True

    # Act
    patches.store_pending_patch(patch)

    # Assert
    mock_redis.set.assert_called_once_with(
        f"{Patches.PENDING_PATCHES_PREFIX}{patch.task_id}:{patch.vulnerability_id}", patch_data
    )


def test_get_pending_patches(patches, mock_redis):
    # Arrange
    patch = Patch(task_id="test_task", vulnerability_id="test_vuln", patch="test_patch")
    patch_data = patch.SerializeToString()
    mock_redis.scan_iter.return_value = [f"{Patches.PENDING_PATCHES_PREFIX}{patch.task_id}:{patch.vulnerability_id}"]
    mock_redis.get.return_value = patch_data

    # Act
    pending_patches = patches.get_pending_patches()

    # Assert
    assert len(pending_patches) == 1
    assert pending_patches[0].task_id == patch.task_id
    assert pending_patches[0].vulnerability_id == patch.vulnerability_id
    assert pending_patches[0].patch == patch.patch


def test_remove_pending_patch(patches, mock_redis):
    # Arrange
    task_id = "test_task"
    vulnerability_id = "test_vuln"
    mock_redis.delete.return_value = True

    # Act
    patches.remove_pending_patch(task_id, vulnerability_id)

    # Assert
    mock_redis.delete.assert_called_once_with(f"{Patches.PENDING_PATCHES_PREFIX}{task_id}:{vulnerability_id}")


def test_process_pending_patches_vuln_passed(patches, mock_submission_tracker, mock_patch_api):
    # Arrange
    patch = Patch(task_id="test_task", vulnerability_id="test_vuln", patch="test_patch")
    patches.get_pending_patches = Mock(return_value=[patch])
    patches.task_registry.should_stop_processing.return_value = False
    mock_submission_tracker.get_pov_status.return_value = TypesSubmissionStatus.PASSED
    patches.remove_pending_patch = Mock()

    response = TypesPatchSubmissionResponse(
        patch_id="test_patch_id",
        status=TypesSubmissionStatus.ACCEPTED,
    )
    mock_patch_api.v1_task_task_id_patch_post.return_value = response

    # Act
    result = patches.process_pending_patches()

    # Assert
    assert result is True
    mock_submission_tracker.get_pov_status.assert_called_once_with(patch.task_id, patch.vulnerability_id)
    mock_patch_api.v1_task_task_id_patch_post.assert_called_once()
    patches.remove_pending_patch.assert_called_once_with(patch.task_id, patch.vulnerability_id)


def test_process_pending_patches_vuln_accepted(patches, mock_submission_tracker):
    # Arrange
    patch = Patch(task_id="test_task", vulnerability_id="test_vuln", patch="test_patch")
    patches.get_pending_patches = Mock(return_value=[patch])
    patches.task_registry.should_stop_processing.return_value = False
    mock_submission_tracker.get_pov_status.return_value = TypesSubmissionStatus.ACCEPTED
    patches.remove_pending_patch = Mock()

    # Act
    result = patches.process_pending_patches()

    # Assert
    assert result is False
    mock_submission_tracker.get_pov_status.assert_called_once_with(patch.task_id, patch.vulnerability_id)
    patches.remove_pending_patch.assert_not_called()


def test_process_pending_patches_vuln_failed(patches, mock_submission_tracker):
    # Arrange
    patch = Patch(task_id="test_task", vulnerability_id="test_vuln", patch="test_patch")
    patches.get_pending_patches = Mock(return_value=[patch])
    patches.task_registry.should_stop_processing.return_value = False
    mock_submission_tracker.get_pov_status.return_value = TypesSubmissionStatus.FAILED
    patches.remove_pending_patch = Mock()

    # Act
    result = patches.process_pending_patches()

    # Assert
    assert result is True
    mock_submission_tracker.get_pov_status.assert_called_once_with(patch.task_id, patch.vulnerability_id)
    patches.remove_pending_patch.assert_called_once_with(patch.task_id, patch.vulnerability_id)


class TestCheckPendingStatuses:
    def test_check_pending_statuses_no_pending(self, patches, mock_submission_tracker):
        # Setup
        mock_submission_tracker.get_pending_patch_submissions.return_value = []

        # Execute
        result = patches.check_pending_statuses()

        # Verify
        assert result is False
        mock_submission_tracker.get_pending_patch_submissions.assert_called_once()
        patches.patch_api.v1_task_task_id_patch_patch_id_get.assert_not_called()

    def test_check_pending_statuses_success(self, patches, mock_submission_tracker):
        # Setup
        task_id = "test_task"
        patch_id = "test_patch"
        mock_submission_tracker.get_pending_patch_submissions.return_value = [(task_id, patch_id)]
        mock_response = TypesPatchSubmissionResponse(status=TypesSubmissionStatus.PASSED, patch_id=patch_id)
        patches.patch_api.v1_task_task_id_patch_patch_id_get.return_value = mock_response

        # Execute
        result = patches.check_pending_statuses()

        # Verify
        assert result is True
        mock_submission_tracker.get_pending_patch_submissions.assert_called_once()
        patches.patch_api.v1_task_task_id_patch_patch_id_get.assert_called_once_with(task_id=task_id, patch_id=patch_id)
        mock_submission_tracker.update_patch_status.assert_called_once_with(
            task_id, patch_id, TypesSubmissionStatus.PASSED
        )

    def test_check_pending_statuses_api_error(self, patches, mock_submission_tracker):
        # Setup
        task_id = "test_task"
        patch_id = "test_patch"
        mock_submission_tracker.get_pending_patch_submissions.return_value = [(task_id, patch_id)]
        patches.patch_api.v1_task_task_id_patch_patch_id_get.side_effect = Exception("API Error")

        # Execute
        result = patches.check_pending_statuses()

        # Verify
        assert result is False
        mock_submission_tracker.get_pending_patch_submissions.assert_called_once()
        patches.patch_api.v1_task_task_id_patch_patch_id_get.assert_called_once_with(task_id=task_id, patch_id=patch_id)
        mock_submission_tracker.update_patch_status.assert_not_called()

    def test_check_pending_statuses_accepted_status(self, patches, mock_submission_tracker):
        # Setup
        task_id = "test_task"
        patch_id = "test_patch"
        mock_submission_tracker.get_pending_patch_submissions.return_value = [(task_id, patch_id)]
        mock_response = TypesPatchSubmissionResponse(status=TypesSubmissionStatus.ACCEPTED, patch_id=patch_id)
        patches.patch_api.v1_task_task_id_patch_patch_id_get.return_value = mock_response

        # Execute
        result = patches.check_pending_statuses()

        # Verify
        assert result is True
        mock_submission_tracker.get_pending_patch_submissions.assert_called_once()
        patches.patch_api.v1_task_task_id_patch_patch_id_get.assert_called_once_with(task_id=task_id, patch_id=patch_id)
        mock_submission_tracker.update_patch_status.assert_not_called()


def test_process_patches_duplicate_with_passed_vuln(patches, mock_submission_tracker, mock_patch_api):
    """Test that a patch isn't processed twice when vulnerability status is PASSED."""
    # Arrange
    patch = Patch(task_id="test_task", vulnerability_id="test_vuln", patch="test_patch")
    patch_item = Mock(spec=RQItem)
    patch_item.deserialized = patch
    patch_item.item_id = "test_item_id"
    patches.patches_queue.pop.return_value = patch_item
    patches.task_registry.should_stop_processing.return_value = False
    # Mock _is_patched to return True (indicating patch was already processed)
    patches._is_patched = Mock(return_value=True)
    mock_submission_tracker.get_pov_status.return_value = TypesSubmissionStatus.PASSED

    # Act
    result = patches.process_patches()

    # Assert
    assert result is True
    patches._is_patched.assert_called_once_with(patch.vulnerability_id)
    # Since we already handled this vulnerability, we shouldn't submit the patch again
    mock_patch_api.v1_task_task_id_patch_post.assert_not_called()
    # The patch item should be acknowledged
    patches.patches_queue.ack_item.assert_called_once_with(patch_item.item_id)


def test_process_patches_duplicate_with_accepted_vuln(patches, mock_submission_tracker):
    """Test that a patch isn't processed twice when vulnerability status is ACCEPTED."""
    # Arrange
    patch = Patch(task_id="test_task", vulnerability_id="test_vuln", patch="test_patch")
    patch_item = Mock(spec=RQItem)
    patch_item.deserialized = patch
    patch_item.item_id = "test_item_id"
    patches.patches_queue.pop.return_value = patch_item
    patches.task_registry.should_stop_processing.return_value = False
    # Mock _is_patched to return True (indicating patch was already processed)
    patches._is_patched = Mock(return_value=True)
    # Mock store_pending_patch to ensure we can assert it's not called
    patches.store_pending_patch = Mock()
    mock_submission_tracker.get_pov_status.return_value = TypesSubmissionStatus.ACCEPTED

    # Act
    result = patches.process_patches()

    # Assert
    assert result is True
    patches._is_patched.assert_called_once_with(patch.vulnerability_id)
    # Since we already handled this vulnerability, we shouldn't store the patch
    patches.store_pending_patch.assert_not_called()
    # The patch item should be acknowledged
    patches.patches_queue.ack_item.assert_called_once_with(patch_item.item_id)
