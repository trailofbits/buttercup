import pytest
import base64
import uuid
from unittest.mock import Mock, patch, MagicMock
from buttercup.orchestrator.scheduler.submissions import CompetitionAPI, Submissions
from buttercup.common.datastructures.msg_pb2 import (
    TracedCrash,
    BuildOutput,
    Crash,
    Patch,
    SubmissionEntry,
    Task,
)
from buttercup.common.task_registry import TaskRegistry
from buttercup.orchestrator.competition_api_client.models.types_pov_submission_response import (
    TypesPOVSubmissionResponse,
)
from buttercup.orchestrator.competition_api_client.models.types_patch_submission_response import (
    TypesPatchSubmissionResponse,
)
from buttercup.orchestrator.competition_api_client.models.types_bundle_submission_response import (
    TypesBundleSubmissionResponse,
)
from buttercup.orchestrator.competition_api_client.models.types_submission_status import TypesSubmissionStatus
from buttercup.common.constants import ARCHITECTURE


@pytest.fixture
def mock_api_client():
    return Mock()


@pytest.fixture
def mock_task_registry():
    mock_registry = Mock(spec=TaskRegistry)
    mock_registry.should_stop_processing.return_value = False

    # Create a mock task with proper metadata dictionary
    mock_task = Mock(spec=Task)
    mock_task.metadata = {
        "metadata": {
            "round.id": "round-1",
            "task.id": "task-1",
            "team.id": "team-1",
        }
    }

    # Configure the mock to return the mock task for any task_id
    mock_registry.get.return_value = mock_task
    return mock_registry


@pytest.fixture
def competition_api(mock_api_client, mock_task_registry):
    return CompetitionAPI(mock_api_client, mock_task_registry)


@pytest.fixture
def sample_crash():
    crash = Crash()
    target = BuildOutput()
    target.sanitizer = "test_sanitizer"
    target.engine = "test_engine"
    target.task_id = str(uuid.uuid4())
    crash.target.CopyFrom(target)
    crash.harness_name = "test_harness"
    crash.crash_input_path = "/test/crash/input.txt"
    traced_crash = TracedCrash()
    traced_crash.crash.CopyFrom(crash)
    traced_crash.tracer_stacktrace = "test_stacktrace"
    return traced_crash


@pytest.fixture
def mock_redis():
    mock = Mock()
    mock.lrange.return_value = []  # Default empty list for stored submissions
    mock.smembers.return_value = set()  # Return empty set for smembers calls
    return mock


@pytest.fixture
def mock_competition_api(mock_task_registry):
    mock = Mock(spec=CompetitionAPI)
    # Add the missing method that's needed in tests
    mock.submit_bundle_patch = Mock(return_value=(True, TypesSubmissionStatus.SubmissionStatusAccepted))
    return mock


@pytest.fixture
def submissions(mock_redis, mock_competition_api, mock_task_registry):
    # Create a Submissions instance with our mocks
    subs = Submissions(redis=mock_redis, competition_api=mock_competition_api, task_registry=mock_task_registry)
    return subs


@pytest.fixture
def sample_submission_entry(sample_crash):
    entry = SubmissionEntry()
    entry.crash.CopyFrom(sample_crash)
    entry.pov_id = "test-pov-123"
    entry.state = SubmissionEntry.SUBMIT_PATCH_REQUEST
    return entry


@pytest.fixture
def sample_patch():
    patch = Patch()
    patch.submission_index = "0"
    patch.task_id = "test-task-123"
    patch.patch = "test patch content"
    return patch


# Tests for the CompetitionAPI class
class TestCompetitionAPI:
    @patch("buttercup.common.node_local.lopen")
    def test_submit_pov_successful(self, mock_lopen, competition_api, sample_crash, mock_api_client):
        # Mock file handling
        mock_file = Mock()
        mock_file.read.return_value = b"test crash data"
        mock_lopen.return_value.__enter__.return_value = mock_file

        # Setup API response
        mock_response = TypesPOVSubmissionResponse(
            status=TypesSubmissionStatus.SubmissionStatusAccepted, pov_id="test-pov-123"
        )

        # Setup API client mock
        mock_pov_api = Mock()
        mock_pov_api.v1_task_task_id_pov_post.return_value = mock_response

        # Patch the PovApi constructor
        with patch("buttercup.orchestrator.scheduler.submissions.PovApi", return_value=mock_pov_api):
            # Call the method before verifying any mocks
            result = competition_api.submit_pov(sample_crash)

            # Verify result first
            assert result[0] == "test-pov-123"
            assert result[1] == TypesSubmissionStatus.SubmissionStatusAccepted

            # Verify file was read correctly
            mock_lopen.assert_called_once_with(sample_crash.crash.crash_input_path, "rb")

            # Verify API was called with correct parameters
            mock_pov_api.v1_task_task_id_pov_post.assert_called_once()
            call_args = mock_pov_api.v1_task_task_id_pov_post.call_args
            assert call_args[1]["task_id"] == sample_crash.crash.target.task_id

            # Check payload
            payload = call_args[1]["payload"]
            assert payload.architecture == ARCHITECTURE
            assert payload.engine == sample_crash.crash.target.engine
            assert payload.fuzzer_name == sample_crash.crash.harness_name
            assert payload.sanitizer == sample_crash.crash.target.sanitizer

    @patch("buttercup.common.node_local.lopen")
    def test_submit_pov_failed(self, mock_lopen, competition_api, sample_crash):
        # Mock file handling
        mock_file = Mock()
        mock_file.read.return_value = b"test crash data"
        mock_lopen.return_value.__enter__.return_value = mock_file

        # Setup API response
        mock_response = TypesPOVSubmissionResponse(status=TypesSubmissionStatus.SubmissionStatusFailed, pov_id="")

        # Setup API client mock
        mock_pov_api = Mock()
        mock_pov_api.v1_task_task_id_pov_post.return_value = mock_response

        # Patch the PovApi constructor
        with patch("buttercup.orchestrator.scheduler.submissions.PovApi", return_value=mock_pov_api):
            # Call the method
            result = competition_api.submit_pov(sample_crash)

            # Verify result is a tuple with (None, FAILED)
            assert result[0] is None
            assert result[1] == TypesSubmissionStatus.SubmissionStatusFailed

    def test_get_pov_status(self, competition_api):
        # Setup mock
        mock_pov_api = Mock()
        mock_pov_api.v1_task_task_id_pov_pov_id_get.return_value = Mock(
            status=TypesSubmissionStatus.SubmissionStatusPassed
        )

        # Patch the PovApi constructor
        with patch("buttercup.orchestrator.scheduler.submissions.PovApi", return_value=mock_pov_api):
            # Call method
            status = competition_api.get_pov_status("task-123", "pov-456")

            # Verify call and result
            mock_pov_api.v1_task_task_id_pov_pov_id_get.assert_called_once_with(task_id="task-123", pov_id="pov-456")
            assert status == TypesSubmissionStatus.SubmissionStatusPassed

    def test_submit_patch_successful(self, competition_api):
        # Setup test data
        task_id = "task-123"
        patch_content = "diff --git a/file.c b/file.c\n@@ -1,1 +1,1 @@\n-old\n+new"
        expected_encoded_patch = base64.b64encode(patch_content.encode()).decode()

        # Setup mock response
        mock_response = TypesPatchSubmissionResponse(
            status=TypesSubmissionStatus.SubmissionStatusAccepted, patch_id="patch-123"
        )

        # Setup patch API mock
        mock_patch_api = Mock()
        mock_patch_api.v1_task_task_id_patch_post.return_value = mock_response

        # Patch the PatchApi constructor
        with patch("buttercup.orchestrator.scheduler.submissions.PatchApi", return_value=mock_patch_api):
            # Call method
            result = competition_api.submit_patch(task_id, patch_content)

            # Verify API call
            mock_patch_api.v1_task_task_id_patch_post.assert_called_once()
            call_args = mock_patch_api.v1_task_task_id_patch_post.call_args
            assert call_args[1]["task_id"] == task_id
            assert call_args[1]["payload"].patch == expected_encoded_patch

            # Verify result
            assert result[0] == "patch-123"
            assert result[1] == TypesSubmissionStatus.SubmissionStatusAccepted

    def test_get_patch_status(self, competition_api):
        # Setup mock
        mock_patch_api = Mock()
        mock_patch_api.v1_task_task_id_patch_patch_id_get.return_value = Mock(
            status=TypesSubmissionStatus.SubmissionStatusPassed
        )

        # Patch the PatchApi constructor
        with patch("buttercup.orchestrator.scheduler.submissions.PatchApi", return_value=mock_patch_api):
            # Call method
            status = competition_api.get_patch_status("task-123", "patch-456")

            # Verify call and result
            mock_patch_api.v1_task_task_id_patch_patch_id_get.assert_called_once_with(
                task_id="task-123", patch_id="patch-456"
            )
            assert status == TypesSubmissionStatus.SubmissionStatusPassed

    def test_submit_bundle_successful(self, competition_api):
        # Setup test data
        task_id = "task-123"
        pov_id = "pov-456"
        patch_id = "patch-789"

        # Setup mock response
        mock_response = TypesBundleSubmissionResponse(
            status=TypesSubmissionStatus.SubmissionStatusAccepted, bundle_id="bundle-123"
        )

        # Setup bundle API mock
        mock_bundle_api = Mock()
        mock_bundle_api.v1_task_task_id_bundle_post.return_value = mock_response

        # Patch the BundleApi constructor
        with patch("buttercup.orchestrator.scheduler.submissions.BundleApi", return_value=mock_bundle_api):
            # Call method
            result = competition_api.submit_bundle(task_id, pov_id, patch_id)

            # Verify API call
            mock_bundle_api.v1_task_task_id_bundle_post.assert_called_once()
            call_args = mock_bundle_api.v1_task_task_id_bundle_post.call_args
            assert call_args[1]["task_id"] == task_id
            assert call_args[1]["payload"].pov_id == pov_id
            assert call_args[1]["payload"].patch_id == patch_id

            # Verify result
            assert result[0] == "bundle-123"
            assert result[1] == TypesSubmissionStatus.SubmissionStatusAccepted

    def test_submit_matching_sarif_successful(self, competition_api):
        # Setup test data
        task_id = "task-123"
        sarif_id = "sarif-456"

        # Setup mock response
        mock_response = Mock(status=TypesSubmissionStatus.SubmissionStatusAccepted)

        # Setup sarif API mock
        mock_sarif_api = Mock()
        mock_sarif_api.v1_task_task_id_broadcast_sarif_assessment_broadcast_sarif_id_post.return_value = mock_response

        # Patch the BroadcastSarifAssessmentApi constructor
        with patch(
            "buttercup.orchestrator.scheduler.submissions.BroadcastSarifAssessmentApi", return_value=mock_sarif_api
        ):
            # Call method
            result = competition_api.submit_matching_sarif(task_id, sarif_id)

            # Verify API call
            mock_sarif_api.v1_task_task_id_broadcast_sarif_assessment_broadcast_sarif_id_post.assert_called_once()

            # Verify result
            assert result[0] is True
            assert result[1] == TypesSubmissionStatus.SubmissionStatusAccepted


# Tests for the Submissions class
class TestSubmissions:
    def test_submit_vulnerability_successful(self, submissions, mock_competition_api, sample_crash, mock_redis):
        # Setup mock return value for submit_vulnerability
        mock_competition_api.submit_pov.return_value = ("test-pov-123", TypesSubmissionStatus.SubmissionStatusAccepted)
        mock_redis.rpush.return_value = 1  # Index of the inserted entry

        # Call the method
        result = submissions.submit_vulnerability(sample_crash)

        # Verify competition API call
        mock_competition_api.submit_pov.assert_called_once_with(sample_crash)

        # Verify Redis interactions
        mock_redis.rpush.assert_called_once()

        # Verify result
        assert result is True

        # Verify entries list is updated
        assert len(submissions.entries) == 1
        assert submissions.entries[0].pov_id == "test-pov-123"
        assert submissions.entries[0].state == SubmissionEntry.SUBMIT_PATCH_REQUEST

    def test_submit_vulnerability_failed(self, submissions, mock_competition_api, sample_crash):
        # Setup mock to return an error
        mock_competition_api.submit_pov.return_value = (None, TypesSubmissionStatus.SubmissionStatusFailed)

        # Call the method
        result = submissions.submit_vulnerability(sample_crash)

        # Verify competition API call
        mock_competition_api.submit_pov.assert_called_once_with(sample_crash)

        # Verify result
        assert result is True  # Returns True even for a failure because we stop processing

        # Verify no entries were added
        assert len(submissions.entries) == 0

    def test_submit_vulnerability_errored(self, submissions, mock_competition_api, sample_crash):
        # Setup mock to return an error
        mock_competition_api.submit_pov.return_value = (None, TypesSubmissionStatus.SubmissionStatusErrored)

        # Call the method
        result = submissions.submit_vulnerability(sample_crash)

        # Verify competition API call
        mock_competition_api.submit_pov.assert_called_once_with(sample_crash)

        # Verify result
        assert result is False  # Returns False for ERRORED, indicating we should retry

        # Verify no entries were added
        assert len(submissions.entries) == 0

    def test_record_patch(self, submissions, sample_patch, sample_submission_entry):
        # Setup submission entry in entries list
        submissions.entries = [sample_submission_entry]

        # Set task_id in both sample_submission_entry and sample_patch to match
        task_id = "test-task-123"
        sample_submission_entry.crash.crash.target.task_id = task_id
        sample_patch.task_id = task_id

        # Call the method
        result = submissions.record_patch(sample_patch)

        # Verify _persist was called
        submissions.redis.lset.assert_called_once()

        # Verify patch was added to entries
        assert len(submissions.entries[0].patches) == 1
        assert submissions.entries[0].patches[0] == sample_patch.patch

        # Verify return value
        assert result is True

    def test_record_patch_task_stopped(self, submissions, sample_patch, sample_submission_entry, mock_task_registry):
        # Setup submission entry in entries list
        submissions.entries = [sample_submission_entry]

        # Set task_id in both sample_submission_entry and sample_patch to match
        task_id = "test-task-123"
        sample_submission_entry.crash.crash.target.task_id = task_id
        sample_patch.task_id = task_id

        # Configure mock to return True for should_stop_processing
        mock_task_registry.should_stop_processing.return_value = True

        # Call the method
        result = submissions.record_patch(sample_patch)

        # Verify _persist was still called
        submissions.redis.lset.assert_called_once()

        # Verify patch was added to entries
        assert len(submissions.entries[0].patches) == 1
        assert submissions.entries[0].patches[0] == sample_patch.patch

        # Verify return value
        assert result is True

        # Verify should_stop_processing was called with the task_id
        mock_task_registry.should_stop_processing.assert_called_once_with(task_id)


# Tests for state transitions
class TestStateTransitions:
    def test_submit_patch_request_transition(self, submissions, sample_submission_entry):
        # Setup entry in SUBMIT_PATCH_REQUEST state
        sample_submission_entry.state = SubmissionEntry.SUBMIT_PATCH_REQUEST
        submissions.entries = [sample_submission_entry]

        # Mock QueueFactory
        queue_mock = MagicMock()
        pipeline_mock = MagicMock()
        submissions.redis.pipeline.return_value = pipeline_mock

        # Simulate process_cycle
        with patch(
            "buttercup.orchestrator.scheduler.submissions.QueueFactory", return_value=MagicMock()
        ) as queue_factory_mock:
            queue_factory_mock.return_value.create.return_value = queue_mock
            submissions.process_cycle()

        # Verify state transition
        assert sample_submission_entry.state == SubmissionEntry.WAIT_POV_PASS

    def test_wait_pov_pass_to_submit_patch(self, submissions, sample_submission_entry, mock_competition_api):
        # Setup entry in WAIT_POV_PASS state
        sample_submission_entry.state = SubmissionEntry.WAIT_POV_PASS
        submissions.entries = [sample_submission_entry]

        # Mock competition API to return PASSED
        mock_competition_api.get_pov_status.return_value = TypesSubmissionStatus.SubmissionStatusPassed

        # Simulate process_cycle
        submissions.process_cycle()

        # Verify state transition
        assert sample_submission_entry.state == SubmissionEntry.SUBMIT_PATCH

    def test_wait_pov_pass_to_stop_when_failed(self, submissions, sample_submission_entry, mock_competition_api):
        # Setup entry in WAIT_POV_PASS state
        sample_submission_entry.state = SubmissionEntry.WAIT_POV_PASS
        submissions.entries = [sample_submission_entry]

        # Mock competition API to return FAILED
        mock_competition_api.get_pov_status.return_value = TypesSubmissionStatus.SubmissionStatusFailed

        # Simulate process_cycle
        submissions.process_cycle()

        # Verify state transition
        assert sample_submission_entry.state == SubmissionEntry.STOP

    def test_wait_pov_pass_resubmit_when_errored(self, submissions, sample_submission_entry, mock_competition_api):
        # Setup entry in WAIT_POV_PASS state
        sample_submission_entry.state = SubmissionEntry.WAIT_POV_PASS
        submissions.entries = [sample_submission_entry]

        # Mock competition API to return ERRORED then successful resubmission
        mock_competition_api.get_pov_status.return_value = TypesSubmissionStatus.SubmissionStatusErrored
        mock_competition_api.submit_pov.return_value = ("new-pov-456", TypesSubmissionStatus.SubmissionStatusAccepted)

        # Simulate process_cycle
        submissions.process_cycle()

        # Verify POV was resubmitted with new ID
        mock_competition_api.submit_pov.assert_called_once_with(sample_submission_entry.crash)
        assert sample_submission_entry.pov_id == "new-pov-456"
        # State remains the same as we're waiting for the new submission to be processed
        assert sample_submission_entry.state == SubmissionEntry.WAIT_POV_PASS

    def test_submit_patch_successful(self, submissions, sample_submission_entry, mock_competition_api):
        # Setup entry in SUBMIT_PATCH state with a patch
        sample_submission_entry.state = SubmissionEntry.SUBMIT_PATCH
        sample_submission_entry.patches.append("test patch content")
        sample_submission_entry.patch_idx = 0
        sample_submission_entry.patch_submission_attempt = 0
        submissions.entries = [sample_submission_entry]

        # Mock competition API to return successful patch submission
        mock_competition_api.submit_patch.return_value = (
            "test-patch-123",
            TypesSubmissionStatus.SubmissionStatusAccepted,
        )

        # Mock the _have_more_patches function to avoid AttributeError
        with patch("buttercup.orchestrator.scheduler.submissions._have_more_patches", return_value=True):
            # Simulate process_cycle
            submissions.process_cycle()

            # Verify state transition and patch ID
            assert sample_submission_entry.state == SubmissionEntry.WAIT_PATCH_PASS
            assert sample_submission_entry.patch_id == "test-patch-123"
            assert sample_submission_entry.patch_submission_attempt == 1  # Incremented

    def test_wait_patch_pass_to_submit_bundle(self, submissions, sample_submission_entry, mock_competition_api):
        # Setup entry in WAIT_PATCH_PASS state
        sample_submission_entry.state = SubmissionEntry.WAIT_PATCH_PASS
        sample_submission_entry.patch_id = "test-patch-123"
        submissions.entries = [sample_submission_entry]

        # Mock competition API to return PASSED
        mock_competition_api.get_patch_status.return_value = TypesSubmissionStatus.SubmissionStatusPassed

        # Simulate process_cycle
        submissions.process_cycle()

        # Verify state transition
        assert sample_submission_entry.state == SubmissionEntry.SUBMIT_BUNDLE

    def test_wait_patch_pass_to_submit_patch_when_failed(
        self, submissions, sample_submission_entry, mock_competition_api
    ):
        # Setup entry in WAIT_PATCH_PASS state
        sample_submission_entry.state = SubmissionEntry.WAIT_PATCH_PASS
        sample_submission_entry.patch_id = "test-patch-123"
        sample_submission_entry.patch_idx = 0
        sample_submission_entry.patches.append("test patch content")
        sample_submission_entry.patches.append("another test patch")  # Add a second patch for advancement
        submissions.entries = [sample_submission_entry]

        # Mock competition API to return FAILED
        mock_competition_api.get_patch_status.return_value = TypesSubmissionStatus.SubmissionStatusFailed

        # Mock the _advance_patch_idx function to avoid AttributeError
        with patch("buttercup.orchestrator.scheduler.submissions._advance_patch_idx") as mock_advance:
            # Simulate process_cycle
            submissions.process_cycle()

            # Verify advance_patch_idx was called
            mock_advance.assert_called_once_with(sample_submission_entry)

            # Verify state transition
            assert sample_submission_entry.state == SubmissionEntry.SUBMIT_PATCH

    def test_submit_bundle_successful(self, submissions, sample_submission_entry, mock_competition_api):
        # Setup entry in SUBMIT_BUNDLE state
        sample_submission_entry.state = SubmissionEntry.SUBMIT_BUNDLE
        sample_submission_entry.pov_id = "test-pov-123"
        sample_submission_entry.patch_id = "test-patch-456"
        submissions.entries = [sample_submission_entry]

        # Mock competition API to return successful bundle submission
        mock_competition_api.submit_bundle.return_value = (
            "test-bundle-789",
            TypesSubmissionStatus.SubmissionStatusAccepted,
        )

        # Simulate process_cycle
        submissions.process_cycle()

        # Verify state transition and bundle ID
        assert sample_submission_entry.state == SubmissionEntry.SUBMIT_MATCHING_SARIF
        assert sample_submission_entry.bundle_id == "test-bundle-789"

    def test_submit_bundle_to_stop_when_failed(self, submissions, sample_submission_entry, mock_competition_api):
        # Setup entry in SUBMIT_BUNDLE state
        sample_submission_entry.state = SubmissionEntry.SUBMIT_BUNDLE
        sample_submission_entry.pov_id = "test-pov-123"
        sample_submission_entry.patch_id = "test-patch-456"
        submissions.entries = [sample_submission_entry]

        # Mock competition API to return failed bundle submission
        mock_competition_api.submit_bundle.return_value = (None, TypesSubmissionStatus.SubmissionStatusFailed)

        # Simulate process_cycle
        submissions.process_cycle()

        # Verify state transition to STOP
        assert sample_submission_entry.state == SubmissionEntry.STOP

    def test_submit_bundle_retry_when_errored(self, submissions, sample_submission_entry, mock_competition_api):
        # Setup entry in SUBMIT_BUNDLE state
        sample_submission_entry.state = SubmissionEntry.SUBMIT_BUNDLE
        sample_submission_entry.pov_id = "test-pov-123"
        sample_submission_entry.patch_id = "test-patch-456"
        submissions.entries = [sample_submission_entry]

        # Mock competition API to return error
        mock_competition_api.submit_bundle.return_value = (None, TypesSubmissionStatus.SubmissionStatusErrored)

        # Simulate process_cycle
        submissions.process_cycle()

        # Verify state remains the same (will retry on next cycle)
        assert sample_submission_entry.state == SubmissionEntry.SUBMIT_BUNDLE

    def test_submit_matching_sarif_successful(self, submissions, sample_submission_entry, mock_competition_api):
        # Setup entry in SUBMIT_MATCHING_SARIF state
        sample_submission_entry.state = SubmissionEntry.SUBMIT_MATCHING_SARIF
        sample_submission_entry.pov_id = "test-pov-123"
        sample_submission_entry.patch_id = "test-patch-456"
        sample_submission_entry.bundle_id = "test-bundle-789"
        submissions.entries = [sample_submission_entry]

        # Create a mock for finding a matching SARIF
        with patch.object(submissions, "_submit_matching_sarif", autospec=True) as mock_submit_sarif:
            # Configure the mock to set a sarif_id and advance state
            def side_effect(i, e):
                e.sarif_id = "test-sarif-123"
                e.state = SubmissionEntry.SUBMIT_BUNDLE_PATCH
                return

            mock_submit_sarif.side_effect = side_effect

            # Simulate process_cycle
            submissions.process_cycle()

            # Verify state transition and SARIF ID
            assert sample_submission_entry.state == SubmissionEntry.SUBMIT_BUNDLE_PATCH
            assert sample_submission_entry.sarif_id == "test-sarif-123"

    def test_submit_bundle_patch_successful(self, submissions, sample_submission_entry, mock_competition_api):
        # Setup entry in SUBMIT_BUNDLE_PATCH state
        sample_submission_entry.state = SubmissionEntry.SUBMIT_BUNDLE_PATCH
        sample_submission_entry.pov_id = "test-pov-123"
        sample_submission_entry.patch_id = "test-patch-456"
        sample_submission_entry.bundle_id = "test-bundle-789"
        sample_submission_entry.sarif_id = "test-sarif-123"
        submissions.entries = [sample_submission_entry]

        # Mock competition API to return successful bundle patch
        mock_competition_api.patch_bundle.return_value = (True, TypesSubmissionStatus.SubmissionStatusAccepted)

        # Simulate process_cycle
        submissions.process_cycle()

        # Verify state transition to STOP (terminal state)
        assert sample_submission_entry.state == SubmissionEntry.STOP

    def test_all_states_in_process_cycle(self, submissions, sample_submission_entry):
        # Test that process_cycle handles all states by mocking the individual state handlers
        submissions.entries = [sample_submission_entry]

        # Create mocks for all state handlers
        submissions._submit_patch_request = Mock()
        submissions._wait_pov_pass = Mock()
        submissions._submit_patch = Mock()
        submissions._wait_patch_pass = Mock()
        submissions._submit_bundle = Mock()
        submissions._submit_matching_sarif = Mock()
        submissions._submit_bundle_patch = Mock()

        # Test each state
        for state in [
            SubmissionEntry.SUBMIT_PATCH_REQUEST,
            SubmissionEntry.WAIT_POV_PASS,
            SubmissionEntry.SUBMIT_PATCH,
            SubmissionEntry.WAIT_PATCH_PASS,
            SubmissionEntry.SUBMIT_BUNDLE,
            SubmissionEntry.SUBMIT_MATCHING_SARIF,
            SubmissionEntry.SUBMIT_BUNDLE_PATCH,
            SubmissionEntry.STOP,
        ]:
            # Reset mocks
            for mock_method in [
                submissions._submit_patch_request,
                submissions._wait_pov_pass,
                submissions._submit_patch,
                submissions._wait_patch_pass,
                submissions._submit_bundle,
                submissions._submit_matching_sarif,
                submissions._submit_bundle_patch,
            ]:
                mock_method.reset_mock()

            # Set the state
            sample_submission_entry.state = state

            # Run process_cycle
            submissions.process_cycle()

            # Verify correct method was called based on state
            if state == SubmissionEntry.SUBMIT_PATCH_REQUEST:
                submissions._submit_patch_request.assert_called_once()
            elif state == SubmissionEntry.WAIT_POV_PASS:
                submissions._wait_pov_pass.assert_called_once()
            elif state == SubmissionEntry.SUBMIT_PATCH:
                submissions._submit_patch.assert_called_once()
            elif state == SubmissionEntry.WAIT_PATCH_PASS:
                submissions._wait_patch_pass.assert_called_once()
            elif state == SubmissionEntry.SUBMIT_BUNDLE:
                submissions._submit_bundle.assert_called_once()
            elif state == SubmissionEntry.SUBMIT_MATCHING_SARIF:
                submissions._submit_matching_sarif.assert_called_once()
            elif state == SubmissionEntry.SUBMIT_BUNDLE_PATCH:
                submissions._submit_bundle_patch.assert_called_once()
            # For STOP state, none of the methods should be called

    def test_submit_patch_uses_task_id_correctly(self, submissions, sample_submission_entry, mock_competition_api):
        """
        Test that the _submit_patch method correctly passes the task_id to the CompetitionAPI.submit_patch method,
        not the TracedCrash object directly.
        """
        # Setup entry in SUBMIT_PATCH state with a patch
        task_id = "test-task-specific-id"
        sample_submission_entry.state = SubmissionEntry.SUBMIT_PATCH
        sample_submission_entry.patches.append("test patch content")
        sample_submission_entry.patch_idx = 0
        sample_submission_entry.patch_submission_attempt = 0
        sample_submission_entry.crash.crash.target.task_id = task_id
        submissions.entries = [sample_submission_entry]

        # Mock the _task_id function to verify it's being called with the right arguments
        with patch("buttercup.orchestrator.scheduler.submissions._task_id", return_value=task_id) as mock_task_id:
            # Mock competition API to return successful patch submission
            mock_competition_api.submit_patch.return_value = (
                "test-patch-123",
                TypesSubmissionStatus.SubmissionStatusAccepted,
            )

            # Simulate process_cycle
            submissions.process_cycle()

            # Verify _task_id was called with the submission entry
            mock_task_id.assert_called_with(sample_submission_entry)

            # Verify competition_api.submit_patch was called with the task_id, not the crash object
            mock_competition_api.submit_patch.assert_called_once()
            args, kwargs = mock_competition_api.submit_patch.call_args

            # First argument should be the task_id, not the crash
            assert args[0] == task_id
            assert args[0] != sample_submission_entry.crash

            # Second argument should be the patch content
            assert args[1] == "test patch content"

            # Verify state transition and patch ID set correctly
            assert sample_submission_entry.state == SubmissionEntry.WAIT_PATCH_PASS
            assert sample_submission_entry.patch_id == "test-patch-123"
            assert sample_submission_entry.patch_submission_attempt == 1  # Incremented
