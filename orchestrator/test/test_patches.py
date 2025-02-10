import pytest
from unittest.mock import Mock, patch
from buttercup.orchestrator.scheduler.patches import Patches
from buttercup.common.queues import RQItem, QueueFactory
from buttercup.common.datastructures.msg_pb2 import Patch
from buttercup.orchestrator.competition_api_client.models.types_patch_submission_response import (
    TypesPatchSubmissionResponse,
)
from buttercup.orchestrator.competition_api_client.models.types_submission_status import TypesSubmissionStatus


@pytest.fixture
def mock_redis():
    return Mock()


@pytest.fixture
def mock_api_client():
    return Mock()


@pytest.fixture
def mock_queues():
    patches_queue = Mock()

    # Mock QueueFactory
    queue_factory = Mock(spec=QueueFactory)
    queue_factory.create.return_value = patches_queue

    # Create a patch for QueueFactory
    with patch("buttercup.orchestrator.scheduler.patches.QueueFactory", return_value=queue_factory):
        yield {
            "factory": queue_factory,
            "patches": patches_queue,
        }


@pytest.fixture
def sample_patch():
    patch = Patch()
    patch.task_id = "test-task-123"
    patch.vulnerability_id = "test-vuln-456"
    patch.patch = "test patch content"
    return patch


@pytest.fixture
def patches(mock_redis, mock_api_client, mock_queues):
    # Create Patches instance with mocked dependencies
    patches = Patches(redis=mock_redis, api_client=mock_api_client)

    # Manually set the queue to match our mock
    patches.patches_queue = mock_queues["patches"]

    # Mock the vulnerability API method we use
    patches.vulnerability_api.v1_task_task_id_vuln_vuln_id_patch_post = Mock()

    return patches


class TestSubmitPatch:
    def test_successful_submission(self, patches, sample_patch):
        # Mock successful API response
        mock_response = TypesPatchSubmissionResponse(
            status=TypesSubmissionStatus.ACCEPTED,
            patch_id="test-patch-789"
        )
        patches.vulnerability_api.v1_task_task_id_vuln_vuln_id_patch_post.return_value = mock_response

        result = patches.submit_patch(sample_patch)

        # Verify API was called with correct data
        patches.vulnerability_api.v1_task_task_id_vuln_vuln_id_patch_post.assert_called_once()
        call_args = patches.vulnerability_api.v1_task_task_id_vuln_vuln_id_patch_post.call_args
        assert call_args[1]["task_id"] == sample_patch.task_id
        assert call_args[1]["vuln_id"] == sample_patch.vulnerability_id
        assert call_args[1]["payload"].patch == sample_patch.patch
        assert call_args[1]["payload"].vuln_id == sample_patch.vulnerability_id

        # Verify returned response
        assert result == mock_response

    def test_api_error_raises_exception(self, patches, sample_patch):
        # Mock API error
        patches.vulnerability_api.v1_task_task_id_vuln_vuln_id_patch_post.side_effect = Exception("API Error")

        with pytest.raises(Exception) as exc_info:
            patches.submit_patch(sample_patch)
        assert "API Error" in str(exc_info.value)


class TestProcessPatches:
    def test_no_patches_returns_false(self, patches, mock_queues):
        mock_queues["patches"].pop.return_value = None
        assert patches.process_patches() is False
        mock_queues["patches"].pop.assert_called_once()

    def test_accepted_patch_processes_successfully(self, patches, mock_queues, sample_patch):
        # Setup mock item and response
        mock_item = RQItem(item_id="test_id", deserialized=sample_patch)
        mock_queues["patches"].pop.return_value = mock_item

        mock_response = TypesPatchSubmissionResponse(
            status=TypesSubmissionStatus.ACCEPTED,
            patch_id="test-patch-789"
        )
        patches.vulnerability_api.v1_task_task_id_vuln_vuln_id_patch_post.return_value = mock_response

        assert patches.process_patches() is True
        mock_queues["patches"].pop.assert_called_once()
        mock_queues["patches"].ack_item.assert_called_once_with("test_id")

    def test_rejected_patch_is_acknowledged(self, patches, mock_queues, sample_patch):
        # Setup mock item and rejected response
        mock_item = RQItem(item_id="test_id", deserialized=sample_patch)
        mock_queues["patches"].pop.return_value = mock_item

        mock_response = TypesPatchSubmissionResponse(
            status=TypesSubmissionStatus.INVALID,
            patch_id="rejected-789"
        )
        patches.vulnerability_api.v1_task_task_id_vuln_vuln_id_patch_post.return_value = mock_response

        assert patches.process_patches() is True
        mock_queues["patches"].pop.assert_called_once()
        mock_queues["patches"].ack_item.assert_called_once_with("test_id")

    def test_api_error_is_handled_gracefully(self, patches, mock_queues, sample_patch):
        # Setup mock item and API error
        mock_item = RQItem(item_id="test_id", deserialized=sample_patch)
        mock_queues["patches"].pop.return_value = mock_item

        patches.vulnerability_api.v1_task_task_id_vuln_vuln_id_patch_post.side_effect = Exception("API Error")

        assert patches.process_patches() is True
        mock_queues["patches"].pop.assert_called_once()
        mock_queues["patches"].ack_item.assert_not_called()

    def test_passed_patch_processes_successfully(self, patches, mock_queues, sample_patch):
        # Setup mock item and PASSED response
        mock_item = RQItem(item_id="test_id", deserialized=sample_patch)
        mock_queues["patches"].pop.return_value = mock_item

        mock_response = TypesPatchSubmissionResponse(
            status=TypesSubmissionStatus.PASSED,
            patch_id="test-patch-789"
        )
        patches.vulnerability_api.v1_task_task_id_vuln_vuln_id_patch_post.return_value = mock_response

        assert patches.process_patches() is True
        mock_queues["patches"].pop.assert_called_once()
        mock_queues["patches"].ack_item.assert_called_once_with("test_id") 