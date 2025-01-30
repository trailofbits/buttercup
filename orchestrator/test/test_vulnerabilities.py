import pytest
from unittest.mock import Mock
from buttercup.orchestrator.scheduler.vulnerabilities import Vulnerabilities
from buttercup.common.queues import RQItem, QueueFactory
from buttercup.common.datastructures.msg_pb2 import Crash, ConfirmedVulnerability
from unittest.mock import patch


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
def vulnerabilities(mock_redis, mock_queues):
    vuln = Vulnerabilities(redis=mock_redis)
    # Manually set the queues to match our mocks
    vuln.crash_queue = mock_queues["crash"]
    vuln.unique_vulnerabilities_queue = mock_queues["unique"]
    vuln.confirmed_vulnerabilities_queue = mock_queues["confirmed"]
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


def test_process_crashes_with_valid_crash(vulnerabilities, mock_queues):
    # Setup
    crash = Crash()
    crash.target.package_name = "test_package"
    crash.harness_path = "test_harness"
    crash.crash_input_path = "test_input"

    mock_item = RQItem(item_id="test_id", deserialized=crash)
    mock_queues["crash"].pop.return_value = mock_item

    # Execute
    result = vulnerabilities.process_crashes()

    # Verify
    assert result is True
    mock_queues["crash"].pop.assert_called_once()
    mock_queues["unique"].push.assert_called_once()
    mock_queues["crash"].ack_item.assert_called_once_with("test_id")


def test_process_unique_vulnerabilities_with_no_vulns(vulnerabilities, mock_queues):
    # Setup
    mock_queues["unique"].pop.return_value = None

    # Execute/test
    result = vulnerabilities.process_unique_vulnerabilities()

    # Verify
    assert result is False
    mock_queues["unique"].pop.assert_called_once()
    mock_queues["confirmed"].push.assert_not_called()


def test_process_unique_vulnerabilities_with_valid_vuln(vulnerabilities, mock_queues):
    # Setup
    crash = Crash()
    crash.target.package_name = "test_package"
    crash.harness_path = "test_harness"
    crash.crash_input_path = "test_input"

    mock_item = RQItem(item_id="test_id", deserialized=crash)
    mock_queues["unique"].pop.return_value = mock_item

    # Execute
    result = vulnerabilities.process_unique_vulnerabilities()

    # Verify
    assert result is True
    mock_queues["unique"].pop.assert_called_once()
    mock_queues["confirmed"].push.assert_called_once()
    mock_queues["unique"].ack_item.assert_called_once_with("test_id")


def test_submit_vulnerability_creates_confirmed_vuln(vulnerabilities, mock_queues):
    # Setup
    crash = Crash()
    crash.target.package_name = "test_package"
    crash.harness_path = "test_harness"
    crash.crash_input_path = "test_input"

    # Execute
    vulnerabilities.submit_vulnerability(crash)

    # Verify
    mock_queues["confirmed"].push.assert_called_once()
    # Verify the pushed item is a ConfirmedVulnerability
    pushed_vuln = mock_queues["confirmed"].push.call_args[0][0]
    assert isinstance(pushed_vuln, ConfirmedVulnerability)
    assert pushed_vuln.crash.target.package_name == "test_package"
    assert pushed_vuln.vuln_id != ""  # Verify UUID was generated


def test_dedup_crash_returns_crash(vulnerabilities):
    # Setup
    crash = Crash()
    crash.target.package_name = "test_package"
    crash.harness_path = "test_harness"
    crash.crash_input_path = "test_input"

    # Execute
    result = vulnerabilities.dedup_crash(crash)

    # Verify
    assert result == crash  # Currently returns all crashes as unique
