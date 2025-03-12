import pytest
import uuid
from unittest.mock import Mock, patch
from buttercup.orchestrator.scheduler.vulnerabilities import Vulnerabilities
from buttercup.common.queues import RQItem, QueueFactory
from buttercup.common.datastructures.msg_pb2 import Crash, BuildOutput, TracedCrash
from buttercup.orchestrator.competition_api_client.models.types_vuln_submission_response import (
    TypesVulnSubmissionResponse,
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
def sample_crash():
    crash = Crash()
    target = BuildOutput()
    target.sanitizer = "test_sanitizer"
    target.task_id = str(uuid.uuid4())
    crash.target.CopyFrom(target)
    crash.harness_name = "test_harness"
    crash.crash_input_path = "test/crash/input.txt"
    annotated_crash = TracedCrash()
    annotated_crash.crash.CopyFrom(crash)
    annotated_crash.tracer_stacktrace = "test_stacktrace"
    return annotated_crash


@pytest.fixture
def vulnerabilities(mock_redis, mock_api_client, mock_queues):
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

    # Mock the vulnerability API method we use
    vuln.vulnerability_api.v1_task_task_id_vuln_post = Mock()

    return vuln


class TestProcessTracedVulnerabilities:
    def test_no_vulns_returns_false(self, vulnerabilities, mock_queues):
        mock_queues["traced"].pop.return_value = None
        assert vulnerabilities.process_traced_vulnerabilities() is False
        mock_queues["traced"].pop.assert_called_once()
        mock_queues["confirmed"].push.assert_not_called()

    @patch("builtins.open")
    def test_accepted_submission_processes_successfully(self, mock_open, vulnerabilities, mock_queues, sample_crash):
        # Mock file reading
        mock_file = Mock()
        mock_file.read.return_value = b"test crash data"
        mock_open.return_value.__enter__.return_value = mock_file

        mock_item = RQItem(item_id="test_id", deserialized=sample_crash)
        mock_queues["traced"].pop.return_value = mock_item

        mock_response = TypesVulnSubmissionResponse(status=TypesSubmissionStatus.ACCEPTED, vuln_id="test-vuln-123")
        vulnerabilities.vulnerability_api.v1_task_task_id_vuln_post.return_value = mock_response

        assert vulnerabilities.process_traced_vulnerabilities() is True
        mock_queues["traced"].pop.assert_called_once()
        mock_queues["confirmed"].push.assert_called_once()
        mock_queues["traced"].ack_item.assert_called_once_with("test_id")

    @patch("builtins.open")
    def test_rejected_submission_is_handled_gracefully(self, mock_open, vulnerabilities, mock_queues, sample_crash):
        # Mock file reading
        mock_file = Mock()
        mock_file.read.return_value = b"test crash data"
        mock_open.return_value.__enter__.return_value = mock_file

        mock_item = RQItem(item_id="test_id", deserialized=sample_crash)
        mock_queues["traced"].pop.return_value = mock_item

        mock_response = TypesVulnSubmissionResponse(status=TypesSubmissionStatus.INVALID, vuln_id="rejected-123")
        vulnerabilities.vulnerability_api.v1_task_task_id_vuln_post.return_value = mock_response

        assert vulnerabilities.process_traced_vulnerabilities() is True
        mock_queues["traced"].pop.assert_called_once()
        mock_queues["confirmed"].push.assert_not_called()
        mock_queues["traced"].ack_item.assert_called_once_with("test_id")

    @patch("builtins.open")
    def test_api_error_is_handled_gracefully(self, mock_open, vulnerabilities, mock_queues, sample_crash):
        # Mock file reading
        mock_file = Mock()
        mock_file.read.return_value = b"test crash data"
        mock_open.return_value.__enter__.return_value = mock_file

        mock_item = RQItem(item_id="test_id", deserialized=sample_crash)
        mock_queues["traced"].pop.return_value = mock_item

        vulnerabilities.vulnerability_api.v1_task_task_id_vuln_post.side_effect = Exception("API Error")

        assert vulnerabilities.process_traced_vulnerabilities() is True
        mock_queues["traced"].pop.assert_called_once()
        mock_queues["confirmed"].push.assert_not_called()
        mock_queues["traced"].ack_item.assert_not_called()

    def test_cancelled_task_is_skipped(self, vulnerabilities, mock_queues, sample_crash):
        mock_item = RQItem(item_id="test_id", deserialized=sample_crash)
        mock_queues["traced"].pop.return_value = mock_item
        vulnerabilities.task_registry.is_cancelled = Mock(return_value=True)

        assert vulnerabilities.process_traced_vulnerabilities() is True
        mock_queues["traced"].pop.assert_called_once()
        mock_queues["confirmed"].push.assert_not_called()
        mock_queues["traced"].ack_item.assert_called_once_with("test_id")
        vulnerabilities.task_registry.is_cancelled.assert_called_once_with(sample_crash.crash.target.task_id)


class TestSubmitVulnerability:
    @patch("builtins.open")
    def test_successful_submission(self, mock_open, vulnerabilities, sample_crash):
        # Mock file reading
        mock_file = Mock()
        mock_file.read.return_value = b"test crash data"
        mock_open.return_value.__enter__.return_value = mock_file

        mock_response = TypesVulnSubmissionResponse(status=TypesSubmissionStatus.ACCEPTED, vuln_id="test-vuln-123")
        vulnerabilities.vulnerability_api.v1_task_task_id_vuln_post.return_value = mock_response

        result = vulnerabilities.submit_vulnerability(sample_crash)

        # Verify file was read correctly
        mock_open.assert_called_once_with(sample_crash.crash.crash_input_path, "rb")

        # Verify API was called with correct data
        vulnerabilities.vulnerability_api.v1_task_task_id_vuln_post.assert_called_once()
        call_args = vulnerabilities.vulnerability_api.v1_task_task_id_vuln_post.call_args
        assert call_args[1]["task_id"] == sample_crash.crash.target.task_id
        assert call_args[1]["payload"].data_file == "dGVzdCBjcmFzaCBkYXRh"  # base64 encoded "test crash data"

        # Verify returned vulnerability object
        assert result is not None
        assert result.crash == sample_crash
        assert result.vuln_id == "test-vuln-123"

    @patch("builtins.open")
    def test_api_error_raises_exception(self, mock_open, vulnerabilities, sample_crash):
        # Mock file reading
        mock_file = Mock()
        mock_file.read.return_value = b"test crash data"
        mock_open.return_value.__enter__.return_value = mock_file

        vulnerabilities.vulnerability_api.v1_task_task_id_vuln_post.side_effect = Exception("API Error")

        with pytest.raises(Exception) as exc_info:
            vulnerabilities.submit_vulnerability(sample_crash)
        assert "API Error" in str(exc_info.value)

    @patch("builtins.open")
    def test_file_read_error_raises_exception(self, mock_open, vulnerabilities, sample_crash):
        # Mock file reading error
        mock_open.side_effect = FileNotFoundError("File not found")

        with pytest.raises(Exception) as exc_info:
            vulnerabilities.submit_vulnerability(sample_crash)
        assert "File not found" in str(exc_info.value)


class TestDedupCrash:
    def test_returns_crash_as_unique(self, vulnerabilities, sample_crash):
        assert vulnerabilities.dedup_crash(sample_crash) == sample_crash
