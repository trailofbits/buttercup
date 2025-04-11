import pytest
import uuid
from unittest.mock import Mock, patch
from buttercup.orchestrator.scheduler.vulnerabilities import Vulnerabilities
from buttercup.common.queues import RQItem, QueueFactory
from buttercup.common.datastructures.msg_pb2 import Crash, BuildOutput, TracedCrash
from buttercup.orchestrator.competition_api_client.models.types_pov_submission_response import (
    TypesPOVSubmissionResponse,
)
from buttercup.orchestrator.competition_api_client.models.types_submission_status import TypesSubmissionStatus
from buttercup.orchestrator.scheduler.submission_tracker import SubmissionTracker


@pytest.fixture
def mock_redis():
    return Mock()


@pytest.fixture
def mock_api_client():
    return Mock()


@pytest.fixture
def mock_queues():
    crash_queue = Mock()
    traced_vulnerabilities_queue = Mock()
    confirmed_vulnerabilities_queue = Mock()

    # Mock QueueFactory
    queue_factory = Mock(spec=QueueFactory)
    queue_factory.create.side_effect = [crash_queue, traced_vulnerabilities_queue, confirmed_vulnerabilities_queue]

    # Create a patch for QueueFactory
    with patch("buttercup.orchestrator.scheduler.vulnerabilities.QueueFactory", return_value=queue_factory):
        yield {
            "factory": queue_factory,
            "crash": crash_queue,
            "traced": traced_vulnerabilities_queue,
            "confirmed": confirmed_vulnerabilities_queue,
        }


@pytest.fixture
def mock_submission_tracker():
    mock = Mock(spec=SubmissionTracker)
    mock.get_pending_pov_submissions = Mock()
    mock.update_pov_status = Mock()
    return mock


@pytest.fixture
def sample_crash():
    crash = Crash()
    target = BuildOutput()
    target.sanitizer = "test_sanitizer"
    target.task_id = str(uuid.uuid4())
    crash.target.CopyFrom(target)
    crash.harness_name = "test_harness"
    crash.crash_input_path = "/test/crash/input.txt"
    annotated_crash = TracedCrash()
    annotated_crash.crash.CopyFrom(crash)
    annotated_crash.tracer_stacktrace = "test_stacktrace"
    return annotated_crash


@pytest.fixture
def vulnerabilities(mock_redis, mock_api_client, mock_queues, mock_submission_tracker):
    # Mock Redis operations for TaskRegistry
    mock_redis.hexists.return_value = False
    mock_redis.hget.return_value = None

    # Create Vulnerabilities instance with mocked dependencies
    vuln = Vulnerabilities(redis=mock_redis, api_client=mock_api_client)

    # Manually set the queues to match our mocks
    vuln.crash_queue = mock_queues["crash"]
    vuln.traced_vulnerabilities_queue = mock_queues["traced"]
    vuln.confirmed_vulnerabilities_queue = mock_queues["confirmed"]

    # Mock task_registry methods directly instead of relying on Redis
    vuln.task_registry.is_cancelled = Mock(return_value=False)
    vuln.task_registry.should_stop_processing = Mock(return_value=False)

    # Mock the vulnerability API method we use
    vuln.pov_api.v1_task_task_id_pov_post = Mock()
    vuln.pov_api.v1_task_task_id_pov_pov_id_get = Mock()

    # Set the submission tracker
    vuln.submission_tracker = mock_submission_tracker

    return vuln


class TestProcessTracedVulnerabilities:
    def test_no_vulns_returns_false(self, vulnerabilities, mock_queues):
        mock_queues["traced"].pop.return_value = None
        assert vulnerabilities.process_traced_vulnerabilities() is False
        mock_queues["traced"].pop.assert_called_once()
        mock_queues["confirmed"].push.assert_not_called()

    @patch("buttercup.common.node_local.lopen")
    @patch("buttercup.common.node_local.make_locally_available")
    def test_accepted_submission_processes_successfully(
        self, mock_make_locally, mock_lopen, vulnerabilities, mock_queues, sample_crash
    ):
        # Mock file handling
        mock_file = Mock()
        mock_file.read.return_value = b"test crash data"
        mock_lopen.return_value.__enter__.return_value = mock_file

        # Setup the queue item
        mock_item = RQItem(item_id="test_id", deserialized=sample_crash)
        mock_queues["traced"].pop.return_value = mock_item

        # Setup API response
        mock_response = TypesPOVSubmissionResponse(status=TypesSubmissionStatus.ACCEPTED, pov_id="test-pov-123")
        vulnerabilities.pov_api.v1_task_task_id_pov_post.return_value = mock_response

        # Run the method
        assert vulnerabilities.process_traced_vulnerabilities() is True

        # Verify calls
        mock_queues["traced"].pop.assert_called_once()
        mock_lopen.assert_called_once_with(sample_crash.crash.crash_input_path, "rb")
        mock_queues["confirmed"].push.assert_called_once()
        mock_queues["traced"].ack_item.assert_called_once_with("test_id")

    @patch("buttercup.common.node_local.lopen")
    @patch("buttercup.common.node_local.make_locally_available")
    def test_rejected_submission_is_handled_gracefully(
        self, mock_make_locally, mock_lopen, vulnerabilities, mock_queues, sample_crash
    ):
        # Mock file handling
        mock_file = Mock()
        mock_file.read.return_value = b"test crash data"
        mock_lopen.return_value.__enter__.return_value = mock_file

        # Setup the queue item
        mock_item = RQItem(item_id="test_id", deserialized=sample_crash)
        mock_queues["traced"].pop.return_value = mock_item

        # Setup API response for rejection
        mock_response = TypesPOVSubmissionResponse(status=TypesSubmissionStatus.ERRORED, pov_id="rejected-123")
        vulnerabilities.pov_api.v1_task_task_id_pov_post.return_value = mock_response

        # Run the method
        assert vulnerabilities.process_traced_vulnerabilities() is True

        # Verify calls
        mock_queues["traced"].pop.assert_called_once()
        mock_lopen.assert_called_once_with(sample_crash.crash.crash_input_path, "rb")
        mock_queues["confirmed"].push.assert_not_called()
        mock_queues["traced"].ack_item.assert_called_once_with("test_id")

    @patch("buttercup.common.node_local.lopen")
    @patch("buttercup.common.node_local.make_locally_available")
    def test_api_error_is_handled_gracefully(
        self, mock_make_locally, mock_lopen, vulnerabilities, mock_queues, sample_crash
    ):
        # Mock file handling
        mock_file = Mock()
        mock_file.read.return_value = b"test crash data"
        mock_lopen.return_value.__enter__.return_value = mock_file

        # Setup the queue item
        mock_item = RQItem(item_id="test_id", deserialized=sample_crash)
        mock_queues["traced"].pop.return_value = mock_item

        # Setup API exception
        vulnerabilities.pov_api.v1_task_task_id_pov_post.side_effect = Exception("API Error")

        # Run the method
        assert vulnerabilities.process_traced_vulnerabilities() is True

        # Verify calls
        mock_queues["traced"].pop.assert_called_once()
        mock_lopen.assert_called_once_with(sample_crash.crash.crash_input_path, "rb")
        mock_queues["confirmed"].push.assert_not_called()
        # When an exception occurs in submit_pov, the traced vulnerabilities queue item should not be acknowledged
        mock_queues["traced"].ack_item.assert_not_called()

    def test_cancelled_task_is_skipped(self, vulnerabilities, mock_queues, sample_crash):
        mock_item = RQItem(item_id="test_id", deserialized=sample_crash)
        mock_queues["traced"].pop.return_value = mock_item
        vulnerabilities.task_registry.should_stop_processing = Mock(return_value=True)

        assert vulnerabilities.process_traced_vulnerabilities() is True
        mock_queues["traced"].pop.assert_called_once()
        mock_queues["confirmed"].push.assert_not_called()
        mock_queues["traced"].ack_item.assert_called_once_with("test_id")
        vulnerabilities.task_registry.should_stop_processing.assert_called_once_with(sample_crash.crash.target.task_id)


class TestSubmitVulnerability:
    @patch("buttercup.common.node_local.lopen")
    @patch("buttercup.common.node_local.make_locally_available")
    def test_successful_submission(self, mock_make_locally, mock_lopen, vulnerabilities, sample_crash):
        # Mock file handling
        mock_file = Mock()
        mock_file.read.return_value = b"test crash data"
        mock_lopen.return_value.__enter__.return_value = mock_file

        # Setup API response
        mock_response = TypesPOVSubmissionResponse(status=TypesSubmissionStatus.ACCEPTED, pov_id="test-pov-123")
        vulnerabilities.pov_api.v1_task_task_id_pov_post.return_value = mock_response

        # Call the method
        result = vulnerabilities.submit_pov(sample_crash)

        # Verify file was read correctly
        mock_lopen.assert_called_once_with(sample_crash.crash.crash_input_path, "rb")

        # Verify API was called with correct data
        vulnerabilities.pov_api.v1_task_task_id_pov_post.assert_called_once()
        call_args = vulnerabilities.pov_api.v1_task_task_id_pov_post.call_args
        assert call_args[1]["task_id"] == sample_crash.crash.target.task_id
        assert call_args[1]["payload"].testcase == "dGVzdCBjcmFzaCBkYXRh"  # base64 encoded "test crash data"

        # Verify returned vulnerability object
        assert result is not None
        assert result.crash == sample_crash
        assert result.vuln_id == "test-pov-123"

    @patch("buttercup.common.node_local.lopen")
    @patch("buttercup.common.node_local.make_locally_available")
    def test_api_error_raises_exception(self, mock_make_locally, mock_lopen, vulnerabilities, sample_crash):
        # Mock file handling
        mock_file = Mock()
        mock_file.read.return_value = b"test crash data"
        mock_lopen.return_value.__enter__.return_value = mock_file

        # Setup API exception
        vulnerabilities.pov_api.v1_task_task_id_pov_post.side_effect = Exception("API Error")

        # Verify exception is raised
        with pytest.raises(Exception) as exc_info:
            vulnerabilities.submit_pov(sample_crash)
        assert "API Error" in str(exc_info.value)

    @patch("buttercup.common.node_local.lopen")
    @patch("buttercup.common.node_local.make_locally_available")
    def test_file_read_error_raises_exception(self, mock_make_locally, mock_lopen, vulnerabilities, sample_crash):
        # Mock file reading error
        mock_lopen.side_effect = FileNotFoundError("File not found")

        # Verify exception is raised
        with pytest.raises(Exception) as exc_info:
            vulnerabilities.submit_pov(sample_crash)
        assert "File not found" in str(exc_info.value)


class TestDedupCrash:
    def test_returns_crash_as_unique(self, vulnerabilities, sample_crash):
        assert vulnerabilities.dedup_crash(sample_crash) == sample_crash


class TestCheckPendingStatuses:
    def test_check_pending_statuses_no_pending(self, vulnerabilities, mock_submission_tracker):
        # Setup
        mock_submission_tracker.get_pending_pov_submissions.return_value = []

        # Execute
        result = vulnerabilities.check_pending_statuses()

        # Verify
        assert result is False
        mock_submission_tracker.get_pending_pov_submissions.assert_called_once()
        vulnerabilities.pov_api.v1_task_task_id_pov_pov_id_get.assert_not_called()

    def test_check_pending_statuses_success(self, vulnerabilities, mock_submission_tracker):
        # Setup
        task_id = "test_task"
        pov_id = "test_pov"
        mock_submission_tracker.get_pending_pov_submissions.return_value = [(task_id, pov_id)]
        mock_response = TypesPOVSubmissionResponse(status=TypesSubmissionStatus.PASSED, pov_id=pov_id)
        vulnerabilities.pov_api.v1_task_task_id_pov_pov_id_get.return_value = mock_response

        # Execute
        result = vulnerabilities.check_pending_statuses()

        # Verify
        assert result is True
        mock_submission_tracker.get_pending_pov_submissions.assert_called_once()
        vulnerabilities.pov_api.v1_task_task_id_pov_pov_id_get.assert_called_once_with(task_id=task_id, pov_id=pov_id)
        mock_submission_tracker.update_pov_status.assert_called_once_with(task_id, pov_id, TypesSubmissionStatus.PASSED)

    def test_check_pending_statuses_api_error(self, vulnerabilities, mock_submission_tracker):
        # Setup
        task_id = "test_task"
        pov_id = "test_pov"
        mock_submission_tracker.get_pending_pov_submissions.return_value = [(task_id, pov_id)]
        vulnerabilities.pov_api.v1_task_task_id_pov_pov_id_get.side_effect = Exception("API Error")

        # Execute
        result = vulnerabilities.check_pending_statuses()

        # Verify
        assert result is False
        mock_submission_tracker.get_pending_pov_submissions.assert_called_once()
        vulnerabilities.pov_api.v1_task_task_id_pov_pov_id_get.assert_called_once_with(task_id=task_id, pov_id=pov_id)
        mock_submission_tracker.update_pov_status.assert_not_called()

    def test_check_pending_statuses_accepted_status(self, vulnerabilities, mock_submission_tracker):
        # Setup
        task_id = "test_task"
        pov_id = "test_pov"
        mock_submission_tracker.get_pending_pov_submissions.return_value = [(task_id, pov_id)]
        mock_response = TypesPOVSubmissionResponse(status=TypesSubmissionStatus.ACCEPTED, pov_id=pov_id)
        vulnerabilities.pov_api.v1_task_task_id_pov_pov_id_get.return_value = mock_response

        # Execute
        result = vulnerabilities.check_pending_statuses()

        # Verify
        assert result is True
        mock_submission_tracker.get_pending_pov_submissions.assert_called_once()
        vulnerabilities.pov_api.v1_task_task_id_pov_pov_id_get.assert_called_once_with(task_id=task_id, pov_id=pov_id)
        mock_submission_tracker.update_pov_status.assert_not_called()
