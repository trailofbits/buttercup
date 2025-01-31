import pytest
import uuid
from unittest.mock import Mock, patch
from buttercup.orchestrator.scheduler.vulnerabilities import Vulnerabilities
from buttercup.common.queues import RQItem, QueueFactory
from buttercup.common.datastructures.msg_pb2 import Crash, ConfirmedVulnerability, BuildOutput
from buttercup.orchestrator.competition_api_client.models.types_vuln_submission_response import (
    TypesVulnSubmissionResponse,
)
from buttercup.orchestrator.competition_api_client.models.types_submission_status import TypesSubmissionStatus


@pytest.fixture
def mock_redis():
    return Mock()


@pytest.fixture
def mock_queues():
    crash_queue = Mock()
    unique_vulnerabilities_queue = Mock()
    confirmed_vulnerabilities_queue = Mock()

    # Mock QueueFactory
    queue_factory = Mock(spec=QueueFactory)
    queue_factory.create.side_effect = [crash_queue, unique_vulnerabilities_queue, confirmed_vulnerabilities_queue]

    # Create a patch for QueueFactory
    with patch("buttercup.orchestrator.scheduler.vulnerabilities.QueueFactory", return_value=queue_factory):
        yield {
            "factory": queue_factory,
            "crash": crash_queue,
            "unique": unique_vulnerabilities_queue,
            "confirmed": confirmed_vulnerabilities_queue,
        }


@pytest.fixture
def sample_crash():
    crash = Crash()
    target = BuildOutput()
    target.package_name = "test_package"
    target.sanitizer = "test_sanitizer"
    target.task_id = str(uuid.uuid4())
    crash.target.CopyFrom(target)
    crash.harness_path = "test_harness"
    crash.crash_input_path = "test/crash/input.txt"
    return crash


@pytest.fixture
def vulnerabilities(mock_redis, mock_queues):
    # Mock Redis operations for TaskRegistry
    mock_redis.hexists.return_value = False
    mock_redis.hget.return_value = None

    vuln = Vulnerabilities(redis=mock_redis)
    # Manually set the queues to match our mocks
    vuln.crash_queue = mock_queues["crash"]
    vuln.unique_vulnerabilities_queue = mock_queues["unique"]
    vuln.confirmed_vulnerabilities_queue = mock_queues["confirmed"]

    # Mock task_registry methods directly instead of relying on Redis
    vuln.task_registry.is_cancelled = Mock(return_value=False)
    return vuln


def test_process_crashes_with_no_crashes(vulnerabilities, mock_queues):
    # Setup
    mock_queues["crash"].pop.return_value = None

    # Execute
    result = vulnerabilities.process_crashes()

    # Verify
    assert result is False
    mock_queues["crash"].pop.assert_called_once()
    mock_queues["unique"].push.assert_not_called()


def test_process_crashes_with_valid_crash(vulnerabilities, mock_queues, sample_crash):
    # Setup
    mock_item = RQItem(item_id="test_id", deserialized=sample_crash)
    mock_queues["crash"].pop.return_value = mock_item

    # Execute
    result = vulnerabilities.process_crashes()

    # Verify
    assert result is True
    mock_queues["crash"].pop.assert_called_once()
    mock_queues["unique"].push.assert_called_once()
    mock_queues["crash"].ack_item.assert_called_once_with("test_id")


def test_process_crashes_with_exception(vulnerabilities, mock_queues, sample_crash):
    # Setup
    mock_item = RQItem(item_id="test_id", deserialized=sample_crash)
    mock_queues["crash"].pop.return_value = mock_item
    mock_queues["unique"].push.side_effect = Exception("Test error")

    # Execute
    result = vulnerabilities.process_crashes()

    # Verify
    assert result is False
    mock_queues["crash"].pop.assert_called_once()
    mock_queues["crash"].ack_item.assert_not_called()


def test_process_unique_vulnerabilities_with_no_vulns(vulnerabilities, mock_queues):
    # Setup
    mock_queues["unique"].pop.return_value = None

    # Execute
    result = vulnerabilities.process_unique_vulnerabilities()

    # Verify
    assert result is False
    mock_queues["unique"].pop.assert_called_once()
    mock_queues["confirmed"].push.assert_not_called()


@patch("buttercup.orchestrator.scheduler.vulnerabilities.VulnerabilityApi")
def test_process_unique_vulnerabilities_with_accepted_submission(
    mock_vuln_api, vulnerabilities, mock_queues, sample_crash
):
    # Setup
    mock_item = RQItem(item_id="test_id", deserialized=sample_crash)
    mock_queues["unique"].pop.return_value = mock_item

    # Mock API response
    mock_api_instance = Mock()
    mock_vuln_api.return_value = mock_api_instance

    mock_response = TypesVulnSubmissionResponse(status=TypesSubmissionStatus.ACCEPTED, vuln_id="test-vuln-123")
    mock_api_instance.v1_task_task_id_vuln_post.return_value = mock_response

    # Execute
    result = vulnerabilities.process_unique_vulnerabilities()

    # Verify
    assert result is True
    mock_queues["unique"].pop.assert_called_once()
    mock_queues["confirmed"].push.assert_called_once()
    mock_queues["unique"].ack_item.assert_called_once_with("test_id")

    # Verify the API was called correctly
    mock_api_instance.v1_task_task_id_vuln_post.assert_called_once()
    call_args = mock_api_instance.v1_task_task_id_vuln_post.call_args
    assert call_args[1]["task_id"] == sample_crash.target.task_id

    # Verify the pushed confirmed vulnerability
    pushed_vuln = mock_queues["confirmed"].push.call_args[0][0]
    assert isinstance(pushed_vuln, ConfirmedVulnerability)
    assert pushed_vuln.crash.target.package_name == sample_crash.target.package_name
    assert pushed_vuln.vuln_id == "test-vuln-123"


@patch("buttercup.orchestrator.scheduler.vulnerabilities.VulnerabilityApi")
def test_process_unique_vulnerabilities_with_rejected_submission(
    mock_vuln_api, vulnerabilities, mock_queues, sample_crash
):
    # Setup
    mock_item = RQItem(item_id="test_id", deserialized=sample_crash)
    mock_queues["unique"].pop.return_value = mock_item

    # Mock API response for rejected submission
    mock_api_instance = Mock()
    mock_vuln_api.return_value = mock_api_instance

    mock_response = TypesVulnSubmissionResponse(status=TypesSubmissionStatus.INVALID, vuln_id="rejected-123")
    mock_api_instance.v1_task_task_id_vuln_post.return_value = mock_response

    # Execute
    result = vulnerabilities.process_unique_vulnerabilities()

    # Verify
    assert result is True
    mock_queues["unique"].pop.assert_called_once()
    mock_queues["confirmed"].push.assert_not_called()
    mock_queues["unique"].ack_item.assert_called_once_with("test_id")


@patch("buttercup.orchestrator.scheduler.vulnerabilities.VulnerabilityApi")
def test_process_unique_vulnerabilities_with_api_error(mock_vuln_api, vulnerabilities, mock_queues, sample_crash):
    # Setup
    mock_item = RQItem(item_id="test_id", deserialized=sample_crash)
    mock_queues["unique"].pop.return_value = mock_item

    # Mock API error
    mock_api_instance = Mock()
    mock_vuln_api.return_value = mock_api_instance
    mock_api_instance.v1_task_task_id_vuln_post.side_effect = Exception("API Error")

    # Execute
    result = vulnerabilities.process_unique_vulnerabilities()

    # Verify
    assert result is True
    mock_queues["unique"].pop.assert_called_once()
    mock_queues["confirmed"].push.assert_not_called()
    mock_queues["unique"].ack_item.assert_not_called()


@patch("buttercup.orchestrator.scheduler.vulnerabilities.VulnerabilityApi")
def test_submit_vulnerability_api_error(mock_vuln_api, vulnerabilities, sample_crash):
    # Setup
    mock_api_instance = Mock()
    mock_vuln_api.return_value = mock_api_instance
    mock_api_instance.v1_task_task_id_vuln_post.side_effect = Exception("API Error")

    # Execute and verify exception is raised
    with pytest.raises(Exception) as exc_info:
        vulnerabilities.submit_vulnerability(sample_crash)

    assert "API Error" in str(exc_info.value)


def test_dedup_crash_returns_crash(vulnerabilities, sample_crash):
    # Execute
    result = vulnerabilities.dedup_crash(sample_crash)

    # Verify
    assert result == sample_crash  # Currently returns all crashes as unique


def test_process_unique_vulnerabilities_with_cancelled_task(vulnerabilities, mock_queues, sample_crash):
    # Setup
    mock_item = RQItem(item_id="test_id", deserialized=sample_crash)
    mock_queues["unique"].pop.return_value = mock_item

    # Mock task registry to indicate cancelled task
    vulnerabilities.task_registry.is_cancelled = Mock(return_value=True)

    # Execute
    result = vulnerabilities.process_unique_vulnerabilities()

    # Verify
    assert result is True
    mock_queues["unique"].pop.assert_called_once()
    mock_queues["confirmed"].push.assert_not_called()
    mock_queues["unique"].ack_item.assert_called_once_with("test_id")
    vulnerabilities.task_registry.is_cancelled.assert_called_once_with(sample_crash.target.task_id)
