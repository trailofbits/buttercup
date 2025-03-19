import pytest
from unittest.mock import Mock, patch
from buttercup.orchestrator.scheduler.patches import Patches
from buttercup.common.queues import RQItem, QueueFactory
from buttercup.common.datastructures.msg_pb2 import Patch
from buttercup.orchestrator.competition_api_client.models.types_patch_submission_response import (
    TypesPatchSubmissionResponse,
)
from buttercup.orchestrator.competition_api_client.models.types_submission_status import TypesSubmissionStatus
from buttercup.orchestrator.registry import TaskRegistry
import base64


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
def mock_task_registry():
    task_registry = Mock(spec=TaskRegistry)
    task_registry.is_cancelled.return_value = False
    task_registry.is_expired.return_value = False
    return task_registry


@pytest.fixture
def patches(mock_redis, mock_api_client, mock_queues, mock_task_registry):
    # Create Patches instance with mocked dependencies
    patches = Patches(redis=mock_redis, api_client=mock_api_client)

    # Manually set the queue to match our mock
    patches.patches_queue = mock_queues["patches"]

    # Set our mocked task registry
    patches.task_registry = mock_task_registry

    # Mock the patch API method we use
    patches.patch_api.v1_task_task_id_patch_post = Mock()

    return patches


class TestSubmitPatch:
    def test_successful_submission(self, patches, sample_patch):
        # Mock successful API response
        mock_response = TypesPatchSubmissionResponse(status=TypesSubmissionStatus.ACCEPTED, patch_id="test-patch-789")
        patches.patch_api.v1_task_task_id_patch_post.return_value = mock_response

        result = patches.submit_patch(sample_patch)

        # Verify API was called with correct data
        patches.patch_api.v1_task_task_id_patch_post.assert_called_once()
        call_args = patches.patch_api.v1_task_task_id_patch_post.call_args
        assert call_args[1]["task_id"] == sample_patch.task_id
        # Verify the patch content is base64 encoded
        expected_encoded_patch = base64.b64encode(sample_patch.patch.encode()).decode()
        assert call_args[1]["payload"].patch == expected_encoded_patch

        # Verify returned response
        assert result == mock_response

    def test_api_error_raises_exception(self, patches, sample_patch):
        # Mock API error
        patches.patch_api.v1_task_task_id_patch_post.side_effect = Exception("API Error")

        with pytest.raises(Exception) as exc_info:
            patches.submit_patch(sample_patch)
        assert "API Error" in str(exc_info.value)

    def test_encoding_error_raises_exception(self, patches):
        # Create a patch with non-encodable content
        bad_patch = Patch()
        bad_patch.task_id = "test-task-123"
        bad_patch.vulnerability_id = "test-vuln-456"
        # Use a valid string for the protobuf, but one that will fail base64 encoding
        bad_patch.patch = "test patch content"

        # Mock base64.b64encode to simulate the encoding failure
        with patch("base64.b64encode", side_effect=Exception("Failed to encode")):
            with pytest.raises(Exception) as exc_info:
                patches.submit_patch(bad_patch)
            assert "Failed to encode" in str(exc_info.value)


class TestProcessPatches:
    def test_no_patches_returns_false(self, patches, mock_queues):
        mock_queues["patches"].pop.return_value = None
        assert patches.process_patches() is False
        mock_queues["patches"].pop.assert_called_once()

    def test_accepted_patch_processes_successfully(self, patches, mock_queues, sample_patch):
        # Setup mock item and response
        mock_item = RQItem(item_id="test_id", deserialized=sample_patch)
        mock_queues["patches"].pop.return_value = mock_item

        mock_response = TypesPatchSubmissionResponse(status=TypesSubmissionStatus.ACCEPTED, patch_id="test-patch-789")
        patches.patch_api.v1_task_task_id_patch_post.return_value = mock_response

        assert patches.process_patches() is True
        mock_queues["patches"].pop.assert_called_once()
        mock_queues["patches"].ack_item.assert_called_once_with("test_id")

    def test_rejected_patch_is_acknowledged(self, patches, mock_queues, sample_patch):
        # Setup mock item and rejected response
        mock_item = RQItem(item_id="test_id", deserialized=sample_patch)
        mock_queues["patches"].pop.return_value = mock_item

        mock_response = TypesPatchSubmissionResponse(status=TypesSubmissionStatus.ERRORED, patch_id="rejected-789")
        patches.patch_api.v1_task_task_id_patch_post.return_value = mock_response

        assert patches.process_patches() is True
        mock_queues["patches"].pop.assert_called_once()
        mock_queues["patches"].ack_item.assert_called_once_with("test_id")

    def test_api_error_is_handled_gracefully(self, patches, mock_queues, sample_patch):
        # Setup mock item and API error
        mock_item = RQItem(item_id="test_id", deserialized=sample_patch)
        mock_queues["patches"].pop.return_value = mock_item

        patches.patch_api.v1_task_task_id_patch_post.side_effect = Exception("API Error")

        # Reset ack_item mock to clear any previous calls
        mock_queues["patches"].ack_item.reset_mock()

        assert patches.process_patches() is True
        mock_queues["patches"].pop.assert_called_once()
        # The implementation acknowledges all items now, even on exception
        mock_queues["patches"].ack_item.assert_called_once_with("test_id")

    def test_passed_patch_processes_successfully(self, patches, mock_queues, sample_patch):
        # Setup mock item and PASSED response
        mock_item = RQItem(item_id="test_id", deserialized=sample_patch)
        mock_queues["patches"].pop.return_value = mock_item

        mock_response = TypesPatchSubmissionResponse(status=TypesSubmissionStatus.PASSED, patch_id="test-patch-789")
        patches.patch_api.v1_task_task_id_patch_post.return_value = mock_response

        assert patches.process_patches() is True
        mock_queues["patches"].pop.assert_called_once()
        mock_queues["patches"].ack_item.assert_called_once_with("test_id")

    def test_cancelled_task_skips_patch_submission(self, patches, mock_queues, sample_patch, mock_task_registry):
        # Setup mock item
        mock_item = RQItem(item_id="test_id", deserialized=sample_patch)
        mock_queues["patches"].pop.return_value = mock_item

        # Configure mock_task_registry to report the task as cancelled
        mock_task_registry.should_stop_processing.return_value = True

        # Reset the mock call counters
        patches.patch_api.v1_task_task_id_patch_post.reset_mock()
        mock_queues["patches"].ack_item.reset_mock()

        assert patches.process_patches() is True

        # Verify the patch_api was NOT called (submission skipped)
        patches.patch_api.v1_task_task_id_patch_post.assert_not_called()

        # Verify the item was acknowledged
        mock_queues["patches"].ack_item.assert_called_once_with("test_id")
