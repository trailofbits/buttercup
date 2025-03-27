import pytest
from unittest.mock import Mock
from buttercup.orchestrator.scheduler.bundles import Bundles
from buttercup.orchestrator.competition_api_client.models.types_bundle_submission_response import (
    TypesBundleSubmissionResponse,
)
from buttercup.orchestrator.competition_api_client.models.types_submission_status import TypesSubmissionStatus
from buttercup.orchestrator.competition_api_client.models.types_bundle_submission import TypesBundleSubmission


@pytest.fixture
def mock_redis():
    return Mock()


@pytest.fixture
def mock_api_client():
    return Mock()


@pytest.fixture
def mock_bundle_api():
    mock = Mock()
    mock.v1_task_task_id_bundle_post = Mock()
    return mock


@pytest.fixture
def mock_task_registry():
    mock = Mock()
    mock.should_stop_processing = Mock()
    return mock


@pytest.fixture
def mock_submission_tracker():
    mock = Mock()
    mock.get_ready_vulnerability_patch_bundles = Mock()
    mock.mark_bundle_submitted = Mock()
    return mock


@pytest.fixture
def bundles(mock_redis, mock_api_client, mock_bundle_api, mock_task_registry, mock_submission_tracker):
    bundles = Bundles(redis=mock_redis, api_client=mock_api_client)
    bundles.bundle_api = mock_bundle_api
    bundles.task_registry = mock_task_registry
    bundles.submission_tracker = mock_submission_tracker
    return bundles


def test_submit_bundle_success(bundles, mock_bundle_api):
    # Setup
    task_id = "test_task"
    vulnerability_id = "test_vuln"
    patch_id = "test_patch"
    expected_response = TypesBundleSubmissionResponse(status=TypesSubmissionStatus.ACCEPTED, bundle_id="test_bundle_id")
    mock_bundle_api.v1_task_task_id_bundle_post.return_value = expected_response

    # Execute
    result = bundles.submit_bundle(task_id, vulnerability_id, patch_id)

    # Verify
    assert result == expected_response
    mock_bundle_api.v1_task_task_id_bundle_post.assert_called_once_with(
        task_id=task_id, payload=TypesBundleSubmission(pov_id=vulnerability_id, patch_id=patch_id, description=None)
    )
    bundles.submission_tracker.mark_bundle_submitted.assert_called_once_with(task_id, vulnerability_id, patch_id)


def test_submit_bundle_api_error(bundles, mock_bundle_api):
    # Setup
    task_id = "test_task"
    vulnerability_id = "test_vuln"
    patch_id = "test_patch"
    mock_bundle_api.v1_task_task_id_bundle_post.side_effect = Exception("API Error")

    # Execute and verify
    with pytest.raises(Exception) as exc_info:
        bundles.submit_bundle(task_id, vulnerability_id, patch_id)
    assert str(exc_info.value) == "API Error"
    bundles.submission_tracker.mark_bundle_submitted.assert_not_called()


def test_process_bundles_no_ready_bundles(bundles, mock_submission_tracker):
    # Setup
    mock_submission_tracker.get_ready_vulnerability_patch_bundles.return_value = []

    # Execute
    result = bundles.process_bundles()

    # Verify
    assert result is False
    mock_submission_tracker.get_ready_vulnerability_patch_bundles.assert_called_once()


def test_process_bundles_cancelled_task(bundles, mock_submission_tracker, mock_bundle_api):
    # Setup
    task_id = "test_task"
    vulnerability_id = "test_vuln"
    patch_id = "test_patch"
    mock_submission_tracker.get_ready_vulnerability_patch_bundles.return_value = [(task_id, vulnerability_id, patch_id)]
    bundles.task_registry.should_stop_processing.return_value = True

    # Execute
    result = bundles.process_bundles()

    # Verify
    assert result is False
    mock_bundle_api.v1_task_task_id_bundle_post.assert_not_called()


def test_process_bundles_success(bundles, mock_submission_tracker, mock_bundle_api):
    # Setup
    task_id = "test_task"
    vulnerability_id = "test_vuln"
    patch_id = "test_patch"
    mock_submission_tracker.get_ready_vulnerability_patch_bundles.return_value = [(task_id, vulnerability_id, patch_id)]
    bundles.task_registry.should_stop_processing.return_value = False

    response = TypesBundleSubmissionResponse(status=TypesSubmissionStatus.ACCEPTED, bundle_id="test_bundle_id")
    mock_bundle_api.v1_task_task_id_bundle_post.return_value = response

    # Execute
    result = bundles.process_bundles()

    # Verify
    assert result is True
    mock_bundle_api.v1_task_task_id_bundle_post.assert_called_once_with(
        task_id=task_id, payload=TypesBundleSubmission(pov_id=vulnerability_id, patch_id=patch_id, description=None)
    )
    bundles.submission_tracker.mark_bundle_submitted.assert_called_once_with(task_id, vulnerability_id, patch_id)


def test_submit_bundle_passed_status(bundles, mock_bundle_api):
    # Setup
    task_id = "test_task"
    vulnerability_id = "test_vuln"
    patch_id = "test_patch"
    expected_response = TypesBundleSubmissionResponse(status=TypesSubmissionStatus.PASSED, bundle_id="test_bundle_id")
    mock_bundle_api.v1_task_task_id_bundle_post.return_value = expected_response

    # Execute
    result = bundles.submit_bundle(task_id, vulnerability_id, patch_id)

    # Verify
    assert result == expected_response
    mock_bundle_api.v1_task_task_id_bundle_post.assert_called_once_with(
        task_id=task_id, payload=TypesBundleSubmission(pov_id=vulnerability_id, patch_id=patch_id, description=None)
    )
    bundles.submission_tracker.mark_bundle_submitted.assert_called_once_with(task_id, vulnerability_id, patch_id)


def test_submit_bundle_failed_status(bundles, mock_bundle_api):
    # Setup
    task_id = "test_task"
    vulnerability_id = "test_vuln"
    patch_id = "test_patch"
    expected_response = TypesBundleSubmissionResponse(status=TypesSubmissionStatus.FAILED, bundle_id="test_bundle_id")
    mock_bundle_api.v1_task_task_id_bundle_post.return_value = expected_response

    # Execute
    result = bundles.submit_bundle(task_id, vulnerability_id, patch_id)

    # Verify
    assert result is None
    mock_bundle_api.v1_task_task_id_bundle_post.assert_called_once_with(
        task_id=task_id, payload=TypesBundleSubmission(pov_id=vulnerability_id, patch_id=patch_id, description=None)
    )
    bundles.submission_tracker.mark_bundle_submitted.assert_not_called()
