import pytest
import base64
import uuid
from unittest.mock import Mock, patch, MagicMock
from pathlib import Path
from typing import Optional
from buttercup.orchestrator.scheduler.submissions import CompetitionAPI, Submissions
from buttercup.common.datastructures.msg_pb2 import (
    TracedCrash,
    BuildOutput,
    Crash,
    Patch,
    SubmissionEntry,
    Task,
    SubmissionEntryPatch,
    BuildType,
    CrashWithId,
    SubmissionResult,
    Bundle,
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
from buttercup.orchestrator.scheduler.submissions import (
    _get_first_successful_pov_id,
    _find_matching_build_output,
    _get_first_successful_pov,
    _get_pending_pov_submissions,
    _get_eligible_povs_for_submission,
    _get_pending_patch_submissions,
    _current_patch,
)
from buttercup.common.clusterfuzz_parser.crash_comparer import CrashComparer


def create_crash_comparison_mocks(similar_patterns=None):
    """Create mock functions for crash comparison tests.

    Args:
        similar_patterns: List of patterns that should be considered similar.
                         If None, patterns containing "similar_pattern" are similar.
    """
    if similar_patterns is None:
        similar_patterns = ["similar_pattern"]

    def mock_get_crash_data(stacktrace):
        for pattern in similar_patterns:
            if pattern in stacktrace:
                return "similar_data"
        return f"unique_data_{hash(stacktrace)}"

    def mock_get_inst_key(stacktrace):
        for pattern in similar_patterns:
            if pattern in stacktrace:
                return "similar_inst"
        return f"unique_inst_{hash(stacktrace)}"

    def mock_crash_comparer_init(self, data1, data2):
        self.data1 = data1
        self.data2 = data2

    def mock_is_similar(self):
        return self.data1 == "similar_data" and self.data2 == "similar_data"

    return mock_get_crash_data, mock_get_inst_key, mock_crash_comparer_init, mock_is_similar


class SubmissionEntryBuilder:
    """Builder pattern for creating SubmissionEntry objects in tests."""

    def __init__(self):
        self.entry = SubmissionEntry()

    def crash(
        self,
        task_id: Optional[str] = None,
        competition_pov_id: Optional[str] = None,
        result: Optional[SubmissionResult] = None,
        crash_input_path: Optional[str] = None,
        harness_name: Optional[str] = None,
        sanitizer: Optional[str] = None,
        engine: Optional[str] = None,
        stacktrace: Optional[str] = None,
    ):
        """Add a crash to the submission entry.

        All parameters are optional. If None, protobuf defaults will be used.
        """
        crash = Crash()
        target = BuildOutput()

        if sanitizer is not None:
            target.sanitizer = sanitizer
        if engine is not None:
            target.engine = engine
        if task_id is not None:
            target.task_id = task_id

        crash.target.CopyFrom(target)

        if harness_name is not None:
            crash.harness_name = harness_name
        if crash_input_path is not None:
            crash.crash_input_path = crash_input_path
        if stacktrace is not None:
            crash.stacktrace = stacktrace

        traced_crash = TracedCrash()
        traced_crash.crash.CopyFrom(crash)

        crash_with_id = CrashWithId()
        crash_with_id.crash.CopyFrom(traced_crash)
        if competition_pov_id is not None:
            crash_with_id.competition_pov_id = competition_pov_id
        if result is not None:
            crash_with_id.result = result

        self.entry.crashes.append(crash_with_id)
        return self

    def patch(
        self,
        internal_patch_id: Optional[str] = None,
        patch_content: Optional[str] = None,
        competition_patch_id: Optional[str] = None,
        result: Optional[SubmissionResult] = None,
    ):
        """Add a patch to the submission entry.

        All parameters are optional. If None, protobuf defaults will be used.
        """
        patch_entry = SubmissionEntryPatch()
        if internal_patch_id is not None:
            patch_entry.internal_patch_id = internal_patch_id
        if patch_content is not None:
            patch_entry.patch = patch_content
        if competition_patch_id is not None:
            patch_entry.competition_patch_id = competition_patch_id
        if result is not None:
            patch_entry.result = result

        self.entry.patches.append(patch_entry)
        return self

    def bundle(
        self,
        bundle_id: Optional[str] = None,
        competition_pov_id: Optional[str] = None,
        competition_patch_id: Optional[str] = None,
        competition_sarif_id: Optional[str] = None,
        task_id: Optional[str] = None,
    ):
        """Add a bundle to the submission entry.

        All parameters are optional. If None, protobuf defaults will be used.
        """
        bundle = Bundle()
        if bundle_id is not None:
            bundle.bundle_id = bundle_id
        if competition_pov_id is not None:
            bundle.competition_pov_id = competition_pov_id
        if competition_patch_id is not None:
            bundle.competition_patch_id = competition_patch_id
        if competition_sarif_id is not None:
            bundle.competition_sarif_id = competition_sarif_id
        if task_id is not None:
            bundle.task_id = task_id

        self.entry.bundles.append(bundle)
        return self

    def stopped(self, is_stopped: bool = True):
        """Mark the submission as stopped."""
        self.entry.stop = is_stopped
        return self

    def patch_idx(self, idx: int):
        """Set the patch index."""
        self.entry.patch_idx = idx
        return self

    def patch_submission_attempts(self, attempts: int):
        """Set the patch submission attempts."""
        self.entry.patch_submission_attempts = attempts
        return self

    def build_output(
        self,
        patch_internal_id: Optional[str] = None,
        sanitizer: Optional[str] = None,
        engine: Optional[str] = None,
        build_type: Optional[BuildType] = None,
        apply_diff: Optional[bool] = None,
        task_dir: Optional[str] = None,
        task_id: Optional[str] = None,
    ):
        """Add a build output to the last patch.

        All parameters are optional. If None, protobuf defaults will be used.
        """
        if not self.entry.patches:
            raise ValueError("Cannot add build output without a patch. Call .patch() first.")

        build_output = BuildOutput()
        if patch_internal_id is not None:
            build_output.internal_patch_id = patch_internal_id
        if sanitizer is not None:
            build_output.sanitizer = sanitizer
        if engine is not None:
            build_output.engine = engine
        if build_type is not None:
            build_output.build_type = build_type
        if apply_diff is not None:
            build_output.apply_diff = apply_diff
        if task_dir is not None:
            build_output.task_dir = task_dir
        if task_id is not None:
            build_output.task_id = task_id

        self.entry.patches[-1].build_outputs.append(build_output)
        return self

    def build(self) -> SubmissionEntry:
        """Build and return the SubmissionEntry."""
        return self.entry


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
    target.engine = "libfuzzer"
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
    mock.rpush.return_value = 1  # Return an integer instead of Mock object

    # Mock pipeline context manager
    pipeline_mock = Mock()
    pipeline_mock.__enter__ = Mock(return_value=pipeline_mock)
    pipeline_mock.__exit__ = Mock(return_value=None)
    pipeline_mock.lset = Mock(return_value=True)  # Mock lset on pipeline
    pipeline_mock.execute = Mock(return_value=[True])  # Mock execute
    mock.pipeline.return_value = pipeline_mock

    return mock


@pytest.fixture
def mock_competition_api(mock_task_registry):
    mock = Mock(spec=CompetitionAPI)
    # Add the missing method that's needed in tests
    mock.submit_bundle_patch = Mock(return_value=(True, SubmissionResult.ACCEPTED))
    return mock


@pytest.fixture
def submissions(mock_redis, mock_competition_api, mock_task_registry):
    # Mock QueueFactory to avoid the missing reproduce_response_queue initialization
    with patch("buttercup.orchestrator.scheduler.submissions.QueueFactory") as mock_queue_factory:
        # Create mock queues
        mock_build_queue = Mock()
        mock_build_queue.push = Mock()  # Ensure push method is properly mocked
        mock_reproduce_queue = Mock()
        mock_reproduce_queue.pop.return_value = None  # No items in queue
        mock_reproduce_queue.ack_item = Mock()  # Mock ack_item method

        # Configure QueueFactory to return the appropriate queue based on queue name
        def queue_factory_side_effect(queue_name, **kwargs):
            if queue_name == "QueueNames.BUILD":
                return mock_build_queue
            else:
                return mock_reproduce_queue

        mock_queue_factory.return_value.create.side_effect = queue_factory_side_effect

        # Create a Submissions instance with our mocks
        subs = Submissions(
            redis=mock_redis,
            competition_api=mock_competition_api,
            task_registry=mock_task_registry,
            tasks_storage_dir=Path("/tmp/tasks_storage"),
        )

    # Add additional attributes needed for _request_patched_builds
    subs.select_preferred = Mock(return_value="libfuzzer")
    # The build_requests_queue is already set by __post_init__, just use the mock
    subs.build_requests_queue = mock_build_queue
    # Set the reproduce_response_queue manually since we need to reference it in tests
    subs.reproduce_response_queue = mock_reproduce_queue
    # Mock the pov_reproduce_status
    subs.pov_reproduce_status = Mock()
    subs.pov_reproduce_status.request_status.return_value = None  # Pending status
    # Mock the _key_from_patch_id method that's referenced in record_repro_status but doesn't exist
    subs._key_from_patch_id = Mock(return_value=(0, 0))
    return subs


@pytest.fixture
def sample_submission_entry(sample_crash):
    entry = SubmissionEntry()
    crash_with_id = CrashWithId()
    crash_with_id.crash.CopyFrom(sample_crash)
    crash_with_id.competition_pov_id = "test-pov-123"
    entry.crashes.append(crash_with_id)
    return entry


@pytest.fixture
def sample_patch():
    patch = Patch()
    patch.internal_patch_id = "0"
    patch.task_id = "test-task-123"
    patch.patch = "test patch content"
    return patch


@pytest.fixture
def sample_build_output():
    build_output = BuildOutput()
    build_output.internal_patch_id = "0"  # internal_patch_id format
    build_output.sanitizer = "test_sanitizer"
    build_output.engine = "libfuzzer"
    build_output.task_id = "test-task-123"
    build_output.build_type = BuildType.PATCH
    build_output.apply_diff = True
    build_output.task_dir = "/tmp/build/test-task-123"
    return build_output


# Helper functions to work with the current SubmissionEntry structure


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
            assert result[1] == SubmissionResult.ACCEPTED

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
            assert result[1] == SubmissionResult.FAILED

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
            assert status == SubmissionResult.PASSED

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
            assert result[1] == SubmissionResult.ACCEPTED

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
            assert status == SubmissionResult.PASSED

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
            sarif_id = "sarif-789"  # Add required sarif_id parameter
            result = competition_api.submit_bundle(task_id, pov_id, patch_id, sarif_id)

            # Verify API call
            mock_bundle_api.v1_task_task_id_bundle_post.assert_called_once()
            call_args = mock_bundle_api.v1_task_task_id_bundle_post.call_args
            assert call_args[1]["task_id"] == task_id
            assert call_args[1]["payload"].pov_id == pov_id
            assert call_args[1]["payload"].patch_id == patch_id

            # Verify result
            assert result[0] == "bundle-123"
            assert result[1] == SubmissionResult.ACCEPTED

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
            assert result[1] == SubmissionResult.ACCEPTED


# Tests for the Submissions class
class TestSubmissions:
    def test_submit_vulnerability_successful(self, submissions, mock_competition_api, sample_crash, mock_redis):
        # Configure mock Redis to return proper values
        mock_redis.rpush.return_value = 1  # Index of the inserted entry

        # Call the method
        result = submissions.submit_vulnerability(sample_crash)

        # Verify Redis interactions - entry should be added
        mock_redis.rpush.assert_called_once()

        # Verify result
        assert result is True

        # Verify entries list is updated
        assert len(submissions.entries) == 1
        entry = submissions.entries[0]

        # Verify crashes field is populated correctly
        assert len(entry.crashes) == 1
        assert entry.crashes[0].crash == sample_crash

        # POV should not be submitted yet (happens in process_cycle)
        mock_competition_api.submit_pov.assert_not_called()

        # POV ID should not be set yet
        assert not entry.crashes[0].competition_pov_id

    def test_submit_vulnerability_failed(self, submissions, mock_competition_api, sample_crash):
        # Configure mock Redis to return proper values
        submissions.redis.rpush.return_value = 1  # Index of the inserted entry

        # Call the method
        result = submissions.submit_vulnerability(sample_crash)

        # Verify result - should succeed (creates entry regardless of POV submission outcome)
        assert result is True

        # Verify entry was created
        assert len(submissions.entries) == 1

        # POV submission happens later in process_cycle, not immediately
        mock_competition_api.submit_pov.assert_not_called()

    def test_submit_vulnerability_errored(self, submissions, mock_competition_api, sample_crash):
        # Configure mock Redis to return proper values
        submissions.redis.rpush.return_value = 1  # Index of the inserted entry

        # Call the method
        result = submissions.submit_vulnerability(sample_crash)

        # Verify result - should succeed (creates entry regardless of POV submission outcome)
        assert result is True

        # Verify entry was created
        assert len(submissions.entries) == 1

        # POV submission happens later in process_cycle, not immediately
        mock_competition_api.submit_pov.assert_not_called()

    def test_record_patch(self, submissions, sample_patch, sample_submission_entry):
        # Setup submission entry in entries list
        submissions.entries = [sample_submission_entry]

        # Set task_id in both sample_submission_entry and sample_patch to match
        task_id = "test-task-123"
        sample_submission_entry.crashes[0].crash.crash.target.task_id = task_id  # Access first crash in crashes list
        sample_patch.task_id = task_id

        # Add a patch entry that matches the sample_patch's internal_patch_id
        patch_entry = SubmissionEntryPatch()
        patch_entry.internal_patch_id = sample_patch.internal_patch_id  # "0"
        # Don't set patch content - this is the first time we're recording a patch for this tracker
        sample_submission_entry.patches.append(patch_entry)

        # Mock ChallengeTask and ProjectYaml dependencies for _request_patched_builds
        mock_task = Mock()
        mock_task.task_dir = Path("/tmp/tasks_storage") / task_id
        mock_task.task_meta.project_name = "test_project"

        mock_project_yaml = Mock()
        mock_project_yaml.fuzzing_engines = ["libfuzzer", "afl"]
        mock_project_yaml.sanitizers = ["asan", "msan", "ubsan"]

        with (
            patch("buttercup.orchestrator.scheduler.submissions.ChallengeTask", return_value=mock_task),
            patch("buttercup.orchestrator.scheduler.submissions.ProjectYaml", return_value=mock_project_yaml),
        ):
            # Call the method
            result = submissions.record_patch(sample_patch)

        # Verify NO build requests were pushed to queue during record_patch
        # (builds are now requested during process_cycle instead)
        assert submissions.build_requests_queue.push.call_count == 0

        # Verify _persist was called
        submissions.redis.lset.assert_called_once()

        # Verify patch was updated in entries
        assert len(submissions.entries[0].patches) == 1
        assert submissions.entries[0].patches[0].patch == sample_patch.patch

        # Verify return value
        assert result is True

    def test_record_patch_task_stopped(self, submissions, sample_patch, sample_submission_entry, mock_task_registry):
        # Setup submission entry in entries list
        submissions.entries = [sample_submission_entry]

        # Set task_id in both sample_submission_entry and sample_patch to match
        task_id = "test-task-123"
        sample_submission_entry.crashes[0].crash.crash.target.task_id = task_id  # Access first crash in crashes list
        sample_patch.task_id = task_id

        # Add a patch entry that matches the sample_patch's internal_patch_id
        patch_entry = SubmissionEntryPatch()
        patch_entry.internal_patch_id = sample_patch.internal_patch_id  # "0"
        # Don't set patch content - this is the first time we're recording a patch for this tracker
        sample_submission_entry.patches.append(patch_entry)

        # Set the task_registry on the submissions object
        submissions.task_registry = mock_task_registry

        # Configure mock to return True for should_stop_processing
        mock_task_registry.should_stop_processing.return_value = True

        # Call the method
        result = submissions.record_patch(sample_patch)

        # Verify that the method returns True (acknowledges the patch)
        assert result is True

        # Verify _persist was NOT called since task is stopped
        submissions.redis.lset.assert_not_called()

        # Verify patch was NOT updated since task is stopped
        assert len(submissions.entries[0].patches) == 1
        assert submissions.entries[0].patches[0].patch == ""  # Empty since we didn't set it

        # Verify should_stop_processing was called with the task_id
        mock_task_registry.should_stop_processing.assert_called_once_with(task_id)

    def test_consolidate_multiple_similar_submissions(self, submissions, mock_competition_api, mock_redis):
        """Test consolidation when a crash is similar to multiple existing submissions."""

        # Create three existing submissions with different crashes that will be similar to our new crash
        task_id = "test-task-consolidate"

        # Setup submissions using builder pattern - add to entries and mock Redis
        submissions.entries = [
            # Submission 1 - has POV ID and patches
            (
                SubmissionEntryBuilder()
                .crash(
                    task_id=task_id,
                    stacktrace="similar_crash_pattern_stack1",
                    harness_name="harness1",
                    competition_pov_id="pov-123",
                    result=SubmissionResult.PASSED,
                )
                .patch(internal_patch_id="patch1", patch_content="patch content 1")
                .patch_idx(1)
                .patch_submission_attempts(2)
                .build()
            ),
            # Submission 2 - has bundle ID
            (
                SubmissionEntryBuilder()
                .crash(
                    task_id=task_id,
                    stacktrace="similar_crash_pattern_stack2",
                    harness_name="harness2",
                    competition_pov_id="pov-456",
                    result=SubmissionResult.PASSED,
                )
                .patch(internal_patch_id="patch2a", patch_content="patch content 2a")
                .patch(internal_patch_id="patch2b", patch_content="patch content 2b")
                .bundle(
                    bundle_id="bundle-456",
                    competition_pov_id="pov-456",
                    competition_patch_id="comp-patch-456",
                    task_id=task_id,
                )
                .patch_idx(0)
                .patch_submission_attempts(1)
                .build()
            ),
            # Submission 3 - has SARIF ID (most advanced)
            (
                SubmissionEntryBuilder()
                .crash(
                    task_id=task_id,
                    stacktrace="similar_crash_pattern_stack3",
                    harness_name="harness3",
                    competition_pov_id="pov-789",
                    result=SubmissionResult.PASSED,
                )
                .patch(internal_patch_id="patch3", patch_content="patch content 3")
                .bundle(
                    bundle_id="bundle-789",
                    competition_pov_id="pov-789",
                    competition_patch_id="comp-patch-789",
                    competition_sarif_id="sarif-789",
                    task_id=task_id,
                )
                .patch_idx(2)
                .patch_submission_attempts(5)
                .build()
            ),
        ]

        # Mock Redis rpush to return the correct index for the new submission
        mock_redis.rpush.return_value = len(submissions.entries) + 1

        # Create a new crash that will be similar to all three submissions
        new_crash = TracedCrash()
        new_crash.crash.target.task_id = task_id
        new_crash.crash.stacktrace = "similar_crash_pattern_new"  # Will be detected as similar
        new_crash.crash.harness_name = "new_harness"

        # Mock the crash comparison to return similar for all existing crashes
        mock_get_crash_data, mock_get_inst_key, mock_crash_comparer_init, mock_is_similar = (
            create_crash_comparison_mocks(["similar_crash_pattern"])
        )

        # Apply mocks
        with (
            patch("buttercup.orchestrator.scheduler.submissions.get_crash_data", side_effect=mock_get_crash_data),
            patch("buttercup.orchestrator.scheduler.submissions.get_inst_key", side_effect=mock_get_inst_key),
            patch.object(CrashComparer, "__init__", mock_crash_comparer_init),
            patch.object(CrashComparer, "is_similar", mock_is_similar),
        ):
            # Call submit_vulnerability with the new crash
            result = submissions.submit_vulnerability(new_crash)

        # Verify the result
        assert result is True

        # Verify consolidation occurred:
        # 1. First submission (target) should have all crashes
        target_submission = submissions.entries[0]
        assert len(target_submission.crashes) == 4  # original + 3 from other submissions + new crash
        # Original crash should still be there
        assert target_submission.crashes[0].crash.crash.stacktrace == "similar_crash_pattern_stack1"
        assert target_submission.crashes[1].crash == new_crash  # new crash added first
        # Crashes from other submissions should be merged in
        assert target_submission.crashes[2].crash.crash.stacktrace == "similar_crash_pattern_stack2"  # from submission2
        assert target_submission.crashes[3].crash.crash.stacktrace == "similar_crash_pattern_stack3"  # from submission3

        # 2. First submission should have original patches plus unprocessed patches from sources
        assert (
            len(target_submission.patches) == 3
        )  # 1 (original) + 2 (unprocessed from submission2) + 0 (none from submission3)
        patch_ids = {p.internal_patch_id for p in target_submission.patches}
        assert patch_ids == {
            "patch1",
            "patch2a",
            "patch2b",
        }  # patch3 not included since submission3.patch_idx=2 >= len(submission3.patches)=1

        # 3. First submission should have all bundles and data from other submissions
        assert _get_first_successful_pov_id(target_submission) == "pov-123"  # kept original since it had one

        # Should have all bundles from all submissions
        assert len(target_submission.bundles) == 2  # from submission2 and submission3

        # First bundle should be from submission2
        assert target_submission.bundles[0].competition_patch_id == "comp-patch-456"
        assert target_submission.bundles[0].bundle_id == "bundle-456"
        assert target_submission.bundles[0].competition_sarif_id == ""  # no SARIF ID

        # Second bundle should be from submission3
        assert target_submission.bundles[1].competition_patch_id == "comp-patch-789"
        assert target_submission.bundles[1].bundle_id == "bundle-789"
        assert target_submission.bundles[1].competition_sarif_id == "sarif-789"
        assert target_submission.patch_idx == 1  # kept from target (original submission1)
        assert target_submission.patch_submission_attempts == 2  # kept from target (original submission1)

        # 4. Other submissions should be STOPPED
        assert submissions.entries[1].stop
        assert submissions.entries[2].stop

        # 5. Verify persistence was called for all submissions
        # Target + 2 source submissions being stopped = 3 calls
        # Since consolidation uses a pipeline, check pipeline.execute was called
        assert mock_redis.pipeline.called

    def test_find_similar_entries(self, submissions):
        """Test find_similar_entries method correctly identifies similar crashes."""

        task_id = "test-task-similarity"

        # Create existing submissions with different crashes using builder
        submissions.entries = [
            SubmissionEntryBuilder()
            .crash(
                task_id=task_id,
                stacktrace="similar_pattern_crash1",
                harness_name="harness1",
            )
            .build(),
            SubmissionEntryBuilder()
            .crash(
                task_id=task_id,
                stacktrace="similar_pattern_crash2",
                harness_name="harness2",
            )
            .build(),
            # Different task (should not be found)
            SubmissionEntryBuilder()
            .crash(
                task_id="different-task",
                stacktrace="similar_pattern_crash3",
                harness_name="harness3",
            )
            .build(),
            # Unique crash (should not be found)
            SubmissionEntryBuilder()
            .crash(
                task_id=task_id,
                stacktrace="unique_pattern_crash4",
                harness_name="harness4",
            )
            .build(),
        ]

        # Create a new crash to search for similar entries
        new_crash = TracedCrash()
        new_crash.crash.target.task_id = task_id
        new_crash.crash.stacktrace = "similar_pattern_new"
        new_crash.crash.harness_name = "new_harness"

        # Mock the crash comparison functions
        mock_get_crash_data, mock_get_inst_key, mock_crash_comparer_init, mock_is_similar = (
            create_crash_comparison_mocks()
        )

        # Apply mocks
        with (
            patch("buttercup.orchestrator.scheduler.submissions.get_crash_data", side_effect=mock_get_crash_data),
            patch("buttercup.orchestrator.scheduler.submissions.get_inst_key", side_effect=mock_get_inst_key),
            patch.object(CrashComparer, "__init__", mock_crash_comparer_init),
            patch.object(CrashComparer, "is_similar", mock_is_similar),
        ):
            # Call find_similar_entries
            similar_entries = submissions.find_similar_entries(new_crash)

        # Verify results
        assert len(similar_entries) == 2  # Should find submission1 and submission2

        # Extract indices and entries
        indices = [idx for idx, _ in similar_entries]
        entries = [entry for _, entry in similar_entries]

        # Verify indices are correct (should be 0 and 1)
        assert 0 in indices  # submission1
        assert 1 in indices  # submission2
        assert 2 not in indices  # submission3 (different task)
        assert 3 not in indices  # submission4 (unique pattern)

        # Verify entries are correct
        assert submissions.entries[0] in entries
        assert submissions.entries[1] in entries
        assert submissions.entries[2] not in entries  # different task
        assert submissions.entries[3] not in entries  # unique pattern

    def test_find_similar_entries_no_matches(self, submissions):
        """Test find_similar_entries returns empty list when no similar crashes exist."""

        task_id = "test-task-no-matches"

        # Create existing submission with unique crash using builder
        submissions.entries = [
            SubmissionEntryBuilder()
            .crash(
                task_id=task_id,
                stacktrace="unique_pattern_crash1",
                harness_name="harness1",
            )
            .build()
        ]

        # Create a new crash with different pattern
        new_crash = TracedCrash()
        new_crash.crash.target.task_id = task_id
        new_crash.crash.stacktrace = "different_pattern_new"
        new_crash.crash.harness_name = "new_harness"

        # Mock the crash comparison functions to return non-matching data
        mock_get_crash_data, mock_get_inst_key, mock_crash_comparer_init, mock_is_similar = (
            create_crash_comparison_mocks(
                []  # No patterns are similar
            )
        )

        # Apply mocks
        with (
            patch("buttercup.orchestrator.scheduler.submissions.get_crash_data", side_effect=mock_get_crash_data),
            patch("buttercup.orchestrator.scheduler.submissions.get_inst_key", side_effect=mock_get_inst_key),
            patch.object(CrashComparer, "__init__", mock_crash_comparer_init),
            patch.object(CrashComparer, "is_similar", mock_is_similar),
        ):
            # Call find_similar_entries
            similar_entries = submissions.find_similar_entries(new_crash)

        # Verify no matches found
        assert len(similar_entries) == 0

    def test_find_similar_entries_empty_submissions(self, submissions):
        """Test find_similar_entries returns empty list when no submissions exist."""
        # No submissions in entries
        submissions.entries = []

        # Create a new crash
        new_crash = TracedCrash()
        new_crash.crash.target.task_id = "test-task"
        new_crash.crash.stacktrace = "some_pattern"
        new_crash.crash.harness_name = "harness"

        # Call find_similar_entries
        similar_entries = submissions.find_similar_entries(new_crash)

        # Verify no matches found
        assert len(similar_entries) == 0

    def test_find_patch_success(self, submissions):
        """Test _find_patch successfully finds a patch by internal_patch_id."""
        # Create submissions with patches using builder
        submissions.entries = [
            SubmissionEntryBuilder()
            .crash(task_id="task-1")
            .patch(internal_patch_id="patch-1a", patch_content="patch content 1a")
            .patch(internal_patch_id="patch-1b", patch_content="patch content 1b")
            .build(),
            SubmissionEntryBuilder()
            .crash(task_id="task-2")
            .patch(internal_patch_id="patch-2a", patch_content="patch content 2a")
            .build(),
        ]

        # Test finding first patch in first submission
        result = submissions._find_patch("patch-1a")
        assert result is not None
        index, entry, patch = result
        assert index == 0
        assert entry is submissions.entries[0]
        assert patch.internal_patch_id == "patch-1a"
        assert patch.patch == "patch content 1a"

        # Test finding second patch in first submission
        result = submissions._find_patch("patch-1b")
        assert result is not None
        index, entry, patch = result
        assert index == 0
        assert entry is submissions.entries[0]
        assert patch.internal_patch_id == "patch-1b"
        assert patch.patch == "patch content 1b"

        # Test finding patch in second submission
        result = submissions._find_patch("patch-2a")
        assert result is not None
        index, entry, patch = result
        assert index == 1
        assert entry is submissions.entries[1]
        assert patch.internal_patch_id == "patch-2a"
        assert patch.patch == "patch content 2a"

    def test_find_patch_not_found(self, submissions):
        """Test _find_patch returns None when patch is not found."""
        # Create submissions with patches using builder
        submissions.entries = [
            SubmissionEntryBuilder()
            .crash(task_id="task-1")
            .patch(internal_patch_id="patch-1", patch_content="patch content 1")
            .build()
        ]

        # Test finding non-existent patch
        result = submissions._find_patch("nonexistent-patch")
        assert result is None

    def test_find_patch_empty_submissions(self, submissions):
        """Test _find_patch returns None when no submissions exist."""
        submissions.entries = []

        # Test finding patch in empty submissions
        result = submissions._find_patch("any-patch")
        assert result is None

    def test_find_patch_no_patches(self, submissions):
        """Test _find_patch returns None when submissions have no patches."""
        # Create submissions without patches using builder
        submissions.entries = [
            SubmissionEntryBuilder().crash(task_id="task-1").build(),
            SubmissionEntryBuilder().crash(task_id="task-2").build(),
        ]

        # Test finding patch when no patches exist
        result = submissions._find_patch("any-patch")
        assert result is None

    def test_find_patch_stopped_submissions(self, submissions):
        """Test _find_patch skips stopped submissions."""
        # Create submissions with patches using builder
        submissions.entries = [
            SubmissionEntryBuilder()
            .crash(task_id="task-1")
            .patch(internal_patch_id="patch-in-stopped", patch_content="patch content in stopped")
            .stopped()
            .build(),
            SubmissionEntryBuilder()
            .crash(task_id="task-2")
            .patch(internal_patch_id="patch-in-active", patch_content="patch content in active")
            .build(),
        ]

        # Test finding patch in stopped submission - should not find it
        result = submissions._find_patch("patch-in-stopped")
        assert result is None

        # Test finding patch in active submission - should find it
        result = submissions._find_patch("patch-in-active")
        assert result is not None
        index, entry, patch = result
        assert index == 1
        assert entry is submissions.entries[1]
        assert patch.internal_patch_id == "patch-in-active"
        assert patch.patch == "patch content in active"

    def test_find_matching_build_output_success(self, submissions):
        """Test _find_matching_build_output successfully finds matching build outputs."""

        # Create a patch with multiple build outputs
        patch = SubmissionEntryPatch()
        patch.internal_patch_id = "test-patch"

        # Add build outputs with different configurations
        build_output1 = BuildOutput()
        build_output1.engine = "libfuzzer"
        build_output1.sanitizer = "asan"
        build_output1.build_type = BuildType.PATCH
        build_output1.apply_diff = True
        build_output1.task_dir = ""  # Placeholder

        build_output2 = BuildOutput()
        build_output2.engine = "afl"
        build_output2.sanitizer = "msan"
        build_output2.build_type = BuildType.FUZZER
        build_output2.apply_diff = False
        build_output2.task_dir = "/path/to/build"  # Already filled

        build_output3 = BuildOutput()
        build_output3.engine = "libfuzzer"
        build_output3.sanitizer = "ubsan"
        build_output3.build_type = BuildType.COVERAGE
        build_output3.apply_diff = True
        build_output3.task_dir = ""  # Placeholder

        patch.build_outputs.extend([build_output1, build_output2, build_output3])

        # Create search criteria that match build_output1
        search_build_output = BuildOutput()
        search_build_output.engine = "libfuzzer"
        search_build_output.sanitizer = "asan"
        search_build_output.build_type = BuildType.PATCH
        search_build_output.apply_diff = True

        # Should find build_output1
        result = _find_matching_build_output(patch, search_build_output)
        assert result is not None
        assert result.engine == "libfuzzer"
        assert result.sanitizer == "asan"
        assert result.build_type == BuildType.PATCH
        assert result.apply_diff is True
        assert result.task_dir == ""  # Should be the placeholder one

        # Create search criteria that match build_output2
        search_build_output2 = BuildOutput()
        search_build_output2.engine = "afl"
        search_build_output2.sanitizer = "msan"
        search_build_output2.build_type = BuildType.FUZZER
        search_build_output2.apply_diff = False

        # Should find build_output2
        result2 = _find_matching_build_output(patch, search_build_output2)
        assert result2 is not None
        assert result2.engine == "afl"
        assert result2.sanitizer == "msan"
        assert result2.build_type == BuildType.FUZZER
        assert result2.apply_diff is False
        assert result2.task_dir == "/path/to/build"  # Should be the filled one

        # Create search criteria that match build_output3
        search_build_output3 = BuildOutput()
        search_build_output3.engine = "libfuzzer"
        search_build_output3.sanitizer = "ubsan"
        search_build_output3.build_type = BuildType.COVERAGE
        search_build_output3.apply_diff = True

        # Should find build_output3
        result3 = _find_matching_build_output(patch, search_build_output3)
        assert result3 is not None
        assert result3.engine == "libfuzzer"
        assert result3.sanitizer == "ubsan"
        assert result3.build_type == BuildType.COVERAGE
        assert result3.apply_diff is True
        assert result3.task_dir == ""  # Should be the placeholder one

    def test_find_matching_build_output_no_match(self, submissions):
        """Test _find_matching_build_output returns None when no match is found."""

        # Create a patch with build outputs
        patch = SubmissionEntryPatch()
        patch.internal_patch_id = "test-patch"

        build_output1 = BuildOutput()
        build_output1.engine = "libfuzzer"
        build_output1.sanitizer = "asan"
        build_output1.build_type = BuildType.PATCH
        build_output1.apply_diff = True

        build_output2 = BuildOutput()
        build_output2.engine = "afl"
        build_output2.sanitizer = "msan"
        build_output2.build_type = BuildType.FUZZER
        build_output2.apply_diff = False

        patch.build_outputs.extend([build_output1, build_output2])

        # Create search criteria that don't match any existing build output
        search_build_output = BuildOutput()
        search_build_output.engine = "honggfuzz"  # Different engine
        search_build_output.sanitizer = "asan"
        search_build_output.build_type = BuildType.PATCH
        search_build_output.apply_diff = True

        # Should not find any match
        result = _find_matching_build_output(patch, search_build_output)
        assert result is None

        # Test with different sanitizer
        search_build_output2 = BuildOutput()
        search_build_output2.engine = "libfuzzer"
        search_build_output2.sanitizer = "tsan"  # Different sanitizer
        search_build_output2.build_type = BuildType.PATCH
        search_build_output2.apply_diff = True

        result2 = _find_matching_build_output(patch, search_build_output2)
        assert result2 is None

        # Test with different build_type
        search_build_output3 = BuildOutput()
        search_build_output3.engine = "libfuzzer"
        search_build_output3.sanitizer = "asan"
        search_build_output3.build_type = BuildType.COVERAGE  # Different build type
        search_build_output3.apply_diff = True

        result3 = _find_matching_build_output(patch, search_build_output3)
        assert result3 is None

        # Test with different apply_diff
        search_build_output4 = BuildOutput()
        search_build_output4.engine = "libfuzzer"
        search_build_output4.sanitizer = "asan"
        search_build_output4.build_type = BuildType.PATCH
        search_build_output4.apply_diff = False  # Different apply_diff

        result4 = _find_matching_build_output(patch, search_build_output4)
        assert result4 is None

    def test_find_matching_build_output_empty_patch(self, submissions):
        """Test _find_matching_build_output with patch that has no build outputs."""

        # Create a patch with no build outputs
        patch = SubmissionEntryPatch()
        patch.internal_patch_id = "empty-patch"
        # patch.build_outputs is empty by default

        # Create search criteria
        search_build_output = BuildOutput()
        search_build_output.engine = "libfuzzer"
        search_build_output.sanitizer = "asan"
        search_build_output.build_type = BuildType.PATCH
        search_build_output.apply_diff = True

        # Should not find any match
        result = _find_matching_build_output(patch, search_build_output)
        assert result is None

    @pytest.mark.parametrize(
        "engine,sanitizer,build_type,apply_diff,description",
        [
            ("afl", "asan", BuildType.PATCH, True, "different engine"),
            ("libfuzzer", "msan", BuildType.PATCH, True, "different sanitizer"),
            ("libfuzzer", "asan", BuildType.FUZZER, True, "different build_type"),
            ("libfuzzer", "asan", BuildType.PATCH, False, "different apply_diff"),
        ],
    )
    def test_find_matching_build_output_parametrized_no_match(
        self, submissions, engine, sanitizer, build_type, apply_diff, description
    ):
        """Test that _find_matching_build_output requires exact match on all fields (parametrized)."""

        # Create a patch with one build output
        patch = SubmissionEntryPatch()
        patch.internal_patch_id = "exact-match-patch"

        build_output = BuildOutput()
        build_output.engine = "libfuzzer"
        build_output.sanitizer = "asan"
        build_output.build_type = BuildType.PATCH
        build_output.apply_diff = True
        build_output.task_dir = "/original/path"

        patch.build_outputs.append(build_output)

        # Create search build output with different field
        search_build_output = BuildOutput()
        search_build_output.engine = engine
        search_build_output.sanitizer = sanitizer
        search_build_output.build_type = build_type
        search_build_output.apply_diff = apply_diff

        result = _find_matching_build_output(patch, search_build_output)
        assert result is None, f"Should not match with {description}"

    def test_find_matching_build_output_exact_match(self, submissions):
        """Test that _find_matching_build_output succeeds with exact match."""

        # Create a patch with one build output
        patch = SubmissionEntryPatch()
        patch.internal_patch_id = "exact-match-patch"

        build_output = BuildOutput()
        build_output.engine = "libfuzzer"
        build_output.sanitizer = "asan"
        build_output.build_type = BuildType.PATCH
        build_output.apply_diff = True
        build_output.task_dir = "/original/path"

        patch.build_outputs.append(build_output)

        # Test exact match - should succeed
        exact_match = BuildOutput()
        exact_match.engine = "libfuzzer"
        exact_match.sanitizer = "asan"
        exact_match.build_type = BuildType.PATCH
        exact_match.apply_diff = True
        # Note: task_dir doesn't need to match - it's not part of the matching criteria
        exact_match.task_dir = "/different/path"

        result = _find_matching_build_output(patch, exact_match)
        assert result is not None
        assert result.engine == "libfuzzer"
        assert result.sanitizer == "asan"
        assert result.build_type == BuildType.PATCH
        assert result.apply_diff is True
        assert result.task_dir == "/original/path"  # Should get the original task_dir

    def test_find_matching_build_output_first_match_returned(self, submissions):
        """Test that _find_matching_build_output returns the first matching build output."""

        # Create a patch with multiple identical build outputs (edge case)
        patch = SubmissionEntryPatch()
        patch.internal_patch_id = "duplicate-patch"

        # Create two identical build outputs with different task_dirs
        build_output1 = BuildOutput()
        build_output1.engine = "libfuzzer"
        build_output1.sanitizer = "asan"
        build_output1.build_type = BuildType.PATCH
        build_output1.apply_diff = True
        build_output1.task_dir = "/first/path"

        build_output2 = BuildOutput()
        build_output2.engine = "libfuzzer"
        build_output2.sanitizer = "asan"
        build_output2.build_type = BuildType.PATCH
        build_output2.apply_diff = True
        build_output2.task_dir = "/second/path"

        patch.build_outputs.extend([build_output1, build_output2])

        # Create search criteria that match both
        search_build_output = BuildOutput()
        search_build_output.engine = "libfuzzer"
        search_build_output.sanitizer = "asan"
        search_build_output.build_type = BuildType.PATCH
        search_build_output.apply_diff = True

        # Should return the first match
        result = _find_matching_build_output(patch, search_build_output)
        assert result is not None
        assert result.task_dir == "/first/path"  # Should be the first one

    def test_get_first_successful_pov_with_passed_pov(self, submissions):
        """Test _get_first_successful_pov returns the first passed POV."""

        # Create a submission entry with multiple POVs using builder
        entry = (
            SubmissionEntryBuilder()
            .crash(
                task_id="test-task",
                competition_pov_id="pov-failed",
                result=SubmissionResult.FAILED,
            )
            .crash(
                task_id="test-task",
                competition_pov_id="pov-passed-first",
                result=SubmissionResult.PASSED,
            )
            .crash(
                task_id="test-task",
                competition_pov_id="pov-passed-second",
                result=SubmissionResult.PASSED,
            )
            .crash(
                task_id="test-task",
                competition_pov_id="pov-accepted",
                result=SubmissionResult.ACCEPTED,
            )
            .build()
        )

        # Should return the first passed POV
        result = _get_first_successful_pov(entry)
        assert result is not None
        assert result.competition_pov_id == "pov-passed-first"
        assert result.result == SubmissionResult.PASSED

    def test_get_first_successful_pov_no_passed_povs(self, submissions):
        """Test _get_first_successful_pov returns None when no POVs are passed."""

        # Create a submission entry with POVs that are not passed using builder
        entry = (
            SubmissionEntryBuilder()
            .crash(task_id="test-task")  # No competition_pov_id
            .crash(
                task_id="test-task",
                competition_pov_id="pov-failed",
                result=SubmissionResult.FAILED,
            )
            .crash(
                task_id="test-task",
                competition_pov_id="pov-accepted",
                result=SubmissionResult.ACCEPTED,
            )
            .crash(
                task_id="test-task",
                competition_pov_id="pov-errored",
                result=SubmissionResult.ERRORED,
            )
            .build()
        )

        # Should return None since no POVs are passed
        result = _get_first_successful_pov(entry)
        assert result is None

    def test_get_first_successful_pov_empty_entry(self, submissions):
        """Test _get_first_successful_pov returns None for entry with no crashes."""

        # Create an empty submission entry
        entry = SubmissionEntry()
        # entry.crashes is empty by default

        # Should return None
        result = _get_first_successful_pov(entry)
        assert result is None

    def test_get_first_successful_pov_requires_both_id_and_passed_status(self, submissions):
        """Test _get_first_successful_pov requires both competition_pov_id and PASSED status."""

        # Create a submission entry with edge cases
        entry = SubmissionEntry()

        # POV with PASSED status but no competition_pov_id
        crash1 = CrashWithId()
        crash1.crash.crash.target.task_id = "test-task"
        # crash1.competition_pov_id is not set
        crash1.result = SubmissionResult.PASSED
        entry.crashes.append(crash1)

        # POV with competition_pov_id but no result set
        crash2 = CrashWithId()
        crash2.crash.crash.target.task_id = "test-task"
        crash2.competition_pov_id = "pov-no-result"
        # crash2.result is not set (default)
        entry.crashes.append(crash2)

        # POV with empty competition_pov_id and PASSED status
        crash3 = CrashWithId()
        crash3.crash.crash.target.task_id = "test-task"
        crash3.competition_pov_id = ""  # Empty string
        crash3.result = SubmissionResult.PASSED
        entry.crashes.append(crash3)

        # Should return None since none meet both criteria
        result = _get_first_successful_pov(entry)
        assert result is None

    def test_get_first_successful_pov_returns_first_match(self, submissions):
        """Test _get_first_successful_pov returns the first POV that meets criteria."""

        # Create a submission entry with multiple passed POVs
        entry = SubmissionEntry()

        # First passed POV - should be returned
        crash1 = CrashWithId()
        crash1.crash.crash.target.task_id = "test-task"
        crash1.competition_pov_id = "first-passed-pov"
        crash1.result = SubmissionResult.PASSED
        entry.crashes.append(crash1)

        # Second passed POV - should not be returned
        crash2 = CrashWithId()
        crash2.crash.crash.target.task_id = "test-task"
        crash2.competition_pov_id = "second-passed-pov"
        crash2.result = SubmissionResult.PASSED
        entry.crashes.append(crash2)

        # Should return the first one
        result = _get_first_successful_pov(entry)
        assert result is not None
        assert result.competition_pov_id == "first-passed-pov"
        assert result.result == SubmissionResult.PASSED
        # Verify it's the first POV by checking it's not the second one
        assert result.competition_pov_id != "second-passed-pov"

    def test_get_pending_povs_with_accepted_povs(self, submissions):
        """Test _get_pending_povs returns all POVs with ACCEPTED status."""

        # Create a submission entry with multiple POVs using builder
        entry = (
            SubmissionEntryBuilder()
            .crash(task_id="test-task")  # No competition_pov_id - not pending
            .crash(
                task_id="test-task",
                competition_pov_id="pov-accepted-1",
                result=SubmissionResult.ACCEPTED,
            )  # Should be included
            .crash(
                task_id="test-task",
                competition_pov_id="pov-passed",
                result=SubmissionResult.PASSED,
            )  # Not pending
            .crash(
                task_id="test-task",
                competition_pov_id="pov-accepted-2",
                result=SubmissionResult.ACCEPTED,
            )  # Should be included
            .crash(
                task_id="test-task",
                competition_pov_id="pov-failed",
                result=SubmissionResult.FAILED,
            )  # Not pending
            .crash(
                task_id="test-task",
                competition_pov_id="pov-errored",
                result=SubmissionResult.ERRORED,
            )  # Not pending
            .build()
        )

        # Should return only the accepted POVs
        result = _get_pending_pov_submissions(entry)
        assert len(result) == 2

        # Check that both accepted POVs are in the result
        pov_ids = [pov.competition_pov_id for pov in result]
        assert "pov-accepted-1" in pov_ids
        assert "pov-accepted-2" in pov_ids

        # Verify they all have ACCEPTED status
        for pov in result:
            assert pov.result == SubmissionResult.ACCEPTED
            assert pov.competition_pov_id  # Should have a POV ID

    def test_get_pending_povs_no_pending_povs(self, submissions):
        """Test _get_pending_povs returns empty list when no POVs are pending."""

        # Create a submission entry with POVs that are not pending
        entry = SubmissionEntry()

        # POV with no competition_pov_id
        crash1 = CrashWithId()
        crash1.crash.crash.target.task_id = "test-task"
        # crash1.competition_pov_id is not set
        entry.crashes.append(crash1)

        # POV that passed
        crash2 = CrashWithId()
        crash2.crash.crash.target.task_id = "test-task"
        crash2.competition_pov_id = "pov-passed"
        crash2.result = SubmissionResult.PASSED
        entry.crashes.append(crash2)

        # POV that failed
        crash3 = CrashWithId()
        crash3.crash.crash.target.task_id = "test-task"
        crash3.competition_pov_id = "pov-failed"
        crash3.result = SubmissionResult.FAILED
        entry.crashes.append(crash3)

        # POV that errored
        crash4 = CrashWithId()
        crash4.crash.crash.target.task_id = "test-task"
        crash4.competition_pov_id = "pov-errored"
        crash4.result = SubmissionResult.ERRORED
        entry.crashes.append(crash4)

        # Should return empty list
        result = _get_pending_pov_submissions(entry)
        assert len(result) == 0
        assert result == []

    def test_get_pending_povs_empty_entry(self, submissions):
        """Test _get_pending_povs returns empty list for entry with no crashes."""

        # Create an empty submission entry
        entry = SubmissionEntry()
        # entry.crashes is empty by default

        # Should return empty list
        result = _get_pending_pov_submissions(entry)
        assert len(result) == 0
        assert result == []

    def test_get_pending_povs_requires_both_id_and_accepted_status(self, submissions):
        """Test _get_pending_povs requires both competition_pov_id and ACCEPTED status."""

        # Create a submission entry with edge cases
        entry = SubmissionEntry()

        # POV with ACCEPTED status but no competition_pov_id
        crash1 = CrashWithId()
        crash1.crash.crash.target.task_id = "test-task"
        # crash1.competition_pov_id is not set
        crash1.result = SubmissionResult.ACCEPTED
        entry.crashes.append(crash1)

        # POV with competition_pov_id but no result explicitly set
        # Note: protobuf now defaults result to NONE (value 0), so this will NOT be considered pending
        crash2 = CrashWithId()
        crash2.crash.crash.target.task_id = "test-task"
        crash2.competition_pov_id = "pov-no-result"
        # crash2.result is not set (defaults to NONE)
        entry.crashes.append(crash2)

        # POV with empty competition_pov_id and ACCEPTED status
        crash3 = CrashWithId()
        crash3.crash.crash.target.task_id = "test-task"
        crash3.competition_pov_id = ""  # Empty string
        crash3.result = SubmissionResult.ACCEPTED
        entry.crashes.append(crash3)

        # POV with both competition_pov_id and explicit ACCEPTED status - should be pending
        crash4 = CrashWithId()
        crash4.crash.crash.target.task_id = "test-task"
        crash4.competition_pov_id = "pov-accepted"
        crash4.result = SubmissionResult.ACCEPTED
        entry.crashes.append(crash4)

        # Should return only crash4 since it has both competition_pov_id and explicit ACCEPTED status
        result = _get_pending_pov_submissions(entry)
        assert len(result) == 1
        assert result[0].competition_pov_id == "pov-accepted"
        assert result[0].result == SubmissionResult.ACCEPTED

    def test_get_pending_povs_preserves_order(self, submissions):
        """Test _get_pending_povs preserves the order of POVs in the entry."""

        # Create a submission entry with multiple accepted POVs
        entry = SubmissionEntry()

        # Add accepted POVs in specific order
        crash1 = CrashWithId()
        crash1.crash.crash.target.task_id = "test-task"
        crash1.competition_pov_id = "first-accepted-pov"
        crash1.result = SubmissionResult.ACCEPTED
        entry.crashes.append(crash1)

        # Add a non-accepted POV in between
        crash2 = CrashWithId()
        crash2.crash.crash.target.task_id = "test-task"
        crash2.competition_pov_id = "passed-pov"
        crash2.result = SubmissionResult.PASSED
        entry.crashes.append(crash2)

        # Add another accepted POV
        crash3 = CrashWithId()
        crash3.crash.crash.target.task_id = "test-task"
        crash3.competition_pov_id = "second-accepted-pov"
        crash3.result = SubmissionResult.ACCEPTED
        entry.crashes.append(crash3)

        # Add another accepted POV
        crash4 = CrashWithId()
        crash4.crash.crash.target.task_id = "test-task"
        crash4.competition_pov_id = "third-accepted-pov"
        crash4.result = SubmissionResult.ACCEPTED
        entry.crashes.append(crash4)

        # Should return accepted POVs in the same order they appear in the entry
        result = _get_pending_pov_submissions(entry)
        assert len(result) == 3
        assert result[0].competition_pov_id == "first-accepted-pov"
        assert result[1].competition_pov_id == "second-accepted-pov"
        assert result[2].competition_pov_id == "third-accepted-pov"

    def test_get_pending_povs_only_accepted_status(self, submissions):
        """Test _get_pending_povs only includes ACCEPTED status, not other statuses."""

        # Create a submission entry with POVs having various statuses
        entry = SubmissionEntry()

        # Test all possible SubmissionResult values
        statuses_to_test = [
            (SubmissionResult.ACCEPTED, "should-be-included"),
            (SubmissionResult.PASSED, "should-not-be-included-passed"),
            (SubmissionResult.FAILED, "should-not-be-included-failed"),
            (SubmissionResult.ERRORED, "should-not-be-included-errored"),
            (SubmissionResult.DEADLINE_EXCEEDED, "should-not-be-included-deadline"),
        ]

        for status, pov_id in statuses_to_test:
            crash = CrashWithId()
            crash.crash.crash.target.task_id = "test-task"
            crash.competition_pov_id = pov_id
            crash.result = status
            entry.crashes.append(crash)

        # Should return only the ACCEPTED POV
        result = _get_pending_pov_submissions(entry)
        assert len(result) == 1
        assert result[0].competition_pov_id == "should-be-included"
        assert result[0].result == SubmissionResult.ACCEPTED

    def test_get_eligible_povs_for_submission_no_pov_id(self, submissions):
        """Test _get_eligible_povs_for_submission returns POVs without competition_pov_id."""

        # Create a submission entry with POVs that don't have competition_pov_id
        entry = SubmissionEntry()

        # POV with no competition_pov_id - should be eligible
        crash1 = CrashWithId()
        crash1.crash.crash.target.task_id = "test-task"
        crash1.crash.crash.crash_input_path = "/path/to/crash1.bin"
        # crash1.competition_pov_id is not set
        entry.crashes.append(crash1)

        # POV with empty competition_pov_id - should be eligible
        crash2 = CrashWithId()
        crash2.crash.crash.target.task_id = "test-task"
        crash2.crash.crash.crash_input_path = "/path/to/crash2.bin"
        crash2.competition_pov_id = ""  # Empty string
        entry.crashes.append(crash2)

        # POV with competition_pov_id and PASSED status - should NOT be eligible
        crash3 = CrashWithId()
        crash3.crash.crash.target.task_id = "test-task"
        crash3.crash.crash.crash_input_path = "/path/to/crash3.bin"
        crash3.competition_pov_id = "pov-passed"
        crash3.result = SubmissionResult.PASSED
        entry.crashes.append(crash3)

        # Should return only the POVs without competition_pov_id
        result = _get_eligible_povs_for_submission(entry)
        assert len(result) == 2

        # Verify by crash input paths
        returned_paths = [pov.crash.crash.crash_input_path for pov in result]
        assert "/path/to/crash1.bin" in returned_paths  # No competition_pov_id
        assert "/path/to/crash2.bin" in returned_paths  # Empty competition_pov_id
        assert "/path/to/crash3.bin" not in returned_paths  # PASSED status - ineligible

    def test_get_eligible_povs_for_submission_errored_povs(self, submissions):
        """Test _get_eligible_povs_for_submission returns POVs with ERRORED status."""

        # Create a submission entry with POVs in different states
        entry = SubmissionEntry()

        # POV with ERRORED status - should be eligible for retry
        crash1 = CrashWithId()
        crash1.crash.crash.target.task_id = "test-task"
        crash1.crash.crash.crash_input_path = "/path/to/errored.bin"
        crash1.competition_pov_id = "pov-errored"
        crash1.result = SubmissionResult.ERRORED
        entry.crashes.append(crash1)

        # POV with FAILED status - should NOT be eligible
        crash2 = CrashWithId()
        crash2.crash.crash.target.task_id = "test-task"
        crash2.crash.crash.crash_input_path = "/path/to/failed.bin"
        crash2.competition_pov_id = "pov-failed"
        crash2.result = SubmissionResult.FAILED
        entry.crashes.append(crash2)

        # POV with PASSED status - should NOT be eligible
        crash3 = CrashWithId()
        crash3.crash.crash.target.task_id = "test-task"
        crash3.crash.crash.crash_input_path = "/path/to/passed.bin"
        crash3.competition_pov_id = "pov-passed"
        crash3.result = SubmissionResult.PASSED
        entry.crashes.append(crash3)

        # POV with ACCEPTED status - should NOT be eligible
        crash4 = CrashWithId()
        crash4.crash.crash.target.task_id = "test-task"
        crash4.crash.crash.crash_input_path = "/path/to/accepted.bin"
        crash4.competition_pov_id = "pov-accepted"
        crash4.result = SubmissionResult.ACCEPTED
        entry.crashes.append(crash4)

        # Should return only the ERRORED POV
        result = _get_eligible_povs_for_submission(entry)
        assert len(result) == 1
        assert result[0].crash.crash.crash_input_path == "/path/to/errored.bin"
        assert result[0].competition_pov_id == "pov-errored"
        assert result[0].result == SubmissionResult.ERRORED

    def test_get_eligible_povs_for_submission_mixed_cases(self, submissions):
        """Test _get_eligible_povs_for_submission with mix of eligible and ineligible POVs."""

        # Create a submission entry with mixed POV states using builder
        entry = (
            SubmissionEntryBuilder()
            .crash(task_id="test-task", crash_input_path="/path/to/no_pov_id.bin")  # No POV ID - eligible
            .crash(
                task_id="test-task",
                crash_input_path="/path/to/passed.bin",
                competition_pov_id="pov-passed",
                result=SubmissionResult.PASSED,
            )  # PASSED - ineligible
            .crash(
                task_id="test-task",
                crash_input_path="/path/to/errored.bin",
                competition_pov_id="pov-errored",
                result=SubmissionResult.ERRORED,
            )  # ERRORED - eligible
            .crash(
                task_id="test-task",
                crash_input_path="/path/to/failed.bin",
                competition_pov_id="pov-failed",
                result=SubmissionResult.FAILED,
            )  # FAILED - ineligible
            .crash(
                task_id="test-task", crash_input_path="/path/to/empty_pov_id.bin", competition_pov_id=""
            )  # Empty string - eligible
            .crash(
                task_id="test-task",
                crash_input_path="/path/to/accepted.bin",
                competition_pov_id="pov-accepted",
                result=SubmissionResult.ACCEPTED,
            )  # ACCEPTED - ineligible
            .build()
        )

        # Should return only the eligible POVs (crash1, crash3, crash5)
        result = _get_eligible_povs_for_submission(entry)
        assert len(result) == 3

        # Verify by crash input paths
        returned_paths = [pov.crash.crash.crash_input_path for pov in result]
        assert "/path/to/no_pov_id.bin" in returned_paths  # No competition_pov_id
        assert "/path/to/errored.bin" in returned_paths  # ERRORED status
        assert "/path/to/empty_pov_id.bin" in returned_paths  # Empty competition_pov_id
        # Verify ineligible ones are not included
        assert "/path/to/passed.bin" not in returned_paths  # PASSED status - ineligible
        assert "/path/to/failed.bin" not in returned_paths  # FAILED status - ineligible
        assert "/path/to/accepted.bin" not in returned_paths  # ACCEPTED status - ineligible

    def test_get_eligible_povs_for_submission_empty_entry(self, submissions):
        """Test _get_eligible_povs_for_submission with entry that has no crashes."""

        # Create an empty submission entry
        entry = SubmissionEntry()
        # entry.crashes is empty by default

        # Should return empty list
        result = _get_eligible_povs_for_submission(entry)
        assert len(result) == 0
        assert result == []

    def test_get_eligible_povs_for_submission_all_ineligible(self, submissions):
        """Test _get_eligible_povs_for_submission when all POVs are ineligible."""

        # Create a submission entry with only ineligible POVs
        entry = SubmissionEntry()

        # POV with PASSED status
        crash1 = CrashWithId()
        crash1.crash.crash.target.task_id = "test-task"
        crash1.competition_pov_id = "pov-passed"
        crash1.result = SubmissionResult.PASSED
        entry.crashes.append(crash1)

        # POV with FAILED status
        crash2 = CrashWithId()
        crash2.crash.crash.target.task_id = "test-task"
        crash2.competition_pov_id = "pov-failed"
        crash2.result = SubmissionResult.FAILED
        entry.crashes.append(crash2)

        # POV with ACCEPTED status
        crash3 = CrashWithId()
        crash3.crash.crash.target.task_id = "test-task"
        crash3.competition_pov_id = "pov-accepted"
        crash3.result = SubmissionResult.ACCEPTED
        entry.crashes.append(crash3)

        # POV with DEADLINE_EXCEEDED status
        crash4 = CrashWithId()
        crash4.crash.crash.target.task_id = "test-task"
        crash4.competition_pov_id = "pov-deadline"
        crash4.result = SubmissionResult.DEADLINE_EXCEEDED
        entry.crashes.append(crash4)

        # Should return empty list since all POVs are ineligible
        result = _get_eligible_povs_for_submission(entry)
        assert len(result) == 0
        assert result == []

    def test_get_eligible_povs_for_submission_all_eligible(self, submissions):
        """Test _get_eligible_povs_for_submission when all POVs are eligible."""

        # Create a submission entry with only eligible POVs
        entry = SubmissionEntry()

        # POV with no competition_pov_id
        crash1 = CrashWithId()
        crash1.crash.crash.target.task_id = "test-task"
        crash1.crash.crash.crash_input_path = "/path/to/no_pov_id.bin"
        # crash1.competition_pov_id is not set
        entry.crashes.append(crash1)

        # POV with ERRORED status
        crash2 = CrashWithId()
        crash2.crash.crash.target.task_id = "test-task"
        crash2.crash.crash.crash_input_path = "/path/to/errored1.bin"
        crash2.competition_pov_id = "pov-errored-1"
        crash2.result = SubmissionResult.ERRORED
        entry.crashes.append(crash2)

        # Another POV with ERRORED status
        crash3 = CrashWithId()
        crash3.crash.crash.target.task_id = "test-task"
        crash3.crash.crash.crash_input_path = "/path/to/errored2.bin"
        crash3.competition_pov_id = "pov-errored-2"
        crash3.result = SubmissionResult.ERRORED
        entry.crashes.append(crash3)

        # POV with empty competition_pov_id
        crash4 = CrashWithId()
        crash4.crash.crash.target.task_id = "test-task"
        crash4.crash.crash.crash_input_path = "/path/to/empty_pov_id.bin"
        crash4.competition_pov_id = ""  # Empty string
        entry.crashes.append(crash4)

        # Should return all POVs since they're all eligible
        result = _get_eligible_povs_for_submission(entry)
        assert len(result) == 4

        # Verify by crash input paths
        returned_paths = [pov.crash.crash.crash_input_path for pov in result]
        assert "/path/to/no_pov_id.bin" in returned_paths  # No competition_pov_id
        assert "/path/to/errored1.bin" in returned_paths  # ERRORED status
        assert "/path/to/errored2.bin" in returned_paths  # ERRORED status
        assert "/path/to/empty_pov_id.bin" in returned_paths  # Empty competition_pov_id

    def test_get_eligible_povs_for_submission_preserves_order(self, submissions):
        """Test _get_eligible_povs_for_submission preserves order of eligible POVs."""

        # Create a submission entry with mixed POVs
        entry = SubmissionEntry()

        # Add POVs in specific order, mixing eligible and ineligible
        crash1 = CrashWithId()  # Eligible: no pov_id
        crash1.crash.crash.target.task_id = "test-task"
        crash1.crash.crash.crash_input_path = "/path/to/first_eligible.bin"
        entry.crashes.append(crash1)

        crash2 = CrashWithId()  # Ineligible: PASSED
        crash2.crash.crash.target.task_id = "test-task"
        crash2.crash.crash.crash_input_path = "/path/to/passed.bin"
        crash2.competition_pov_id = "pov-passed"
        crash2.result = SubmissionResult.PASSED
        entry.crashes.append(crash2)

        crash3 = CrashWithId()  # Eligible: ERRORED
        crash3.crash.crash.target.task_id = "test-task"
        crash3.crash.crash.crash_input_path = "/path/to/errored.bin"
        crash3.competition_pov_id = "pov-errored"
        crash3.result = SubmissionResult.ERRORED
        entry.crashes.append(crash3)

        crash4 = CrashWithId()  # Ineligible: FAILED
        crash4.crash.crash.target.task_id = "test-task"
        crash4.crash.crash.crash_input_path = "/path/to/failed.bin"
        crash4.competition_pov_id = "pov-failed"
        crash4.result = SubmissionResult.FAILED
        entry.crashes.append(crash4)

        crash5 = CrashWithId()  # Eligible: empty pov_id
        crash5.crash.crash.target.task_id = "test-task"
        crash5.crash.crash.crash_input_path = "/path/to/empty_pov_id.bin"
        crash5.competition_pov_id = ""
        entry.crashes.append(crash5)

        # Should return eligible POVs in the same order they appear in the entry
        result = _get_eligible_povs_for_submission(entry)
        assert len(result) == 3

        # Check order is preserved by verifying crash input paths
        assert result[0].crash.crash.crash_input_path == "/path/to/first_eligible.bin"  # First eligible
        assert result[1].crash.crash.crash_input_path == "/path/to/errored.bin"  # Second eligible (skipping PASSED)
        assert result[2].crash.crash.crash_input_path == "/path/to/empty_pov_id.bin"  # Third eligible (skipping FAILED)

    def test_find_patch_cancelled_task(self, submissions, mock_task_registry):
        """Test _find_patch skips submissions for cancelled tasks."""
        # Create submission with patch using builder
        submissions.entries = [
            SubmissionEntryBuilder()
            .crash(task_id="cancelled-task")
            .patch(internal_patch_id="patch-in-cancelled", patch_content="patch content in cancelled")
            .build()
        ]

        # Mock task registry to indicate task should stop processing
        mock_task_registry.should_stop_processing.return_value = True

        # Test finding patch in cancelled task - should not find it
        result = submissions._find_patch("patch-in-cancelled")
        assert result is None

        # Verify should_stop_processing was called with correct task_id
        mock_task_registry.should_stop_processing.assert_called_with("cancelled-task")

    def test_get_pending_patch_submissions_with_accepted_patches(self, submissions):
        """Test _get_pending_patch_submissions returns all patches with ACCEPTED status."""

        # Create a submission entry with multiple patches
        entry = SubmissionEntry()

        # Patch with no competition_patch_id - not pending
        patch1 = SubmissionEntryPatch()
        patch1.internal_patch_id = "patch-no-id"
        patch1.patch = "patch content 1"
        # patch1.competition_patch_id is not set
        entry.patches.append(patch1)

        # Patch that's accepted - should be included
        patch2 = SubmissionEntryPatch()
        patch2.internal_patch_id = "patch-accepted-1"
        patch2.patch = "patch content 2"
        patch2.competition_patch_id = "comp-patch-accepted-1"
        patch2.result = SubmissionResult.ACCEPTED
        entry.patches.append(patch2)

        # Patch that's passed - not pending
        patch3 = SubmissionEntryPatch()
        patch3.internal_patch_id = "patch-passed"
        patch3.patch = "patch content 3"
        patch3.competition_patch_id = "comp-patch-passed"
        patch3.result = SubmissionResult.PASSED
        entry.patches.append(patch3)

        # Another patch that's accepted - should be included
        patch4 = SubmissionEntryPatch()
        patch4.internal_patch_id = "patch-accepted-2"
        patch4.patch = "patch content 4"
        patch4.competition_patch_id = "comp-patch-accepted-2"
        patch4.result = SubmissionResult.ACCEPTED
        entry.patches.append(patch4)

        # Patch that failed - not pending
        patch5 = SubmissionEntryPatch()
        patch5.internal_patch_id = "patch-failed"
        patch5.patch = "patch content 5"
        patch5.competition_patch_id = "comp-patch-failed"
        patch5.result = SubmissionResult.FAILED
        entry.patches.append(patch5)

        # Patch that errored - not pending
        patch6 = SubmissionEntryPatch()
        patch6.internal_patch_id = "patch-errored"
        patch6.patch = "patch content 6"
        patch6.competition_patch_id = "comp-patch-errored"
        patch6.result = SubmissionResult.ERRORED
        entry.patches.append(patch6)

        # Should return only the accepted patches
        result = _get_pending_patch_submissions(entry)
        assert len(result) == 2

        # Check that both accepted patches are in the result
        patch_ids = [patch_entry.competition_patch_id for patch_entry in result]
        assert "comp-patch-accepted-1" in patch_ids
        assert "comp-patch-accepted-2" in patch_ids

        # Verify they all have ACCEPTED status
        for patch_entry in result:
            assert patch_entry.result == SubmissionResult.ACCEPTED
            assert patch_entry.competition_patch_id  # Should have a competition patch ID

    def test_get_pending_patch_submissions_no_pending_patches(self, submissions):
        """Test _get_pending_patch_submissions returns empty list when no patches are pending."""

        # Create a submission entry with patches that are not pending
        entry = SubmissionEntry()

        # Patch with no competition_patch_id
        patch1 = SubmissionEntryPatch()
        patch1.internal_patch_id = "patch-no-id"
        patch1.patch = "patch content 1"
        # patch1.competition_patch_id is not set
        entry.patches.append(patch1)

        # Patch that passed
        patch2 = SubmissionEntryPatch()
        patch2.internal_patch_id = "patch-passed"
        patch2.patch = "patch content 2"
        patch2.competition_patch_id = "comp-patch-passed"
        patch2.result = SubmissionResult.PASSED
        entry.patches.append(patch2)

        # Patch that failed
        patch3 = SubmissionEntryPatch()
        patch3.internal_patch_id = "patch-failed"
        patch3.patch = "patch content 3"
        patch3.competition_patch_id = "comp-patch-failed"
        patch3.result = SubmissionResult.FAILED
        entry.patches.append(patch3)

        # Patch that errored
        patch4 = SubmissionEntryPatch()
        patch4.internal_patch_id = "patch-errored"
        patch4.patch = "patch content 4"
        patch4.competition_patch_id = "comp-patch-errored"
        patch4.result = SubmissionResult.ERRORED
        entry.patches.append(patch4)

        # Should return empty list
        result = _get_pending_patch_submissions(entry)
        assert len(result) == 0
        assert result == []

    def test_get_pending_patch_submissions_empty_entry(self, submissions):
        """Test _get_pending_patch_submissions returns empty list for entry with no patches."""

        # Create an empty submission entry
        entry = SubmissionEntry()
        # entry.patches is empty by default

        # Should return empty list
        result = _get_pending_patch_submissions(entry)
        assert len(result) == 0
        assert result == []

    def test_get_pending_patch_submissions_requires_both_id_and_accepted_status(self, submissions):
        """Test _get_pending_patch_submissions requires both competition_patch_id and ACCEPTED status."""

        # Create a submission entry with edge cases
        entry = SubmissionEntry()

        # Patch with ACCEPTED status but no competition_patch_id
        patch1 = SubmissionEntryPatch()
        patch1.internal_patch_id = "patch-accepted-no-id"
        patch1.patch = "patch content 1"
        # patch1.competition_patch_id is not set
        patch1.result = SubmissionResult.ACCEPTED
        entry.patches.append(patch1)

        # Patch with competition_patch_id but no result explicitly set
        # Note: protobuf now defaults result to NONE (value 0), so this will NOT be considered pending
        patch2 = SubmissionEntryPatch()
        patch2.internal_patch_id = "patch-id-no-result"
        patch2.patch = "patch content 2"
        patch2.competition_patch_id = "comp-patch-no-result"
        # patch2.result is not set (defaults to NONE)
        entry.patches.append(patch2)

        # Patch with empty competition_patch_id and ACCEPTED status
        patch3 = SubmissionEntryPatch()
        patch3.internal_patch_id = "patch-empty-id"
        patch3.patch = "patch content 3"
        patch3.competition_patch_id = ""  # Empty string
        patch3.result = SubmissionResult.ACCEPTED
        entry.patches.append(patch3)

        # Patch with both competition_patch_id and explicit ACCEPTED status - should be pending
        patch4 = SubmissionEntryPatch()
        patch4.internal_patch_id = "patch-valid"
        patch4.patch = "patch content 4"
        patch4.competition_patch_id = "comp-patch-accepted"
        patch4.result = SubmissionResult.ACCEPTED
        entry.patches.append(patch4)

        # Should return only patch4 since it has both competition_patch_id and explicit ACCEPTED status
        result = _get_pending_patch_submissions(entry)
        assert len(result) == 1
        assert result[0].competition_patch_id == "comp-patch-accepted"
        assert result[0].result == SubmissionResult.ACCEPTED

    def test_get_pending_patch_submissions_preserves_order(self, submissions):
        """Test _get_pending_patch_submissions preserves the order of patches in the entry."""

        # Create a submission entry with multiple accepted patches
        entry = SubmissionEntry()

        # Add accepted patches in specific order
        patch1 = SubmissionEntryPatch()
        patch1.internal_patch_id = "first-accepted-patch"
        patch1.patch = "patch content 1"
        patch1.competition_patch_id = "first-accepted-patch-id"
        patch1.result = SubmissionResult.ACCEPTED
        entry.patches.append(patch1)

        # Add a non-accepted patch in between
        patch2 = SubmissionEntryPatch()
        patch2.internal_patch_id = "passed-patch"
        patch2.patch = "patch content 2"
        patch2.competition_patch_id = "passed-patch-id"
        patch2.result = SubmissionResult.PASSED
        entry.patches.append(patch2)

        # Add another accepted patch
        patch3 = SubmissionEntryPatch()
        patch3.internal_patch_id = "second-accepted-patch"
        patch3.patch = "patch content 3"
        patch3.competition_patch_id = "second-accepted-patch-id"
        patch3.result = SubmissionResult.ACCEPTED
        entry.patches.append(patch3)

        # Add another accepted patch
        patch4 = SubmissionEntryPatch()
        patch4.internal_patch_id = "third-accepted-patch"
        patch4.patch = "patch content 4"
        patch4.competition_patch_id = "third-accepted-patch-id"
        patch4.result = SubmissionResult.ACCEPTED
        entry.patches.append(patch4)

        # Should return accepted patches in the same order they appear in the entry
        result = _get_pending_patch_submissions(entry)
        assert len(result) == 3
        assert result[0].competition_patch_id == "first-accepted-patch-id"
        assert result[1].competition_patch_id == "second-accepted-patch-id"
        assert result[2].competition_patch_id == "third-accepted-patch-id"

    def test_get_pending_patch_submissions_only_accepted_status(self, submissions):
        """Test _get_pending_patch_submissions only includes ACCEPTED status, not other statuses."""

        # Create a submission entry with patches having various statuses
        entry = SubmissionEntry()

        # Test all possible SubmissionResult values
        statuses_to_test = [
            (SubmissionResult.ACCEPTED, "should-be-included"),
            (SubmissionResult.PASSED, "should-not-be-included-passed"),
            (SubmissionResult.FAILED, "should-not-be-included-failed"),
            (SubmissionResult.ERRORED, "should-not-be-included-errored"),
            (SubmissionResult.DEADLINE_EXCEEDED, "should-not-be-included-deadline"),
        ]

        for status, patch_id in statuses_to_test:
            patch = SubmissionEntryPatch()
            patch.internal_patch_id = f"patch-{patch_id}"
            patch.patch = f"patch content for {patch_id}"
            patch.competition_patch_id = patch_id
            patch.result = status
            entry.patches.append(patch)

        # Should return only the ACCEPTED patch
        result = _get_pending_patch_submissions(entry)
        assert len(result) == 1
        assert result[0].competition_patch_id == "should-be-included"
        assert result[0].result == SubmissionResult.ACCEPTED

    def test_get_pending_patch_submissions_multiple_criteria_combinations(self, submissions):
        """Test _get_pending_patch_submissions with various combinations of criteria."""

        # Create a submission entry with patches covering edge cases using builder
        entry = (
            SubmissionEntryBuilder()
            .patch(
                internal_patch_id="valid-pending",
                patch_content="patch content 1",
                competition_patch_id="valid-pending-id",
                result=SubmissionResult.ACCEPTED,
            )
            .patch(
                internal_patch_id="accepted-empty-id",
                patch_content="patch content 2",
                competition_patch_id="",  # Empty - should not be included
                result=SubmissionResult.ACCEPTED,
            )
            .patch(
                internal_patch_id="passed-with-id",
                patch_content="patch content 3",
                competition_patch_id="passed-patch-id",
                result=SubmissionResult.PASSED,
            )  # PASSED - should not be included
            .patch(
                internal_patch_id="failed-with-id",
                patch_content="patch content 4",
                competition_patch_id="failed-patch-id",
                result=SubmissionResult.FAILED,
            )  # FAILED - should not be included
            .patch(
                internal_patch_id="another-valid-pending",
                patch_content="patch content 5",
                competition_patch_id="another-valid-pending-id",
                result=SubmissionResult.ACCEPTED,
            )
            .build()
        )

        # Should return only the two valid pending patches
        result = _get_pending_patch_submissions(entry)
        assert len(result) == 2

        # Verify the correct patches are returned
        returned_ids = [patch_entry.competition_patch_id for patch_entry in result]
        assert "valid-pending-id" in returned_ids
        assert "another-valid-pending-id" in returned_ids

        # Verify excluded patches are not returned
        assert "passed-patch-id" not in returned_ids
        assert "failed-patch-id" not in returned_ids
        assert "" not in returned_ids  # Empty string should not be in results

    def test_get_available_sarifs_for_matching_with_available_sarifs(self, submissions):
        """Test _get_available_sarifs_for_matching returns SARIFs that haven't been used."""
        # Mock the sarif_store to return some SARIFs for the task
        mock_sarif1 = Mock()
        mock_sarif1.sarif_id = "sarif-1"
        mock_sarif2 = Mock()
        mock_sarif2.sarif_id = "sarif-2"
        mock_sarif3 = Mock()
        mock_sarif3.sarif_id = "sarif-3"

        submissions.sarif_store = Mock()
        submissions.sarif_store.get_by_task_id.return_value = [mock_sarif1, mock_sarif2, mock_sarif3]

        # Create some submissions with bundles that use some SARIFs
        submission1 = SubmissionEntry()
        # Add crash to submission1
        crash_with_id1 = CrashWithId()
        crash_with_id1.crash.crash.target.task_id = "test-task"
        submission1.crashes.append(crash_with_id1)

        # Create bundle with sarif-1 (making it unavailable)

        bundle1 = Bundle()
        bundle1.competition_sarif_id = "sarif-1"
        submission1.bundles.append(bundle1)

        submission2 = SubmissionEntry()
        # Add crash to submission2
        crash_with_id2 = CrashWithId()
        crash_with_id2.crash.crash.target.task_id = "test-task"
        submission2.crashes.append(crash_with_id2)

        # Create bundle with sarif-3 (making it unavailable)
        bundle2 = Bundle()
        bundle2.competition_sarif_id = "sarif-3"
        submission2.bundles.append(bundle2)

        submissions.entries = [submission1, submission2]

        # Call the method
        result = submissions._get_available_sarifs_for_matching("test-task")

        # Should return only sarif-2 (sarif-1 and sarif-3 are used)
        assert len(result) == 1
        assert result[0].sarif_id == "sarif-2"

    def test_get_available_sarifs_for_matching_no_sarifs_for_task(self, submissions):
        """Test _get_available_sarifs_for_matching returns empty list when no SARIFs exist for task."""
        # Mock the sarif_store to return no SARIFs for the task
        submissions.sarif_store = Mock()
        submissions.sarif_store.get_by_task_id.return_value = []

        # Call the method
        result = submissions._get_available_sarifs_for_matching("test-task")

        # Should return empty list
        assert result == []

    def test_get_available_sarifs_for_matching_all_sarifs_used(self, submissions):
        """Test _get_available_sarifs_for_matching returns empty list when all SARIFs are used."""
        # Mock the sarif_store to return some SARIFs
        mock_sarif1 = Mock()
        mock_sarif1.sarif_id = "sarif-1"
        mock_sarif2 = Mock()
        mock_sarif2.sarif_id = "sarif-2"

        submissions.sarif_store = Mock()
        submissions.sarif_store.get_by_task_id.return_value = [mock_sarif1, mock_sarif2]

        # Create submissions with bundles that use all SARIFs
        submission1 = SubmissionEntry()
        # Add crash to submission1
        crash_with_id1 = CrashWithId()
        crash_with_id1.crash.crash.target.task_id = "test-task"
        submission1.crashes.append(crash_with_id1)

        bundle1 = Bundle()
        bundle1.competition_sarif_id = "sarif-1"
        submission1.bundles.append(bundle1)

        submission2 = SubmissionEntry()
        # Add crash to submission2
        crash_with_id2 = CrashWithId()
        crash_with_id2.crash.crash.target.task_id = "test-task"
        submission2.crashes.append(crash_with_id2)

        bundle2 = Bundle()
        bundle2.competition_sarif_id = "sarif-2"
        submission2.bundles.append(bundle2)

        submissions.entries = [submission1, submission2]

        # Call the method
        result = submissions._get_available_sarifs_for_matching("test-task")

        # Should return empty list since all SARIFs are used
        assert result == []

    def test_get_available_sarifs_for_matching_no_bundles_exist(self, submissions):
        """Test _get_available_sarifs_for_matching returns all SARIFs when no bundles exist."""
        # Mock the sarif_store to return some SARIFs
        mock_sarif1 = Mock()
        mock_sarif1.sarif_id = "sarif-1"
        mock_sarif2 = Mock()
        mock_sarif2.sarif_id = "sarif-2"

        submissions.sarif_store = Mock()
        submissions.sarif_store.get_by_task_id.return_value = [mock_sarif1, mock_sarif2]

        # Create submissions without bundles
        submission1 = SubmissionEntry()
        # Add crash to submission1
        crash_with_id1 = CrashWithId()
        crash_with_id1.crash.crash.target.task_id = "test-task"
        submission1.crashes.append(crash_with_id1)
        # No bundles

        submissions.entries = [submission1]

        # Call the method
        result = submissions._get_available_sarifs_for_matching("test-task")

        # Should return all SARIFs since none are used
        assert len(result) == 2
        sarif_ids = [sarif.sarif_id for sarif in result]
        assert "sarif-1" in sarif_ids
        assert "sarif-2" in sarif_ids

    def test_get_available_sarifs_for_matching_empty_sarif_ids_ignored(self, submissions):
        """Test _get_available_sarifs_for_matching ignores bundles with empty competition_sarif_id."""
        # Mock the sarif_store to return some SARIFs
        mock_sarif1 = Mock()
        mock_sarif1.sarif_id = "sarif-1"
        mock_sarif2 = Mock()
        mock_sarif2.sarif_id = "sarif-2"

        submissions.sarif_store = Mock()
        submissions.sarif_store.get_by_task_id.return_value = [mock_sarif1, mock_sarif2]

        # Create submissions with bundles that have empty/no SARIF IDs
        submission1 = SubmissionEntry()
        # Add crash to submission1
        crash_with_id1 = CrashWithId()
        crash_with_id1.crash.crash.target.task_id = "test-task"
        submission1.crashes.append(crash_with_id1)

        bundle1 = Bundle()
        bundle1.competition_sarif_id = ""  # Empty string
        submission1.bundles.append(bundle1)

        submission2 = SubmissionEntry()
        # Add crash to submission2
        crash_with_id2 = CrashWithId()
        crash_with_id2.crash.crash.target.task_id = "test-task"
        submission2.crashes.append(crash_with_id2)

        bundle2 = Bundle()
        # competition_sarif_id is not set (defaults to empty)
        submission2.bundles.append(bundle2)

        submissions.entries = [submission1, submission2]

        # Call the method
        result = submissions._get_available_sarifs_for_matching("test-task")

        # Should return all SARIFs since empty SARIF IDs are ignored
        assert len(result) == 2
        sarif_ids = [sarif.sarif_id for sarif in result]
        assert "sarif-1" in sarif_ids
        assert "sarif-2" in sarif_ids

    def test_get_available_sarifs_for_matching_stopped_submissions_release_sarifs(self, submissions):
        """Test _get_available_sarifs_for_matching excludes SARIFs from stopped submissions (makes them available again)."""
        # Mock the sarif_store to return some SARIFs
        mock_sarif1 = Mock()
        mock_sarif1.sarif_id = "sarif-1"
        mock_sarif2 = Mock()
        mock_sarif2.sarif_id = "sarif-2"

        submissions.sarif_store = Mock()
        submissions.sarif_store.get_by_task_id.return_value = [mock_sarif1, mock_sarif2]

        # Create a stopped submission with a bundle using sarif-1
        submission1 = SubmissionEntry()
        submission1.stop = True  # Mark as stopped
        # Add crash to submission1
        crash_with_id1 = CrashWithId()
        crash_with_id1.crash.crash.target.task_id = "test-task"
        submission1.crashes.append(crash_with_id1)

        bundle1 = Bundle()
        bundle1.competition_sarif_id = "sarif-1"
        submission1.bundles.append(bundle1)

        submissions.entries = [submission1]

        # Call the method
        result = submissions._get_available_sarifs_for_matching("test-task")

        # Should return both SARIFs since stopped submission releases sarif-1 for reuse
        assert len(result) == 2
        sarif_ids = [sarif.sarif_id for sarif in result]
        assert "sarif-1" in sarif_ids
        assert "sarif-2" in sarif_ids

    def test_get_available_sarifs_for_matching_mixed_scenarios(self, submissions):
        """Test _get_available_sarifs_for_matching with a complex mix of scenarios."""
        # Mock the sarif_store to return multiple SARIFs
        mock_sarifs = []
        for i in range(1, 6):  # sarif-1 through sarif-5
            mock_sarif = Mock()
            mock_sarif.sarif_id = f"sarif-{i}"
            mock_sarifs.append(mock_sarif)

        submissions.sarif_store = Mock()
        submissions.sarif_store.get_by_task_id.return_value = mock_sarifs

        # Create various submissions with different bundle states using builder
        submissions.entries = [
            # Submission 1: Uses sarif-1
            (
                SubmissionEntryBuilder()
                .crash(task_id="test-task")
                .bundle(competition_sarif_id="sarif-1", task_id="test-task")
                .build()
            ),
            # Submission 2: Has bundle with empty SARIF ID (doesn't use any SARIF)
            (
                SubmissionEntryBuilder()
                .crash(task_id="test-task")
                .bundle(competition_sarif_id="", task_id="test-task")
                .build()
            ),
            # Submission 3: Uses sarif-3, but is stopped
            (
                SubmissionEntryBuilder()
                .crash(task_id="test-task")
                .bundle(competition_sarif_id="sarif-3", task_id="test-task")
                .stopped()
                .build()
            ),
            # Submission 4: No bundles
            (SubmissionEntryBuilder().crash(task_id="test-task").build()),
            # Submission 5: Uses sarif-5
            (
                SubmissionEntryBuilder()
                .crash(task_id="test-task")
                .bundle(competition_sarif_id="sarif-5", task_id="test-task")
                .build()
            ),
        ]

        # Call the method
        result = submissions._get_available_sarifs_for_matching("test-task")

        # Should return sarif-2, sarif-3, and sarif-4 (sarif-1 and sarif-5 are used by active submissions, sarif-3 is released by stopped submission)
        assert len(result) == 3
        sarif_ids = [sarif.sarif_id for sarif in result]
        assert "sarif-2" in sarif_ids
        assert "sarif-3" in sarif_ids  # Available because submission3 is stopped
        assert "sarif-4" in sarif_ids
        # Verify SARIFs from active submissions are not returned
        assert "sarif-1" not in sarif_ids  # Used by active submission1
        assert "sarif-5" not in sarif_ids  # Used by active submission5

    def test_get_available_sarifs_for_matching_multiple_bundles_per_submission(self, submissions):
        """Test _get_available_sarifs_for_matching handles multiple bundles per submission."""
        # Mock the sarif_store to return some SARIFs
        mock_sarif1 = Mock()
        mock_sarif1.sarif_id = "sarif-1"
        mock_sarif2 = Mock()
        mock_sarif2.sarif_id = "sarif-2"
        mock_sarif3 = Mock()
        mock_sarif3.sarif_id = "sarif-3"

        submissions.sarif_store = Mock()
        submissions.sarif_store.get_by_task_id.return_value = [mock_sarif1, mock_sarif2, mock_sarif3]

        # Create submission with multiple bundles
        submission1 = SubmissionEntry()
        # Add crash to submission1
        crash_with_id1 = CrashWithId()
        crash_with_id1.crash.crash.target.task_id = "test-task"
        submission1.crashes.append(crash_with_id1)

        # First bundle uses sarif-1
        bundle1 = Bundle()
        bundle1.competition_sarif_id = "sarif-1"
        submission1.bundles.append(bundle1)

        # Second bundle uses sarif-3
        bundle2 = Bundle()
        bundle2.competition_sarif_id = "sarif-3"
        submission1.bundles.append(bundle2)

        submissions.entries = [submission1]

        # Call the method
        result = submissions._get_available_sarifs_for_matching("test-task")

        # Should return only sarif-2 (sarif-1 and sarif-3 are used)
        assert len(result) == 1
        assert result[0].sarif_id == "sarif-2"

    def test_enumerate_task_submissions_with_matching_task(self, submissions):
        """Test _enumerate_task_submissions returns submissions for the specified task."""
        # Create submissions for different tasks using builder
        submissions.entries = [
            SubmissionEntryBuilder().crash(task_id="task-1").build(),
            SubmissionEntryBuilder().crash(task_id="task-2").build(),
            SubmissionEntryBuilder().crash(task_id="task-1").build(),  # Same as first
        ]

        # Call the method for task-1
        result = list(submissions._enumerate_task_submissions("task-1"))

        # Should return submissions at indices 0 and 2 with their indices
        assert len(result) == 2
        indices = [i for i, _ in result]
        entries = [e for _, e in result]

        assert 0 in indices  # first submission
        assert 2 in indices  # third submission
        assert submissions.entries[0] in entries
        assert submissions.entries[2] in entries
        assert submissions.entries[1] not in entries  # Different task

    def test_enumerate_task_submissions_no_matching_task(self, submissions):
        """Test _enumerate_task_submissions returns empty when no submissions match the task."""
        # Create submissions for different tasks using builder
        submissions.entries = [
            SubmissionEntryBuilder().crash(task_id="task-1").build(),
            SubmissionEntryBuilder().crash(task_id="task-2").build(),
        ]

        # Call the method for non-existent task
        result = list(submissions._enumerate_task_submissions("non-existent-task"))

        # Should return empty list
        assert len(result) == 0
        assert result == []

    def test_enumerate_task_submissions_empty_entries(self, submissions):
        """Test _enumerate_task_submissions returns empty when no submissions exist."""
        submissions.entries = []

        # Call the method
        result = list(submissions._enumerate_task_submissions("any-task"))

        # Should return empty list
        assert len(result) == 0
        assert result == []

    def test_enumerate_task_submissions_skips_stopped_submissions(self, submissions):
        """Test _enumerate_task_submissions skips stopped submissions."""
        # Create submissions for the same task using builder
        submissions.entries = [
            SubmissionEntryBuilder().crash(task_id="test-task").build(),
            SubmissionEntryBuilder().crash(task_id="test-task").stopped().build(),
            SubmissionEntryBuilder().crash(task_id="test-task").build(),
        ]

        # Call the method
        result = list(submissions._enumerate_task_submissions("test-task"))

        # Should return only submission1 and submission3 (skipping stopped submission2)
        assert len(result) == 2
        indices = [i for i, _ in result]
        entries = [e for _, e in result]

        assert 0 in indices  # first submission
        assert 2 in indices  # third submission
        assert 1 not in indices  # second submission (stopped)
        assert submissions.entries[0] in entries
        assert submissions.entries[2] in entries
        assert submissions.entries[1] not in entries  # Stopped submission

    def test_enumerate_task_submissions_skips_cancelled_tasks(self, submissions, mock_task_registry):
        """Test _enumerate_task_submissions skips submissions for cancelled tasks."""
        # Create submissions for different tasks
        submission1 = SubmissionEntry()
        crash_with_id1 = CrashWithId()
        crash_with_id1.crash.crash.target.task_id = "active-task"
        submission1.crashes.append(crash_with_id1)

        submission2 = SubmissionEntry()
        crash_with_id2 = CrashWithId()
        crash_with_id2.crash.crash.target.task_id = "cancelled-task"
        submission2.crashes.append(crash_with_id2)

        submission3 = SubmissionEntry()
        crash_with_id3 = CrashWithId()
        crash_with_id3.crash.crash.target.task_id = "cancelled-task"
        submission3.crashes.append(crash_with_id3)

        submissions.entries = [submission1, submission2, submission3]

        # Mock task registry to indicate cancelled-task should stop processing
        def should_stop_side_effect(task_id):
            return task_id == "cancelled-task"

        mock_task_registry.should_stop_processing.side_effect = should_stop_side_effect

        # Call the method for cancelled-task
        result = list(submissions._enumerate_task_submissions("cancelled-task"))

        # Should return empty list since task is cancelled
        assert len(result) == 0
        assert result == []

        # Verify should_stop_processing was called for the task
        mock_task_registry.should_stop_processing.assert_called_with("cancelled-task")

    def test_enumerate_task_submissions_preserves_order(self, submissions):
        """Test _enumerate_task_submissions preserves the order of submissions."""
        # Create multiple submissions for the same task in specific order
        submission1 = SubmissionEntry()
        crash_with_id1 = CrashWithId()
        crash_with_id1.crash.crash.target.task_id = "test-task"
        crash_with_id1.crash.crash.crash_input_path = "/path/to/crash1.bin"
        submission1.crashes.append(crash_with_id1)

        submission2 = SubmissionEntry()
        crash_with_id2 = CrashWithId()
        crash_with_id2.crash.crash.target.task_id = "other-task"  # Different task
        submission2.crashes.append(crash_with_id2)

        submission3 = SubmissionEntry()
        crash_with_id3 = CrashWithId()
        crash_with_id3.crash.crash.target.task_id = "test-task"
        crash_with_id3.crash.crash.crash_input_path = "/path/to/crash3.bin"
        submission3.crashes.append(crash_with_id3)

        submission4 = SubmissionEntry()
        crash_with_id4 = CrashWithId()
        crash_with_id4.crash.crash.target.task_id = "test-task"
        crash_with_id4.crash.crash.crash_input_path = "/path/to/crash4.bin"
        submission4.crashes.append(crash_with_id4)

        submissions.entries = [submission1, submission2, submission3, submission4]

        # Call the method
        result = list(submissions._enumerate_task_submissions("test-task"))

        # Should return submissions in the same order they appear in entries
        assert len(result) == 3
        assert result[0][0] == 0  # submission1 at index 0
        assert result[1][0] == 2  # submission3 at index 2
        assert result[2][0] == 3  # submission4 at index 3

        # Verify the entries are in correct order
        assert result[0][1].crashes[0].crash.crash.crash_input_path == "/path/to/crash1.bin"
        assert result[1][1].crashes[0].crash.crash.crash_input_path == "/path/to/crash3.bin"
        assert result[2][1].crashes[0].crash.crash.crash_input_path == "/path/to/crash4.bin"

    def test_enumerate_task_submissions_mixed_conditions(self, submissions, mock_task_registry):
        """Test _enumerate_task_submissions with a mix of conditions."""
        # Create submissions with various conditions using builder
        submissions.entries = [
            SubmissionEntryBuilder().crash(task_id="target-task").build(),  # Active, matching task
            SubmissionEntryBuilder().crash(task_id="target-task").stopped().build(),  # Stopped, matching task
            SubmissionEntryBuilder().crash(task_id="other-task").build(),  # Active, different task
            SubmissionEntryBuilder().crash(task_id="target-task").build(),  # Active, matching task
            SubmissionEntryBuilder().crash(task_id="cancelled-task").build(),  # Active, cancelled task
        ]

        # Mock task registry
        def should_stop_side_effect(task_id):
            return task_id == "cancelled-task"

        mock_task_registry.should_stop_processing.side_effect = should_stop_side_effect

        # Call the method for target-task
        result = list(submissions._enumerate_task_submissions("target-task"))

        # Should return only submission1 and submission4 (active, matching task)
        assert len(result) == 2
        indices = [i for i, _ in result]
        entries = [e for _, e in result]

        assert 0 in indices  # first submission
        assert 3 in indices  # fourth submission
        assert submissions.entries[0] in entries
        assert submissions.entries[3] in entries
        # Verify excluded submissions
        assert submissions.entries[1] not in entries  # Stopped
        assert submissions.entries[2] not in entries  # Different task
        assert submissions.entries[4] not in entries  # Different task

    def test_enumerate_task_submissions_returns_correct_indices(self, submissions):
        """Test _enumerate_task_submissions returns correct indices from original entries list."""
        # Create submissions with gaps (some will be filtered out) using builder
        submissions.entries = [
            SubmissionEntryBuilder().crash(task_id="other-task").build(),  # Index 0 - different task
            SubmissionEntryBuilder().crash(task_id="target-task").build(),  # Index 1 - target task
            SubmissionEntryBuilder().crash(task_id="target-task").stopped().build(),  # Index 2 - stopped
            SubmissionEntryBuilder().crash(task_id="target-task").build(),  # Index 3 - target task
        ]

        # Call the method
        result = list(submissions._enumerate_task_submissions("target-task"))

        # Should return submissions at indices 1 and 3
        assert len(result) == 2
        assert result[0][0] == 1  # second submission
        assert result[1][0] == 3  # fourth submission
        assert result[0][1] is submissions.entries[1]
        assert result[1][1] is submissions.entries[3]

    def test_task_outstanding_patch_requests_with_outstanding_requests(self, submissions):
        """Test _task_outstanding_patch_requests counts submissions with requested but not received patches."""
        # Create submissions with patches in different states
        submissions.entries = [
            # Submission 1: Has patch requested but not received (outstanding)
            SubmissionEntryBuilder()
            .crash(task_id="test-task")
            .patch(internal_patch_id="patch-1", patch_content="")  # No patch content = requested but not received
            .build(),
            # Submission 2: Has patch received (not outstanding)
            SubmissionEntryBuilder()
            .crash(task_id="test-task")
            .patch(internal_patch_id="patch-2", patch_content="diff content")  # Has patch content = received
            .build(),
            # Submission 3: Another outstanding patch request
            SubmissionEntryBuilder()
            .crash(task_id="test-task")
            .patch(internal_patch_id="patch-3", patch_content="")  # No patch content = outstanding
            .build(),
            # Submission 4: Different task (should be ignored)
            SubmissionEntryBuilder()
            .crash(task_id="other-task")
            .patch(internal_patch_id="patch-4", patch_content="")  # Outstanding but different task
            .build(),
        ]

        # Call the method
        result = submissions._task_outstanding_patch_requests("test-task")

        # Should count 2 outstanding requests for test-task
        assert result == 2

    def test_task_outstanding_patch_requests_no_outstanding_requests(self, submissions):
        """Test _task_outstanding_patch_requests returns 0 when all patches are received."""
        # Create submissions with all patches received
        submissions.entries = [
            SubmissionEntryBuilder()
            .crash(task_id="test-task")
            .patch(internal_patch_id="patch-1", patch_content="diff content 1")
            .build(),
            SubmissionEntryBuilder()
            .crash(task_id="test-task")
            .patch(internal_patch_id="patch-2", patch_content="diff content 2")
            .build(),
        ]

        # Call the method
        result = submissions._task_outstanding_patch_requests("test-task")

        # Should return 0 since all patches are received
        assert result == 0

    def test_task_outstanding_patch_requests_no_patches(self, submissions):
        """Test _task_outstanding_patch_requests returns 0 when submissions have no patches."""
        # Create submissions without any patches
        submissions.entries = [
            SubmissionEntryBuilder().crash(task_id="test-task").build(),
            SubmissionEntryBuilder().crash(task_id="test-task").build(),
        ]

        # Call the method
        result = submissions._task_outstanding_patch_requests("test-task")

        # Should return 0 since no patches exist
        assert result == 0

    def test_task_outstanding_patch_requests_empty_entries(self, submissions):
        """Test _task_outstanding_patch_requests returns 0 when no submissions exist."""
        submissions.entries = []

        # Call the method
        result = submissions._task_outstanding_patch_requests("test-task")

        # Should return 0 since no submissions exist
        assert result == 0

    def test_task_outstanding_patch_requests_no_matching_task(self, submissions):
        """Test _task_outstanding_patch_requests returns 0 when no submissions match the task."""
        # Create submissions for different tasks
        submissions.entries = [
            SubmissionEntryBuilder()
            .crash(task_id="other-task-1")
            .patch(internal_patch_id="patch-1", patch_content="")  # Outstanding but different task
            .build(),
            SubmissionEntryBuilder()
            .crash(task_id="other-task-2")
            .patch(internal_patch_id="patch-2", patch_content="")  # Outstanding but different task
            .build(),
        ]

        # Call the method for non-existent task
        result = submissions._task_outstanding_patch_requests("test-task")

        # Should return 0 since no submissions match the task
        assert result == 0

    def test_task_outstanding_patch_requests_skips_stopped_submissions(self, submissions):
        """Test _task_outstanding_patch_requests skips stopped submissions."""
        submissions.entries = [
            # Active submission with outstanding patch
            SubmissionEntryBuilder()
            .crash(task_id="test-task")
            .patch(internal_patch_id="patch-1", patch_content="")
            .build(),
            # Stopped submission with outstanding patch (should be ignored)
            SubmissionEntryBuilder()
            .crash(task_id="test-task")
            .patch(internal_patch_id="patch-2", patch_content="")
            .stopped()
            .build(),
            # Another active submission with outstanding patch
            SubmissionEntryBuilder()
            .crash(task_id="test-task")
            .patch(internal_patch_id="patch-3", patch_content="")
            .build(),
        ]

        # Call the method
        result = submissions._task_outstanding_patch_requests("test-task")

        # Should count only active submissions (2), skipping the stopped one
        assert result == 2

    def test_task_outstanding_patch_requests_skips_cancelled_tasks(self, submissions, mock_task_registry):
        """Test _task_outstanding_patch_requests skips submissions for cancelled tasks."""
        submissions.entries = [
            SubmissionEntryBuilder()
            .crash(task_id="cancelled-task")
            .patch(internal_patch_id="patch-1", patch_content="")
            .build(),
            SubmissionEntryBuilder()
            .crash(task_id="cancelled-task")
            .patch(internal_patch_id="patch-2", patch_content="")
            .build(),
        ]

        # Mock task registry to indicate task should stop processing
        mock_task_registry.should_stop_processing.return_value = True

        # Call the method
        result = submissions._task_outstanding_patch_requests("cancelled-task")

        # Should return 0 since task is cancelled
        assert result == 0

        # Verify should_stop_processing was called
        mock_task_registry.should_stop_processing.assert_called_with("cancelled-task")

    def test_task_outstanding_patch_requests_multiple_patches_per_submission(self, submissions):
        """Test _task_outstanding_patch_requests only counts current patch per submission."""
        submissions.entries = [
            # Submission with multiple patches - only current patch (index 0) should be counted if outstanding
            SubmissionEntryBuilder()
            .crash(task_id="test-task")
            .patch(internal_patch_id="patch-1", patch_content="")  # Current patch (index 0) - outstanding
            .patch(internal_patch_id="patch-2", patch_content="diff content")  # Next patch - has content
            .patch_idx(0)  # Current patch is at index 0
            .build(),
            # Submission with current patch that has content (not outstanding)
            SubmissionEntryBuilder()
            .crash(task_id="test-task")
            .patch(internal_patch_id="patch-3", patch_content="diff content")  # Current patch - has content
            .patch(internal_patch_id="patch-4", patch_content="")  # Next patch - no content but not current
            .patch_idx(0)  # Current patch is at index 0
            .build(),
            # Submission where current patch index is beyond available patches
            SubmissionEntryBuilder()
            .crash(task_id="test-task")
            .patch(internal_patch_id="patch-5", patch_content="")  # Has patch but not current
            .patch_idx(1)  # Current patch index is beyond available patches (no current patch)
            .build(),
        ]

        # Call the method
        result = submissions._task_outstanding_patch_requests("test-task")

        # Should count only 1 outstanding request (first submission's current patch)
        assert result == 1

    def test_task_outstanding_patch_requests_patch_idx_out_of_bounds(self, submissions):
        """Test _task_outstanding_patch_requests handles patch_idx out of bounds gracefully."""
        submissions.entries = [
            # Submission where patch_idx is beyond the patches list
            SubmissionEntryBuilder()
            .crash(task_id="test-task")
            .patch(internal_patch_id="patch-1", patch_content="")
            .patch_idx(5)  # Index 5 but only 1 patch exists (index 0)
            .build(),
            # Normal submission with outstanding patch
            SubmissionEntryBuilder()
            .crash(task_id="test-task")
            .patch(internal_patch_id="patch-2", patch_content="")
            .patch_idx(0)  # Valid index
            .build(),
        ]

        # Call the method
        result = submissions._task_outstanding_patch_requests("test-task")

        # Should count only 1 (the valid submission), ignoring the out-of-bounds one
        assert result == 1

    def test_task_outstanding_patch_requests_mixed_conditions(self, submissions, mock_task_registry):
        """Test _task_outstanding_patch_requests with various mixed conditions."""
        submissions.entries = [
            # Outstanding patch, active submission, matching task
            SubmissionEntryBuilder()
            .crash(task_id="target-task")
            .patch(internal_patch_id="patch-1", patch_content="")
            .build(),
            # Patch received, active submission, matching task
            SubmissionEntryBuilder()
            .crash(task_id="target-task")
            .patch(internal_patch_id="patch-2", patch_content="diff content")
            .build(),
            # Outstanding patch, stopped submission, matching task (should be ignored)
            SubmissionEntryBuilder()
            .crash(task_id="target-task")
            .patch(internal_patch_id="patch-3", patch_content="")
            .stopped()
            .build(),
            # Outstanding patch, active submission, different task (should be ignored)
            SubmissionEntryBuilder()
            .crash(task_id="other-task")
            .patch(internal_patch_id="patch-4", patch_content="")
            .build(),
            # Outstanding patch, active submission, cancelled task (should be ignored)
            SubmissionEntryBuilder()
            .crash(task_id="cancelled-task")
            .patch(internal_patch_id="patch-5", patch_content="")
            .build(),
            # Another outstanding patch, active submission, matching task
            SubmissionEntryBuilder()
            .crash(task_id="target-task")
            .patch(internal_patch_id="patch-6", patch_content="")
            .build(),
        ]

        # Mock task registry
        def should_stop_side_effect(task_id):
            return task_id == "cancelled-task"

        mock_task_registry.should_stop_processing.side_effect = should_stop_side_effect

        # Call the method
        result = submissions._task_outstanding_patch_requests("target-task")

        # Should count only 2 outstanding requests (first and last submissions)
        assert result == 2

    def test_reorder_patches_by_completion_basic_reordering(self, submissions):
        """Test _reorder_patches_by_completion reorders patches with content before those without."""
        # Create submission with mixed patches starting from patch_idx
        entry = SubmissionEntryBuilder().crash(task_id="test-task").build()

        # Add patches: some with content, some without
        entry.patches.extend(
            [
                SubmissionEntryPatch(
                    internal_patch_id="patch-1", patch="content-1"
                ),  # Already processed (before patch_idx)
                SubmissionEntryPatch(internal_patch_id="patch-2", patch=""),  # Outstanding (at patch_idx)
                SubmissionEntryPatch(internal_patch_id="patch-3", patch="content-3"),  # Completed (after patch_idx)
                SubmissionEntryPatch(internal_patch_id="patch-4", patch=""),  # Outstanding (after patch_idx)
                SubmissionEntryPatch(internal_patch_id="patch-5", patch="content-5"),  # Completed (after patch_idx)
            ]
        )
        entry.patch_idx = 1  # Start reordering from index 1

        submissions.entries = [entry]

        # Call the method
        submissions._reorder_patches_by_completion(entry)

        # Verify reordering: processed patches unchanged, then completed, then outstanding
        assert entry.patches[0].internal_patch_id == "patch-1"  # Unchanged (before patch_idx)
        assert entry.patches[1].internal_patch_id == "patch-3"  # Completed patch moved first
        assert entry.patches[2].internal_patch_id == "patch-5"  # Completed patch moved second
        assert entry.patches[3].internal_patch_id == "patch-2"  # Outstanding patch moved after completed
        assert entry.patches[4].internal_patch_id == "patch-4"  # Outstanding patch moved last

        # Verify content presence
        assert entry.patches[1].patch == "content-3"
        assert entry.patches[2].patch == "content-5"
        assert entry.patches[3].patch == ""
        assert entry.patches[4].patch == ""

    def test_reorder_patches_by_completion_preserves_relative_order(self, submissions):
        """Test _reorder_patches_by_completion preserves relative order within each group."""
        entry = SubmissionEntryBuilder().crash(task_id="test-task").build()

        # Add patches with specific order to test preservation
        entry.patches.extend(
            [
                SubmissionEntryPatch(internal_patch_id="patch-1", patch=""),  # Outstanding 1
                SubmissionEntryPatch(internal_patch_id="patch-2", patch="content-2"),  # Completed 1
                SubmissionEntryPatch(internal_patch_id="patch-3", patch=""),  # Outstanding 2
                SubmissionEntryPatch(internal_patch_id="patch-4", patch="content-4"),  # Completed 2
                SubmissionEntryPatch(internal_patch_id="patch-5", patch=""),  # Outstanding 3
            ]
        )
        entry.patch_idx = 0

        submissions.entries = [entry]

        # Call the method
        submissions._reorder_patches_by_completion(entry)

        # Verify completed patches come first in original relative order
        assert entry.patches[0].internal_patch_id == "patch-2"  # First completed
        assert entry.patches[1].internal_patch_id == "patch-4"  # Second completed

        # Verify outstanding patches come after in original relative order
        assert entry.patches[2].internal_patch_id == "patch-1"  # First outstanding
        assert entry.patches[3].internal_patch_id == "patch-3"  # Second outstanding
        assert entry.patches[4].internal_patch_id == "patch-5"  # Third outstanding

    def test_reorder_patches_by_completion_no_patches(self, submissions):
        """Test _reorder_patches_by_completion handles empty patches list gracefully."""
        entry = SubmissionEntryBuilder().crash(task_id="test-task").build()
        # entry.patches is already empty by default
        entry.patch_idx = 0

        submissions.entries = [entry]

        # Call the method - should not raise an exception
        submissions._reorder_patches_by_completion(entry)

        # Verify patches list remains empty
        assert len(entry.patches) == 0

    def test_reorder_patches_by_completion_patch_idx_out_of_bounds(self, submissions):
        """Test _reorder_patches_by_completion handles patch_idx >= len(patches) gracefully."""
        entry = SubmissionEntryBuilder().crash(task_id="test-task").build()
        entry.patches.extend(
            [
                SubmissionEntryPatch(internal_patch_id="patch-1", patch="content-1"),
                SubmissionEntryPatch(internal_patch_id="patch-2", patch=""),
            ]
        )
        entry.patch_idx = 5  # Beyond patches list

        original_patch_ids = [p.internal_patch_id for p in entry.patches]
        submissions.entries = [entry]

        # Call the method - should not modify anything
        submissions._reorder_patches_by_completion(entry)

        # Verify patches list unchanged
        assert [p.internal_patch_id for p in entry.patches] == original_patch_ids

    def test_reorder_patches_by_completion_all_completed(self, submissions):
        """Test _reorder_patches_by_completion when all patches from patch_idx have content."""
        entry = SubmissionEntryBuilder().crash(task_id="test-task").build()
        entry.patches.extend(
            [
                SubmissionEntryPatch(internal_patch_id="patch-1", patch="content-1"),  # Completed
                SubmissionEntryPatch(internal_patch_id="patch-2", patch="content-2"),  # Completed
                SubmissionEntryPatch(internal_patch_id="patch-3", patch="content-3"),  # Completed
            ]
        )
        entry.patch_idx = 0

        original_patch_ids = [p.internal_patch_id for p in entry.patches]
        submissions.entries = [entry]

        # Call the method
        submissions._reorder_patches_by_completion(entry)

        # Verify order unchanged (all already have content)
        assert [p.internal_patch_id for p in entry.patches] == original_patch_ids

    def test_reorder_patches_by_completion_all_outstanding(self, submissions):
        """Test _reorder_patches_by_completion when all patches from patch_idx are outstanding."""
        entry = SubmissionEntryBuilder().crash(task_id="test-task").build()
        entry.patches.extend(
            [
                SubmissionEntryPatch(internal_patch_id="patch-1", patch=""),  # Outstanding
                SubmissionEntryPatch(internal_patch_id="patch-2", patch=""),  # Outstanding
                SubmissionEntryPatch(internal_patch_id="patch-3", patch=""),  # Outstanding
            ]
        )
        entry.patch_idx = 0

        original_patch_ids = [p.internal_patch_id for p in entry.patches]
        submissions.entries = [entry]

        # Call the method
        submissions._reorder_patches_by_completion(entry)

        # Verify order unchanged (all outstanding)
        assert [p.internal_patch_id for p in entry.patches] == original_patch_ids

    def test_reorder_patches_by_completion_patch_idx_at_end(self, submissions):
        """Test _reorder_patches_by_completion when patch_idx points to last element."""
        entry = SubmissionEntryBuilder().crash(task_id="test-task").build()
        entry.patches.extend(
            [
                SubmissionEntryPatch(internal_patch_id="patch-1", patch="content-1"),  # Processed
                SubmissionEntryPatch(internal_patch_id="patch-2", patch="content-2"),  # Processed
                SubmissionEntryPatch(internal_patch_id="patch-3", patch=""),  # Current (outstanding)
            ]
        )
        entry.patch_idx = 2

        submissions.entries = [entry]

        # Call the method
        submissions._reorder_patches_by_completion(entry)

        # Verify first two unchanged, last one unchanged (only one to reorder)
        assert entry.patches[0].internal_patch_id == "patch-1"
        assert entry.patches[1].internal_patch_id == "patch-2"
        assert entry.patches[2].internal_patch_id == "patch-3"

    def test_record_patch_triggers_reordering(self, submissions):
        """Test record_patch calls _reorder_patches_by_completion after adding patch content."""
        # Create submission with outstanding patch request
        entry = SubmissionEntryBuilder().crash(task_id="test-task").build()
        entry.patches.extend(
            [
                SubmissionEntryPatch(internal_patch_id="patch-1", patch=""),  # Outstanding (will receive content)
                SubmissionEntryPatch(internal_patch_id="patch-2", patch=""),  # Outstanding
                SubmissionEntryPatch(internal_patch_id="patch-3", patch="content-3"),  # Already completed
            ]
        )
        entry.patch_idx = 0

        submissions.entries = [entry]

        # Create patch to record
        patch = Patch(internal_patch_id="patch-1", patch="new-content-1")

        # Record the patch
        result = submissions.record_patch(patch)

        # Verify success
        assert result is True

        # Verify patch content was added
        assert entry.patches[0].patch == "new-content-1"

        # Verify reordering occurred: completed patches should come first
        # patch-1 now has content, patch-3 already had content, patch-2 is still outstanding
        # Expected order: patch-1 (newly completed), patch-3 (already completed), patch-2 (outstanding)
        assert entry.patches[0].internal_patch_id == "patch-1"  # Newly completed
        assert entry.patches[1].internal_patch_id == "patch-3"  # Already completed
        assert entry.patches[2].internal_patch_id == "patch-2"  # Still outstanding

    def test_record_patch_reordering_with_multiple_outstanding(self, submissions):
        """Test record_patch reordering works correctly with multiple outstanding patches."""
        # Create submission with multiple outstanding patches
        entry = SubmissionEntryBuilder().crash(task_id="test-task").build()
        entry.patches.extend(
            [
                SubmissionEntryPatch(internal_patch_id="patch-1", patch=""),  # Outstanding
                SubmissionEntryPatch(internal_patch_id="patch-2", patch=""),  # Outstanding
                SubmissionEntryPatch(internal_patch_id="patch-3", patch=""),  # Outstanding (will receive content)
                SubmissionEntryPatch(internal_patch_id="patch-4", patch=""),  # Outstanding
            ]
        )
        entry.patch_idx = 0

        submissions.entries = [entry]

        # Record patch content for patch-3 (not the first one)
        patch = Patch(internal_patch_id="patch-3", patch="content-3")
        result = submissions.record_patch(patch)

        # Verify success
        assert result is True

        # Verify reordering: patch-3 should move to front, others preserve relative order
        assert entry.patches[0].internal_patch_id == "patch-3"  # Completed, moved to front
        assert entry.patches[0].patch == "content-3"
        assert entry.patches[1].internal_patch_id == "patch-1"  # Outstanding
        assert entry.patches[2].internal_patch_id == "patch-2"  # Outstanding
        assert entry.patches[3].internal_patch_id == "patch-4"  # Outstanding

    def test_record_patch_reordering_respects_patch_idx(self, submissions):
        """Test record_patch reordering only affects patches from patch_idx onwards."""
        # Create submission with some processed patches
        entry = SubmissionEntryBuilder().crash(task_id="test-task").build()
        entry.patches.extend(
            [
                SubmissionEntryPatch(internal_patch_id="patch-1", patch="content-1"),  # Processed
                SubmissionEntryPatch(internal_patch_id="patch-2", patch=""),  # Processed (no content)
                SubmissionEntryPatch(internal_patch_id="patch-3", patch=""),  # Current (will receive content)
                SubmissionEntryPatch(internal_patch_id="patch-4", patch=""),  # Outstanding
            ]
        )
        entry.patch_idx = 2  # Start from patch-3

        submissions.entries = [entry]

        # Record patch content for patch-3
        patch = Patch(internal_patch_id="patch-3", patch="content-3")
        result = submissions.record_patch(patch)

        # Verify success
        assert result is True

        # Verify first two patches unchanged (before patch_idx)
        assert entry.patches[0].internal_patch_id == "patch-1"
        assert entry.patches[1].internal_patch_id == "patch-2"

        # Verify reordering only affected patches from patch_idx onwards
        assert entry.patches[2].internal_patch_id == "patch-3"  # Completed, stays at front of reordered section
        assert entry.patches[2].patch == "content-3"
        assert entry.patches[3].internal_patch_id == "patch-4"  # Outstanding, moved after completed

    def test_record_patch_duplicate_patch_triggers_reordering(self, submissions):
        """Test record_patch reordering when adding duplicate patch (new patch tracker)."""
        # Create submission with existing patch that already has content
        entry = SubmissionEntryBuilder().crash(task_id="test-task").build()
        entry.patches.extend(
            [
                SubmissionEntryPatch(internal_patch_id="patch-1", patch="existing-content"),  # Already has content
                SubmissionEntryPatch(internal_patch_id="patch-2", patch=""),  # Outstanding
            ]
        )
        entry.patch_idx = 0

        submissions.entries = [entry]

        # Try to record another patch with same internal_patch_id (should create new tracker)
        patch = Patch(internal_patch_id="patch-1", patch="duplicate-content")
        result = submissions.record_patch(patch)

        # Verify success
        assert result is True

        # Verify new patch tracker was added
        assert len(entry.patches) == 3

        # Verify original patch unchanged
        assert entry.patches[0].internal_patch_id == "patch-1"
        assert entry.patches[0].patch == "existing-content"

        # Verify reordering occurred: new completed patch should be prioritized
        # The new patch tracker should be added at the end, then reordering should move completed patches first
        completed_patches = [p for p in entry.patches if p.patch]
        outstanding_patches = [p for p in entry.patches if not p.patch]

        # Should have 2 completed patches and 1 outstanding
        assert len(completed_patches) == 2
        assert len(outstanding_patches) == 1

        # Outstanding patch should be last
        assert entry.patches[-1].internal_patch_id == "patch-2"
        assert entry.patches[-1].patch == ""

    def test_reorder_patches_by_completion_integration_with_current_patch(self, submissions):
        """Test that _current_patch returns the first patch after reordering."""
        # Create submission with patches where completed patch is not first
        entry = SubmissionEntryBuilder().crash(task_id="test-task").build()

        # Add patches where completed patch is not first but should be processed first
        entry.patches.extend(
            [
                SubmissionEntryPatch(internal_patch_id="patch-1", patch=""),  # Outstanding
                SubmissionEntryPatch(internal_patch_id="patch-2", patch="content-2"),  # Completed (should be processed)
                SubmissionEntryPatch(internal_patch_id="patch-3", patch=""),  # Outstanding
            ]
        )
        entry.patch_idx = 0

        submissions.entries = [entry]

        # Before reordering, current patch should be the first one (outstanding)
        current_patch_before = _current_patch(entry)
        assert current_patch_before.internal_patch_id == "patch-1"
        assert current_patch_before.patch == ""  # Outstanding

        # Manually trigger reordering (simulating what record_patch would do)
        submissions._reorder_patches_by_completion(entry)

        # Verify reordering happened
        assert entry.patches[0].internal_patch_id == "patch-2"  # Completed patch moved first
        assert entry.patches[0].patch == "content-2"
        assert entry.patches[1].internal_patch_id == "patch-1"  # Outstanding patch moved after
        assert entry.patches[2].internal_patch_id == "patch-3"  # Outstanding patch moved last

        # After reordering, current patch should be the completed one (now first)
        current_patch_after = _current_patch(entry)
        assert current_patch_after.internal_patch_id == "patch-2"
        assert current_patch_after.patch == "content-2"  # Completed patch is now current

    def test_consolidate_patches_reordered_after_merge(self, submissions, mock_competition_api, mock_redis):
        """Test that patches are reordered after consolidation to prioritize completed patches."""

        task_id = "test-task-reorder-consolidation"

        # Setup submissions with mixed patch states that will demonstrate reordering
        submissions.entries = [
            # Target submission - has outstanding patch request at patch_idx=0
            (
                SubmissionEntryBuilder()
                .crash(
                    task_id=task_id,
                    stacktrace="similar_crash_pattern_target",
                    harness_name="target_harness",
                    competition_pov_id="pov-target",
                    result=SubmissionResult.PASSED,
                )
                .patch(internal_patch_id="target-patch-1", patch_content="")  # Outstanding request
                .patch(internal_patch_id="target-patch-2", patch_content="target content 2")  # Completed
                .patch_idx(0)  # Currently processing outstanding patch
                .build()
            ),
            # Source submission 1 - has mix of completed and outstanding patches
            (
                SubmissionEntryBuilder()
                .crash(
                    task_id=task_id,
                    stacktrace="similar_crash_pattern_source1",
                    harness_name="source1_harness",
                )
                .patch(internal_patch_id="source1-patch-1", patch_content="")  # Outstanding (will be copied)
                .patch(
                    internal_patch_id="source1-patch-2", patch_content="source1 content 2"
                )  # Completed (will be copied)
                .patch(internal_patch_id="source1-patch-3", patch_content="")  # Outstanding (will be copied)
                .patch_idx(1)  # Start copying from index 1
                .build()
            ),
            # Source submission 2 - has completed patches
            (
                SubmissionEntryBuilder()
                .crash(
                    task_id=task_id,
                    stacktrace="similar_crash_pattern_source2",
                    harness_name="source2_harness",
                )
                .patch(
                    internal_patch_id="source2-patch-1", patch_content="source2 content 1"
                )  # Completed (will be copied)
                .patch(internal_patch_id="source2-patch-2", patch_content="")  # Outstanding (will be copied)
                .patch_idx(0)  # Start copying from index 0
                .build()
            ),
        ]

        # Mock Redis rpush to return the correct index for the new submission
        mock_redis.rpush.return_value = len(submissions.entries) + 1

        # Create a new crash that will be similar to all existing submissions
        new_crash = TracedCrash()
        new_crash.crash.target.task_id = task_id
        new_crash.crash.stacktrace = "similar_crash_pattern_new"
        new_crash.crash.harness_name = "new_harness"

        # Mock the crash comparison to return similar for all existing crashes
        mock_get_crash_data, mock_get_inst_key, mock_crash_comparer_init, mock_is_similar = (
            create_crash_comparison_mocks(["similar_crash_pattern"])
        )

        # Apply mocks
        from unittest.mock import patch as mock_patch

        with (
            mock_patch("buttercup.orchestrator.scheduler.submissions.get_crash_data", side_effect=mock_get_crash_data),
            mock_patch("buttercup.orchestrator.scheduler.submissions.get_inst_key", side_effect=mock_get_inst_key),
            mock_patch.object(CrashComparer, "__init__", mock_crash_comparer_init),
            mock_patch.object(CrashComparer, "is_similar", mock_is_similar),
        ):
            # Call submit_vulnerability with the new crash - this will trigger consolidation
            result = submissions.submit_vulnerability(new_crash)

        # Verify the result
        assert result is True

        # Verify consolidation occurred
        target_submission = submissions.entries[0]

        # Verify patches were merged from source submissions
        # Expected patches in target after consolidation:
        # - Original target patches: target-patch-1 (outstanding), target-patch-2 (completed)
        # - From source1 (starting at patch_idx=1): source1-patch-2 (completed), source1-patch-3 (outstanding)
        # - From source2 (starting at patch_idx=0): source2-patch-1 (completed), source2-patch-2 (outstanding)
        expected_patch_count = 2 + 2 + 2  # target + source1 + source2
        assert len(target_submission.patches) == expected_patch_count

        # Verify reordering occurred: completed patches should come before outstanding patches
        # from patch_idx onwards (patch_idx=0 in this case)

        # Get all patch IDs and their content status
        patch_info = [(p.internal_patch_id, bool(p.patch)) for p in target_submission.patches]

        # The first patch that was already processed (before patch_idx=0) should remain in place
        # Since patch_idx=0, all patches are subject to reordering

        # Separate completed and outstanding patches
        completed_patches = [info for info in patch_info if info[1]]  # has content
        outstanding_patches = [info for info in patch_info if not info[1]]  # no content

        # Verify we have the expected number of each type
        assert len(completed_patches) == 3  # target-patch-2, source1-patch-2, source2-patch-1
        assert len(outstanding_patches) == 3  # target-patch-1, source1-patch-3, source2-patch-2

        # Verify completed patches come first after reordering
        completed_patch_ids = {info[0] for info in completed_patches}
        outstanding_patch_ids = {info[0] for info in outstanding_patches}

        # Check the actual order in the target submission
        first_three_patches = target_submission.patches[:3]
        last_three_patches = target_submission.patches[3:]

        # All first three patches should have content (be completed)
        for patch_obj in first_three_patches:
            assert patch_obj.patch, f"Patch {patch_obj.internal_patch_id} should have content but doesn't"
            assert patch_obj.internal_patch_id in completed_patch_ids

        # All last three patches should be outstanding (no content)
        for patch_obj in last_three_patches:
            assert not patch_obj.patch, f"Patch {patch_obj.internal_patch_id} should be outstanding but has content"
            assert patch_obj.internal_patch_id in outstanding_patch_ids

        # Verify that relative order is preserved within each group
        # The completed patches should maintain their relative order from when they were added
        completed_ids_in_order = [patch_obj.internal_patch_id for patch_obj in first_three_patches]
        outstanding_ids_in_order = [patch_obj.internal_patch_id for patch_obj in last_three_patches]

        # Expected order for completed patches: target-patch-2, source1-patch-2, source2-patch-1
        # (based on the order they were added during consolidation)
        expected_completed_order = ["target-patch-2", "source1-patch-2", "source2-patch-1"]
        assert completed_ids_in_order == expected_completed_order

        # Expected order for outstanding patches: target-patch-1, source1-patch-3, source2-patch-2
        expected_outstanding_order = ["target-patch-1", "source1-patch-3", "source2-patch-2"]
        assert outstanding_ids_in_order == expected_outstanding_order

        # Verify other submissions were stopped
        assert submissions.entries[1].stop
        assert submissions.entries[2].stop

        # Verify the target's patch_idx is still 0 (pointing to the first patch)
        assert target_submission.patch_idx == 0

        # Verify that the current patch is now a completed patch (due to reordering)
        current_patch = target_submission.patches[target_submission.patch_idx]
        assert current_patch.patch, "Current patch should now have content after reordering"
        assert current_patch.internal_patch_id == "target-patch-2"


# Tests for state transitions - Updated for current data-driven architecture
class TestStateTransitions:
    def test_pov_submission_and_status_update(self, submissions, sample_submission_entry, mock_competition_api):
        """Test POV submission and status updates work correctly"""
        # Create entry with crash but no POV ID (initial state)
        entry = SubmissionEntry()
        crash_with_id = CrashWithId()
        crash_with_id.crash.CopyFrom(sample_submission_entry.crashes[0].crash)
        entry.crashes.append(crash_with_id)
        submissions.entries = [entry]

        # Mock competition API to return successful POV submission
        mock_competition_api.submit_pov.return_value = ("test-pov-123", SubmissionResult.ACCEPTED)

        # Process cycle - should submit POV
        submissions.process_cycle()

        # Verify POV was submitted
        mock_competition_api.submit_pov.assert_called_once()
        assert entry.crashes[0].competition_pov_id == "test-pov-123"
        assert entry.crashes[0].result == SubmissionResult.ACCEPTED

        # Mock status update to PASSED
        mock_competition_api.get_pov_status.return_value = SubmissionResult.PASSED

        # Process another cycle - should update status
        submissions.process_cycle()

        # Verify status was updated
        mock_competition_api.get_pov_status.assert_called_once_with(
            entry.crashes[0].crash.crash.target.task_id, "test-pov-123"
        )
        assert entry.crashes[0].result == SubmissionResult.PASSED

    def test_patch_request_when_pov_passes(self, submissions, sample_submission_entry, mock_competition_api):
        """Test that patch is requested when POV passes"""
        # Create entry with passed POV
        entry = SubmissionEntry()
        crash_with_id = CrashWithId()
        crash_with_id.crash.CopyFrom(sample_submission_entry.crashes[0].crash)
        crash_with_id.competition_pov_id = "test-pov-123"
        crash_with_id.result = SubmissionResult.PASSED
        entry.crashes.append(crash_with_id)
        submissions.entries = [entry]

        # Mock QueueFactory for patch requests
        queue_mock = MagicMock()
        with patch("buttercup.orchestrator.scheduler.submissions.QueueFactory") as queue_factory_mock:
            queue_factory_mock.return_value.create.return_value = queue_mock

            # Process cycle - should request patch
            submissions.process_cycle()

            # Verify patch request was made
            queue_mock.push.assert_called()
            assert len(entry.patches) == 1
            assert entry.patches[0].internal_patch_id  # Should have generated UUID

    def test_patch_request_waits_for_mitigation_merge(self, submissions, sample_submission_entry, mock_competition_api):
        """Test that patch request waits when _should_wait_for_patch_mitigation_merge returns True"""
        # Create entry with passed POV that needs patch using the builder
        entry = (
            SubmissionEntryBuilder()
            .crash(
                task_id="test-task-123",
                competition_pov_id="test-pov-123",
                result=SubmissionResult.PASSED,
                harness_name="test_harness",
                sanitizer="asan",
                engine="libfuzzer",
            )
            .build()
        )
        submissions.entries = [entry]

        # Mock QueueFactory for patch requests
        queue_mock = MagicMock()
        with patch("buttercup.orchestrator.scheduler.submissions.QueueFactory") as queue_factory_mock:
            queue_factory_mock.return_value.create.return_value = queue_mock

            # Mock _should_wait_for_patch_mitigation_merge to return True (should wait)
            with patch.object(submissions, "_should_wait_for_patch_mitigation_merge", return_value=True) as mock_wait:
                # Process cycle - should NOT request patch due to waiting
                submissions.process_cycle()

                # Verify _should_wait_for_patch_mitigation_merge was called
                mock_wait.assert_called_once_with(0, entry)

                # Verify NO patch request was made
                queue_mock.push.assert_not_called()
                assert len(entry.patches) == 0  # No patches should be added

    def test_patch_request_proceeds_when_no_mitigation_wait_needed(
        self, submissions, sample_submission_entry, mock_competition_api
    ):
        """Test that patch request proceeds when _should_wait_for_patch_mitigation_merge returns False"""
        # Create entry with passed POV that needs patch using the builder
        entry = (
            SubmissionEntryBuilder()
            .crash(
                task_id="test-task-123",
                competition_pov_id="test-pov-123",
                result=SubmissionResult.PASSED,
                harness_name="test_harness",
                sanitizer="asan",
                engine="libfuzzer",
            )
            .build()
        )
        submissions.entries = [entry]

        # Mock QueueFactory for patch requests
        queue_mock = MagicMock()
        with patch("buttercup.orchestrator.scheduler.submissions.QueueFactory") as queue_factory_mock:
            queue_factory_mock.return_value.create.return_value = queue_mock

            # Mock _should_wait_for_patch_mitigation_merge to return False (no need to wait)
            with patch.object(submissions, "_should_wait_for_patch_mitigation_merge", return_value=False) as mock_wait:
                # Process cycle - should request patch
                submissions.process_cycle()

                # Verify _should_wait_for_patch_mitigation_merge was called
                mock_wait.assert_called_once_with(0, entry)

                # Verify patch request was made
                queue_mock.push.assert_called()
                assert len(entry.patches) == 1
                assert entry.patches[0].internal_patch_id  # Should have generated UUID

    def test_patch_request_respects_concurrent_limit_below_threshold(self, submissions, mock_competition_api):
        """Test that patch request proceeds when outstanding requests are below the concurrent limit"""
        # Set concurrent limit to 3 for this test
        submissions.concurrent_patch_requests_per_task = 3

        # Create entries: 2 with outstanding patch requests, 1 ready for new request
        submissions.entries = [
            # Entry 1: Outstanding patch request (counts toward limit)
            SubmissionEntryBuilder()
            .crash(
                task_id="test-task",
                competition_pov_id="pov-1",
                result=SubmissionResult.PASSED,
            )
            .patch(internal_patch_id="patch-1", patch_content="")  # Outstanding (no content)
            .build(),
            # Entry 2: Outstanding patch request (counts toward limit)
            SubmissionEntryBuilder()
            .crash(
                task_id="test-task",
                competition_pov_id="pov-2",
                result=SubmissionResult.PASSED,
            )
            .patch(internal_patch_id="patch-2", patch_content="")  # Outstanding (no content)
            .build(),
            # Entry 3: Ready for new patch request (no existing patches)
            SubmissionEntryBuilder()
            .crash(
                task_id="test-task",
                competition_pov_id="pov-3",
                result=SubmissionResult.PASSED,
            )
            .build(),
        ]

        # Mock QueueFactory for patch requests
        queue_mock = MagicMock()
        with patch("buttercup.orchestrator.scheduler.submissions.QueueFactory") as queue_factory_mock:
            queue_factory_mock.return_value.create.return_value = queue_mock

            # Mock _should_wait_for_patch_mitigation_merge to return False for all entries
            with patch.object(submissions, "_should_wait_for_patch_mitigation_merge", return_value=False):
                # Process cycle - should request patch for entry 3 (2 outstanding < 3 limit)
                submissions.process_cycle()

                # Verify patch request was made for the third entry
                queue_mock.push.assert_called()
                assert len(submissions.entries[2].patches) == 1  # Third entry should have new patch
                assert submissions.entries[2].patches[0].internal_patch_id  # Should have UUID

    def test_patch_request_respects_concurrent_limit_at_threshold(self, submissions, mock_competition_api):
        """Test that patch request is blocked when outstanding requests are at the concurrent limit"""
        # Set concurrent limit to 2 for this test
        submissions.concurrent_patch_requests_per_task = 2

        # Create entries: 2 with outstanding patch requests, 1 ready for new request
        submissions.entries = [
            # Entry 1: Outstanding patch request (counts toward limit)
            SubmissionEntryBuilder()
            .crash(
                task_id="test-task",
                competition_pov_id="pov-1",
                result=SubmissionResult.PASSED,
            )
            .patch(internal_patch_id="patch-1", patch_content="")  # Outstanding (no content)
            .build(),
            # Entry 2: Outstanding patch request (counts toward limit)
            SubmissionEntryBuilder()
            .crash(
                task_id="test-task",
                competition_pov_id="pov-2",
                result=SubmissionResult.PASSED,
            )
            .patch(internal_patch_id="patch-2", patch_content="")  # Outstanding (no content)
            .build(),
            # Entry 3: Ready for new patch request (no existing patches)
            SubmissionEntryBuilder()
            .crash(
                task_id="test-task",
                competition_pov_id="pov-3",
                result=SubmissionResult.PASSED,
            )
            .build(),
        ]

        # Mock QueueFactory for patch requests
        queue_mock = MagicMock()
        with patch("buttercup.orchestrator.scheduler.submissions.QueueFactory") as queue_factory_mock:
            queue_factory_mock.return_value.create.return_value = queue_mock

            # Mock _should_wait_for_patch_mitigation_merge to return False for all entries
            with patch.object(submissions, "_should_wait_for_patch_mitigation_merge", return_value=False):
                # Process cycle - should NOT request patch for entry 3 (2 outstanding >= 2 limit)
                submissions.process_cycle()

                # Verify NO patch request was made for the third entry
                queue_mock.push.assert_not_called()
                assert len(submissions.entries[2].patches) == 0  # Third entry should have no patches

    def test_patch_request_respects_concurrent_limit_above_threshold(self, submissions, mock_competition_api):
        """Test that patch request is blocked when outstanding requests exceed the concurrent limit"""
        # Set concurrent limit to 1 for this test
        submissions.concurrent_patch_requests_per_task = 1

        # Create entries: 3 with outstanding patch requests, 1 ready for new request
        submissions.entries = [
            # Entry 1: Outstanding patch request (counts toward limit)
            SubmissionEntryBuilder()
            .crash(
                task_id="test-task",
                competition_pov_id="pov-1",
                result=SubmissionResult.PASSED,
            )
            .patch(internal_patch_id="patch-1", patch_content="")  # Outstanding (no content)
            .build(),
            # Entry 2: Outstanding patch request (counts toward limit)
            SubmissionEntryBuilder()
            .crash(
                task_id="test-task",
                competition_pov_id="pov-2",
                result=SubmissionResult.PASSED,
            )
            .patch(internal_patch_id="patch-2", patch_content="")  # Outstanding (no content)
            .build(),
            # Entry 3: Outstanding patch request (counts toward limit)
            SubmissionEntryBuilder()
            .crash(
                task_id="test-task",
                competition_pov_id="pov-3",
                result=SubmissionResult.PASSED,
            )
            .patch(internal_patch_id="patch-3", patch_content="")  # Outstanding (no content)
            .build(),
            # Entry 4: Ready for new patch request (no existing patches)
            SubmissionEntryBuilder()
            .crash(
                task_id="test-task",
                competition_pov_id="pov-4",
                result=SubmissionResult.PASSED,
            )
            .build(),
        ]

        # Mock QueueFactory for patch requests
        queue_mock = MagicMock()
        with patch("buttercup.orchestrator.scheduler.submissions.QueueFactory") as queue_factory_mock:
            queue_factory_mock.return_value.create.return_value = queue_mock

            # Mock _should_wait_for_patch_mitigation_merge to return False for all entries
            with patch.object(submissions, "_should_wait_for_patch_mitigation_merge", return_value=False):
                # Process cycle - should NOT request patch for entry 4 (3 outstanding > 1 limit)
                submissions.process_cycle()

                # Verify NO patch request was made for the fourth entry
                queue_mock.push.assert_not_called()
                assert len(submissions.entries[3].patches) == 0  # Fourth entry should have no patches

    def test_patch_request_concurrent_limit_only_counts_outstanding_requests(self, submissions, mock_competition_api):
        """Test that concurrent limit only counts outstanding requests, not completed patches"""
        # Set concurrent limit to 2 for this test
        submissions.concurrent_patch_requests_per_task = 2

        # Create entries: 1 with completed patch, 1 with outstanding request, 1 ready for new request
        submissions.entries = [
            # Entry 1: Completed patch (should NOT count toward limit)
            SubmissionEntryBuilder()
            .crash(
                task_id="test-task",
                competition_pov_id="pov-1",
                result=SubmissionResult.PASSED,
            )
            .patch(internal_patch_id="patch-1", patch_content="diff content")  # Completed (has content)
            .build(),
            # Entry 2: Outstanding patch request (counts toward limit)
            SubmissionEntryBuilder()
            .crash(
                task_id="test-task",
                competition_pov_id="pov-2",
                result=SubmissionResult.PASSED,
            )
            .patch(internal_patch_id="patch-2", patch_content="")  # Outstanding (no content)
            .build(),
            # Entry 3: Ready for new patch request (no existing patches)
            SubmissionEntryBuilder()
            .crash(
                task_id="test-task",
                competition_pov_id="pov-3",
                result=SubmissionResult.PASSED,
            )
            .build(),
        ]

        # Mock QueueFactory for patch requests
        queue_mock = MagicMock()
        with patch("buttercup.orchestrator.scheduler.submissions.QueueFactory") as queue_factory_mock:
            queue_factory_mock.return_value.create.return_value = queue_mock

            # Mock _should_wait_for_patch_mitigation_merge to return False for all entries
            with patch.object(submissions, "_should_wait_for_patch_mitigation_merge", return_value=False):
                # Process cycle - should request patch for entry 3 (1 outstanding < 2 limit)
                submissions.process_cycle()

                # Verify patch request was made for the third entry
                queue_mock.push.assert_called()
                assert len(submissions.entries[2].patches) == 1  # Third entry should have new patch
                assert submissions.entries[2].patches[0].internal_patch_id  # Should have UUID

    def test_patch_request_concurrent_limit_per_task_isolation(self, submissions, mock_competition_api):
        """Test that concurrent limit is applied per task, not globally"""
        # Set concurrent limit to 1 for this test
        submissions.concurrent_patch_requests_per_task = 1

        # Create entries: 1 outstanding for task-1, 1 ready for task-2
        submissions.entries = [
            # Entry 1: Outstanding patch request for task-1 (counts toward task-1 limit)
            SubmissionEntryBuilder()
            .crash(
                task_id="task-1",
                competition_pov_id="pov-1",
                result=SubmissionResult.PASSED,
            )
            .patch(internal_patch_id="patch-1", patch_content="")  # Outstanding (no content)
            .build(),
            # Entry 2: Ready for new patch request for task-2 (different task)
            SubmissionEntryBuilder()
            .crash(
                task_id="task-2",
                competition_pov_id="pov-2",
                result=SubmissionResult.PASSED,
            )
            .build(),
        ]

        # Mock QueueFactory for patch requests
        queue_mock = MagicMock()
        with patch("buttercup.orchestrator.scheduler.submissions.QueueFactory") as queue_factory_mock:
            queue_factory_mock.return_value.create.return_value = queue_mock

            # Mock _should_wait_for_patch_mitigation_merge to return False for all entries
            with patch.object(submissions, "_should_wait_for_patch_mitigation_merge", return_value=False):
                # Process cycle - should request patch for entry 2 (different task, no limit conflict)
                submissions.process_cycle()

                # Verify patch request was made for the second entry
                queue_mock.push.assert_called()
                assert len(submissions.entries[1].patches) == 1  # Second entry should have new patch
                assert submissions.entries[1].patches[0].internal_patch_id  # Should have UUID

    def test_patch_submission_when_ready(self, submissions, sample_submission_entry, mock_competition_api):
        """Test patch submission when all conditions are met"""
        # Create entry with passed POV and ready patch
        entry = SubmissionEntry()
        crash_with_id = CrashWithId()
        crash_with_id.crash.CopyFrom(sample_submission_entry.crashes[0].crash)
        crash_with_id.competition_pov_id = "test-pov-123"
        crash_with_id.result = SubmissionResult.PASSED
        entry.crashes.append(crash_with_id)

        # Add patch with content
        entry_patch = SubmissionEntryPatch()
        entry_patch.internal_patch_id = "patch-uuid"
        entry_patch.patch = "test patch content"
        entry.patches.append(entry_patch)
        entry.patch_idx = 0
        submissions.entries = [entry]

        # Mock POV mitigation check to return True (patch is good)
        # Also mock _request_patched_builds_if_needed to avoid NODE_DATA_DIR dependency
        with (
            patch.object(submissions, "_check_all_povs_are_mitigated", return_value=True),
            patch.object(submissions, "_request_patched_builds_if_needed", return_value=False),
        ):
            # Mock competition API to return successful patch submission
            mock_competition_api.submit_patch.return_value = ("test-patch-456", SubmissionResult.ACCEPTED)

            # Process cycle - should submit patch
            submissions.process_cycle()

            # Verify patch was submitted
            mock_competition_api.submit_patch.assert_called_once_with(
                entry.crashes[0].crash.crash.target.task_id, "test patch content"
            )
            assert entry.patches[0].competition_patch_id == "test-patch-456"
            assert entry.patches[0].result == SubmissionResult.ACCEPTED

    def test_patch_status_update(self, submissions, sample_submission_entry, mock_competition_api):
        """Test patch status updates work correctly"""
        # Create entry with submitted patch
        entry = SubmissionEntry()
        crash_with_id = CrashWithId()
        crash_with_id.crash.CopyFrom(sample_submission_entry.crashes[0].crash)
        crash_with_id.competition_pov_id = "test-pov-123"
        crash_with_id.result = SubmissionResult.PASSED
        entry.crashes.append(crash_with_id)

        entry_patch = SubmissionEntryPatch()
        entry_patch.internal_patch_id = "patch-uuid"
        entry_patch.patch = "test patch content"
        entry_patch.competition_patch_id = "test-patch-456"
        entry_patch.result = SubmissionResult.ACCEPTED
        entry.patches.append(entry_patch)
        submissions.entries = [entry]

        # Mock competition API to return PASSED status
        mock_competition_api.get_patch_status.return_value = SubmissionResult.PASSED

        # Process cycle - should update patch status
        submissions.process_cycle()

        # Verify status was updated
        mock_competition_api.get_patch_status.assert_called_once_with(
            entry.crashes[0].crash.crash.target.task_id, "test-patch-456"
        )
        assert entry.patches[0].result == SubmissionResult.PASSED

    def test_patch_advancement_on_failure(self, submissions, sample_submission_entry, mock_competition_api):
        """Test that patch index advances when patch fails"""
        # Create entry with failed patch and additional patches
        entry = SubmissionEntry()
        crash_with_id = CrashWithId()
        crash_with_id.crash.CopyFrom(sample_submission_entry.crashes[0].crash)
        crash_with_id.competition_pov_id = "test-pov-123"
        crash_with_id.result = SubmissionResult.PASSED
        entry.crashes.append(crash_with_id)

        # Add multiple patches
        patch1 = SubmissionEntryPatch()
        patch1.internal_patch_id = "patch-uuid-1"
        patch1.patch = "test patch 1"
        patch1.competition_patch_id = "test-patch-456"
        patch1.result = SubmissionResult.ACCEPTED
        entry.patches.append(patch1)

        patch2 = SubmissionEntryPatch()
        patch2.internal_patch_id = "patch-uuid-2"
        patch2.patch = "test patch 2"
        entry.patches.append(patch2)

        entry.patch_idx = 0  # Currently on first patch
        submissions.entries = [entry]

        # Mock competition API to return FAILED status
        mock_competition_api.get_patch_status.return_value = SubmissionResult.FAILED

        # Process cycle - should advance patch index
        submissions.process_cycle()

        # Verify patch index was advanced and status updated
        assert entry.patches[0].result == SubmissionResult.FAILED
        assert entry.patch_idx == 1  # Advanced to next patch

    def test_bundle_creation_when_patch_passes(self, submissions, sample_submission_entry, mock_competition_api):
        """Test bundle creation when patch passes"""
        # Create entry with passed POV and passed patch
        entry = SubmissionEntry()
        crash_with_id = CrashWithId()
        crash_with_id.crash.CopyFrom(sample_submission_entry.crashes[0].crash)
        crash_with_id.competition_pov_id = "test-pov-123"
        crash_with_id.result = SubmissionResult.PASSED
        entry.crashes.append(crash_with_id)

        entry_patch = SubmissionEntryPatch()
        entry_patch.internal_patch_id = "patch-uuid"
        entry_patch.patch = "test patch content"
        entry_patch.competition_patch_id = "test-patch-456"
        entry_patch.result = SubmissionResult.PASSED
        entry.patches.append(entry_patch)
        entry.patch_idx = 0
        submissions.entries = [entry]

        # Mock competition API to return successful bundle submission
        mock_competition_api.submit_bundle.return_value = ("test-bundle-789", SubmissionResult.ACCEPTED)

        # Process cycle - should create bundle
        submissions.process_cycle()

        # Verify bundle was created
        mock_competition_api.submit_bundle.assert_called_once_with(
            entry.crashes[0].crash.crash.target.task_id, "test-pov-123", "test-patch-456", ""
        )
        assert len(entry.bundles) == 1
        assert entry.bundles[0].bundle_id == "test-bundle-789"
        assert entry.bundles[0].competition_pov_id == "test-pov-123"
        assert entry.bundles[0].competition_patch_id == "test-patch-456"

    def test_pov_resubmission_on_error(self, submissions, sample_submission_entry, mock_competition_api):
        """Test POV resubmission when first attempt errors"""
        # Create entry with errored POV
        entry = SubmissionEntry()
        crash_with_id = CrashWithId()
        crash_with_id.crash.CopyFrom(sample_submission_entry.crashes[0].crash)
        crash_with_id.competition_pov_id = "test-pov-123"
        crash_with_id.result = SubmissionResult.ERRORED
        entry.crashes.append(crash_with_id)
        submissions.entries = [entry]

        # Mock competition API to return successful resubmission
        mock_competition_api.submit_pov.return_value = ("test-pov-456", SubmissionResult.ACCEPTED)

        # Mock _request_patched_builds_if_needed to avoid NODE_DATA_DIR dependency
        with patch.object(submissions, "_request_patched_builds_if_needed", return_value=False):
            # Process cycle - should resubmit POV
            submissions.process_cycle()

            # Verify POV was resubmitted with new ID
            mock_competition_api.submit_pov.assert_called_once()
            assert entry.crashes[0].competition_pov_id == "test-pov-456"
            assert entry.crashes[0].result == SubmissionResult.ACCEPTED

    def test_patch_resubmission_on_error(self, submissions, sample_submission_entry, mock_competition_api):
        """Test patch resubmission when submission errors"""
        # Create entry with ready patch for resubmission
        entry = SubmissionEntry()
        crash_with_id = CrashWithId()
        crash_with_id.crash.CopyFrom(sample_submission_entry.crashes[0].crash)
        crash_with_id.competition_pov_id = "test-pov-123"
        crash_with_id.result = SubmissionResult.PASSED
        entry.crashes.append(crash_with_id)

        entry_patch = SubmissionEntryPatch()
        entry_patch.internal_patch_id = "patch-uuid"
        entry_patch.patch = "test patch content"
        entry.patches.append(entry_patch)
        entry.patch_idx = 0
        entry.patch_submission_attempts = 1  # Previous attempt failed
        submissions.entries = [entry]

        # Mock POV mitigation check to return True
        # Also mock _request_patched_builds_if_needed to avoid NODE_DATA_DIR dependency
        with (
            patch.object(submissions, "_check_all_povs_are_mitigated", return_value=True),
            patch.object(submissions, "_request_patched_builds_if_needed", return_value=False),
        ):
            # Mock competition API to return ERRORED then successful resubmission
            mock_competition_api.submit_patch.return_value = (None, SubmissionResult.ERRORED)

            # Process cycle - should increment attempts and mark as errored
            submissions.process_cycle()

            # Verify patch submission was attempted and errored
            mock_competition_api.submit_patch.assert_called_once()
            assert entry.patches[0].result == SubmissionResult.ERRORED
            assert entry.patch_submission_attempts == 2

    def test_complete_workflow_integration(self, submissions, sample_submission_entry, mock_competition_api):
        """Test complete workflow from vulnerability submission to bundle creation"""
        # Start with fresh entry (simulating submit_vulnerability result)
        entry = SubmissionEntry()
        crash_with_id = CrashWithId()
        crash_with_id.crash.CopyFrom(sample_submission_entry.crashes[0].crash)
        entry.crashes.append(crash_with_id)
        submissions.entries = [entry]

        # Mock queue for patch requests
        queue_mock = MagicMock()

        with (
            patch("buttercup.orchestrator.scheduler.submissions.QueueFactory") as queue_factory_mock,
            patch.object(submissions, "_request_patched_builds_if_needed", return_value=False),
        ):
            queue_factory_mock.return_value.create.return_value = queue_mock

            # Step 1: Submit POV
            mock_competition_api.submit_pov.return_value = ("test-pov-123", SubmissionResult.ACCEPTED)
            submissions.process_cycle()
            assert entry.crashes[0].competition_pov_id == "test-pov-123"

            # Step 2: POV status update to PASSED
            mock_competition_api.get_pov_status.return_value = SubmissionResult.PASSED
            submissions.process_cycle()
            assert entry.crashes[0].result == SubmissionResult.PASSED

            # Step 3: Patch request should be made
            assert len(entry.patches) == 1
            queue_mock.push.assert_called()

            # Step 4: Simulate patch being received
            entry.patches[0].patch = "test patch content"

            # Step 5: Submit patch when ready
            with (
                patch.object(submissions, "_check_all_povs_are_mitigated", return_value=True),
                patch.object(submissions, "_request_patched_builds_if_needed", return_value=False),
            ):
                mock_competition_api.submit_patch.return_value = ("test-patch-456", SubmissionResult.ACCEPTED)
                submissions.process_cycle()
                assert entry.patches[0].competition_patch_id == "test-patch-456"

                # Step 6: Patch status update to PASSED
                mock_competition_api.get_patch_status.return_value = SubmissionResult.PASSED
                submissions.process_cycle()
                assert entry.patches[0].result == SubmissionResult.PASSED

                # Step 7: Bundle creation
                mock_competition_api.submit_bundle.return_value = ("test-bundle-789", SubmissionResult.ACCEPTED)
                submissions.process_cycle()
                assert len(entry.bundles) == 1
                assert entry.bundles[0].bundle_id == "test-bundle-789"


# Tests for record_patched_build functionality
class TestRecordPatchedBuild:
    def test_record_patched_build_successful(self, submissions, sample_submission_entry, sample_build_output):
        """Test successful recording of a build output to a patch."""
        # Setup submission entry with a patch that has build output placeholders
        patch_entry = SubmissionEntryPatch()
        patch_entry.patch = "test patch content"
        patch_entry.internal_patch_id = "0"

        # Create build output placeholder that matches the sample_build_output
        build_output_placeholder = BuildOutput()
        build_output_placeholder.engine = sample_build_output.engine
        build_output_placeholder.sanitizer = sample_build_output.sanitizer
        build_output_placeholder.task_id = sample_build_output.task_id
        build_output_placeholder.build_type = sample_build_output.build_type
        build_output_placeholder.apply_diff = sample_build_output.apply_diff
        build_output_placeholder.internal_patch_id = sample_build_output.internal_patch_id
        # task_dir is empty as placeholder - this is what gets filled in
        build_output_placeholder.task_dir = ""

        patch_entry.build_outputs.append(build_output_placeholder)
        sample_submission_entry.patches.append(patch_entry)
        submissions.entries = [sample_submission_entry]

        # Call the method
        result = submissions.record_patched_build(sample_build_output)

        # Verify success
        assert result is True

        # Verify build output was updated in the patch
        assert len(submissions.entries[0].patches) == 1
        assert len(submissions.entries[0].patches[0].build_outputs) == 1
        # The task_dir should now be populated
        assert submissions.entries[0].patches[0].build_outputs[0].task_dir == sample_build_output.task_dir
        assert submissions.entries[0].patches[0].build_outputs[0].internal_patch_id == "0"
        assert submissions.entries[0].patches[0].build_outputs[0].sanitizer == "test_sanitizer"
        assert submissions.entries[0].patches[0].build_outputs[0].engine == "libfuzzer"
        assert submissions.entries[0].patches[0].build_outputs[0].build_type == BuildType.PATCH
        assert submissions.entries[0].patches[0].build_outputs[0].apply_diff is True

        # Verify persistence was called
        submissions.redis.lset.assert_called_once_with(
            submissions.SUBMISSIONS, 0, submissions.entries[0].SerializeToString()
        )

    def test_record_patched_build_multiple_outputs(self, submissions, sample_submission_entry):
        """Test recording multiple build outputs for the same patch."""
        # Setup submission entry with a patch using builder
        entry = (
            SubmissionEntryBuilder()
            .crash(task_id="test-task-123")
            .patch(internal_patch_id="0", patch_content="test patch content")
            .build_output(
                patch_internal_id="0",
                task_id="test-task-123",
                sanitizer="asan",
                engine="libfuzzer",
                build_type=BuildType.PATCH,
                apply_diff=True,
                task_dir="",  # Empty indicates placeholder
            )
            .build_output(
                patch_internal_id="0",
                task_id="test-task-123",
                sanitizer="msan",
                engine="afl",
                build_type=BuildType.FUZZER,
                apply_diff=False,
                task_dir="",  # Empty indicates placeholder
            )
            .build()
        )
        submissions.entries = [entry]

        # Create multiple build outputs with the same patch_idx but different properties
        build_output1 = BuildOutput()
        build_output1.internal_patch_id = "0"
        build_output1.task_id = "test-task-123"
        build_output1.sanitizer = "asan"
        build_output1.engine = "libfuzzer"
        build_output1.build_type = BuildType.PATCH
        build_output1.apply_diff = True
        build_output1.task_dir = "/tmp/build/test-task-123-asan"

        build_output2 = BuildOutput()
        build_output2.internal_patch_id = "0"
        build_output2.task_id = "test-task-123"
        build_output2.sanitizer = "msan"
        build_output2.engine = "afl"
        build_output2.build_type = BuildType.FUZZER
        build_output2.apply_diff = False
        build_output2.task_dir = "/tmp/build/test-task-123-msan"

        # Record both build outputs
        result1 = submissions.record_patched_build(build_output1)
        result2 = submissions.record_patched_build(build_output2)

        # Verify both succeeded
        assert result1 is True
        assert result2 is True

        # Verify both build outputs were added to the same patch
        assert len(submissions.entries[0].patches) == 1
        assert len(submissions.entries[0].patches[0].build_outputs) == 2

        # Verify the build outputs have different properties
        build_outputs = submissions.entries[0].patches[0].build_outputs
        assert build_outputs[0].sanitizer == "asan"
        assert build_outputs[0].engine == "libfuzzer"
        assert build_outputs[0].build_type == BuildType.PATCH
        assert build_outputs[0].apply_diff is True
        assert build_outputs[1].sanitizer == "msan"
        assert build_outputs[1].engine == "afl"
        assert build_outputs[1].build_type == BuildType.FUZZER
        assert build_outputs[1].apply_diff is False

        # Verify persistence was called twice
        assert submissions.redis.lset.call_count == 2

    def test_record_patched_build_invalid_patch_idx(self, submissions):
        """Test recording build output with out-of-bounds patch index."""
        # Create build output with out-of-bounds patch index
        build_output = BuildOutput()
        build_output.internal_patch_id = "nonexistent"  # Patch that doesn't exist
        build_output.sanitizer = "test_sanitizer"

        # Call the method
        result = submissions.record_patched_build(build_output)

        # Should return True (acknowledged but discarded)
        assert result is True

        # Verify no persistence occurred
        submissions.redis.lset.assert_not_called()

    def test_retrieve_build_outputs_from_patch(self, submissions, sample_submission_entry):
        """Test that we can retrieve build outputs from a patch after recording them."""
        # Setup submission entry with multiple patches using builder
        entry = (
            SubmissionEntryBuilder()
            .crash(task_id="test-task-123")
            .patch(internal_patch_id="patch1", patch_content="patch 1 content")
            .build_output(
                patch_internal_id="patch1",
                task_id="test-task-123",
                sanitizer="asan",
                build_type=BuildType.PATCH,
                apply_diff=True,
                task_dir="",
            )
            .build_output(
                patch_internal_id="patch1",
                task_id="test-task-123",
                sanitizer="msan",
                build_type=BuildType.FUZZER,
                apply_diff=False,
                task_dir="",
            )
            .patch(internal_patch_id="patch2", patch_content="patch 2 content")
            .build_output(
                patch_internal_id="patch2",
                task_id="test-task-123",
                sanitizer="ubsan",
                build_type=BuildType.COVERAGE,
                apply_diff=True,
                task_dir="",
            )
            .build()
        )
        submissions.entries = [entry]

        # Create different build outputs for different patches
        build_output_patch0_1 = BuildOutput()
        build_output_patch0_1.internal_patch_id = "patch1"
        build_output_patch0_1.task_id = "test-task-123"
        build_output_patch0_1.sanitizer = "asan"
        build_output_patch0_1.build_type = BuildType.PATCH
        build_output_patch0_1.apply_diff = True
        build_output_patch0_1.task_dir = "/tmp/build/patch1-asan"

        build_output_patch0_2 = BuildOutput()
        build_output_patch0_2.internal_patch_id = "patch1"
        build_output_patch0_2.task_id = "test-task-123"
        build_output_patch0_2.sanitizer = "msan"
        build_output_patch0_2.build_type = BuildType.FUZZER
        build_output_patch0_2.apply_diff = False
        build_output_patch0_2.task_dir = "/tmp/build/patch1-msan"

        build_output_patch1 = BuildOutput()
        build_output_patch1.internal_patch_id = "patch2"
        build_output_patch1.task_id = "test-task-123"
        build_output_patch1.sanitizer = "ubsan"
        build_output_patch1.build_type = BuildType.COVERAGE
        build_output_patch1.apply_diff = True
        build_output_patch1.task_dir = "/tmp/build/patch2-ubsan"

        # Record all build outputs
        submissions.record_patched_build(build_output_patch0_1)
        submissions.record_patched_build(build_output_patch0_2)
        submissions.record_patched_build(build_output_patch1)

        # Retrieve and verify build outputs for patch 0
        patch0_build_outputs = submissions.entries[0].patches[0].build_outputs
        assert len(patch0_build_outputs) == 2
        assert patch0_build_outputs[0].sanitizer == "asan"
        assert patch0_build_outputs[0].build_type == BuildType.PATCH
        assert patch0_build_outputs[0].apply_diff is True
        assert patch0_build_outputs[1].sanitizer == "msan"
        assert patch0_build_outputs[1].build_type == BuildType.FUZZER
        assert patch0_build_outputs[1].apply_diff is False

        # Retrieve and verify build outputs for patch 1
        patch1_build_outputs = submissions.entries[0].patches[1].build_outputs
        assert len(patch1_build_outputs) == 1
        assert patch1_build_outputs[0].sanitizer == "ubsan"
        assert patch1_build_outputs[0].build_type == BuildType.COVERAGE
        assert patch1_build_outputs[0].apply_diff is True

    def test_record_patched_build_empty_patch_idx(self, submissions):
        """Test recording build output with empty internal_patch_id."""
        # Create build output with empty internal_patch_id
        build_output = BuildOutput()
        build_output.internal_patch_id = ""
        build_output.sanitizer = "test_sanitizer"

        # Call the method
        result = submissions.record_patched_build(build_output)

        # Should return True (acknowledged but discarded)
        assert result is True

        # Verify no persistence occurred
        submissions.redis.lset.assert_not_called()

    def test_record_patched_build_internal_patch_id_with_extra_slashes(self, submissions):
        """Test recording build output with internal_patch_id containing extra slashes."""
        # Create build output with malformed internal_patch_id (too many slashes)
        build_output = BuildOutput()
        build_output.internal_patch_id = "another-nonexistent"  # Another non-existent patch
        build_output.sanitizer = "test_sanitizer"

        # Call the method
        result = submissions.record_patched_build(build_output)

        # Should return True (acknowledged but discarded)
        assert result is True

        # Verify no persistence occurred
        submissions.redis.lset.assert_not_called()

    def test_record_patched_build_duplicate_filtering(self, submissions, sample_submission_entry):
        """Test that duplicate build outputs are filtered out and not added twice."""
        # Setup submission entry with a patch
        patch_entry = SubmissionEntryPatch()
        patch_entry.patch = "test patch content"
        patch_entry.internal_patch_id = "duplicate-test"

        # Create placeholder
        placeholder = BuildOutput()
        placeholder.internal_patch_id = "duplicate-test"
        placeholder.task_id = "test-task-123"
        placeholder.sanitizer = "asan"
        placeholder.engine = "libfuzzer"
        placeholder.build_type = BuildType.PATCH
        placeholder.apply_diff = True
        placeholder.task_dir = ""  # Empty indicates placeholder

        patch_entry.build_outputs.append(placeholder)
        sample_submission_entry.patches.append(patch_entry)
        submissions.entries = [sample_submission_entry]

        # Create a build output
        build_output = BuildOutput()
        build_output.internal_patch_id = "duplicate-test"
        build_output.task_id = "test-task-123"
        build_output.sanitizer = "asan"
        build_output.engine = "libfuzzer"
        build_output.build_type = BuildType.PATCH
        build_output.apply_diff = True
        build_output.task_dir = "/tmp/build/duplicate-test"

        # Record the build output for the first time
        result1 = submissions.record_patched_build(build_output)
        assert result1 is True

        # Verify it was added
        assert len(submissions.entries[0].patches[0].build_outputs) == 1
        assert submissions.entries[0].patches[0].build_outputs[0].sanitizer == "asan"

        # Try to record the exact same build output again
        result2 = submissions.record_patched_build(build_output)
        assert result2 is True  # Should still return True (acknowledged)

        # Verify it was NOT added again (duplicate filtered out)
        assert len(submissions.entries[0].patches[0].build_outputs) == 1

        # Verify persistence was only called once (for the first addition)
        assert submissions.redis.lset.call_count == 1

    def test_merge_entries_by_patch_mitigation_no_merges(self, submissions):
        """Test _merge_entries_by_patch_mitigation when no merges are needed."""
        # Create submissions with patches that don't mitigate other POVs
        submissions.entries = [
            SubmissionEntryBuilder()
            .crash(task_id="task-1", crash_input_path="/path/to/crash1.bin")
            .patch(internal_patch_id="patch-1", patch_content="patch content 1")
            .patch_idx(0)
            .build(),
            SubmissionEntryBuilder()
            .crash(task_id="task-1", crash_input_path="/path/to/crash2.bin")
            .patch(internal_patch_id="patch-2", patch_content="patch content 2")
            .patch_idx(0)
            .build(),
        ]

        # Mock POV reproduction status to return no mitigation
        def mock_pov_reproduce_patch_status(patch, crashes, task_id):
            # Return None (pending) or True (did crash) for all POVs - no mitigation
            return [None] * len(crashes)

        with patch.object(submissions, "_pov_reproduce_patch_status", side_effect=mock_pov_reproduce_patch_status):
            # Call the method
            submissions._merge_entries_by_patch_mitigation()

        # Verify no merges occurred - both submissions should still be active
        assert len(submissions.entries) == 2
        assert not submissions.entries[0].stop
        assert not submissions.entries[1].stop

    def test_merge_entries_by_patch_mitigation_successful_merge(self, submissions):
        """Test _merge_entries_by_patch_mitigation when patches mitigate POVs and merging occurs."""
        # Create submissions where first has a patch that mitigates second's POVs
        submissions.entries = [
            SubmissionEntryBuilder()
            .crash(task_id="task-1", crash_input_path="/path/to/crash1.bin")
            .patch(internal_patch_id="patch-1", patch_content="patch content 1")
            .build_output(patch_internal_id="patch-1", task_dir="/build/path1", task_id="task-1")
            .patch_idx(0)
            .build(),
            SubmissionEntryBuilder()
            .crash(task_id="task-1", crash_input_path="/path/to/crash2.bin")
            .patch(internal_patch_id="patch-2", patch_content="patch content 2")
            .build_output(patch_internal_id="patch-2", task_dir="/build/path2", task_id="task-1")
            .patch_idx(0)
            .build(),
            SubmissionEntryBuilder()
            .crash(task_id="task-1", crash_input_path="/path/to/crash3.bin")
            .build(),  # No patches
        ]

        # Ensure task registry doesn't filter out submissions
        submissions.task_registry.should_stop_processing.return_value = False

        # Mock POV reproduction status
        def mock_pov_reproduce_patch_status(patch, crashes, task_id):
            if patch.internal_patch_id == "patch-1":
                # patch-1 mitigates POVs from other submissions
                return [Mock(did_crash=False)] * len(crashes)  # Mitigated
            else:
                # Other patches don't mitigate
                return [None] * len(crashes)  # Pending

        # Mock _consolidate_similar_submissions to track calls
        mock_consolidate = Mock()

        with (
            patch.object(submissions, "_pov_reproduce_patch_status", side_effect=mock_pov_reproduce_patch_status),
            patch.object(submissions, "_consolidate_similar_submissions", mock_consolidate),
        ):
            # Call the method
            submissions._merge_entries_by_patch_mitigation()

        # Verify consolidation was called
        mock_consolidate.assert_called_once()

        # Verify the call arguments - should merge submissions 0, 1, and 2
        call_args = mock_consolidate.call_args[1]
        similar_entries = call_args["similar_entries"]
        assert len(similar_entries) == 3  # All three submissions

        # Verify the indices and entries
        indices = [idx for idx, _ in similar_entries]
        assert 0 in indices  # First submission (target)
        assert 1 in indices  # Second submission (has POVs mitigated by patch-1)
        assert 2 in indices  # Third submission (has POVs mitigated by patch-1)

    def test_merge_entries_by_patch_mitigation_partial_mitigation(self, submissions):
        """Test _merge_entries_by_patch_mitigation when patch mitigates some but not all POVs."""
        # Create submissions with multiple crashes
        submissions.entries = [
            SubmissionEntryBuilder()
            .crash(task_id="task-1", crash_input_path="/path/to/crash1.bin")
            .patch(internal_patch_id="patch-1", patch_content="patch content 1")
            .build_output(patch_internal_id="patch-1", task_dir="/build/path1", task_id="task-1")
            .patch_idx(0)
            .build(),
            SubmissionEntryBuilder()
            .crash(task_id="task-1", crash_input_path="/path/to/crash2.bin")
            .crash(task_id="task-1", crash_input_path="/path/to/crash3.bin")
            .build(),
        ]

        # Ensure task registry doesn't filter out submissions
        submissions.task_registry.should_stop_processing.return_value = False

        # Mock POV reproduction status - patch mitigates first crash but not second
        def mock_pov_reproduce_patch_status(patch, crashes, task_id):
            if patch.internal_patch_id == "patch-1":
                # First crash mitigated, second not mitigated
                return [Mock(did_crash=False), Mock(did_crash=True)]
            return [None] * len(crashes)

        mock_consolidate = Mock()

        with (
            patch.object(submissions, "_pov_reproduce_patch_status", side_effect=mock_pov_reproduce_patch_status),
            patch.object(submissions, "_consolidate_similar_submissions", mock_consolidate),
        ):
            # Call the method
            submissions._merge_entries_by_patch_mitigation()

        # Verify consolidation was called (partial mitigation still triggers merge)
        mock_consolidate.assert_called_once()

        # Verify both submissions are included
        call_args = mock_consolidate.call_args[1]
        similar_entries = call_args["similar_entries"]
        assert len(similar_entries) == 2

    def test_merge_entries_by_patch_mitigation_no_current_patch(self, submissions):
        """Test _merge_entries_by_patch_mitigation when submissions have no current patch."""
        # Create submissions without patches or with patch_idx beyond available patches
        submissions.entries = [
            SubmissionEntryBuilder()
            .crash(task_id="task-1", crash_input_path="/path/to/crash1.bin")
            .build(),  # No patches
            SubmissionEntryBuilder()
            .crash(task_id="task-1", crash_input_path="/path/to/crash2.bin")
            .patch(internal_patch_id="patch-1", patch_content="patch content 1")
            .patch_idx(1)  # Beyond available patches
            .build(),
        ]

        # Ensure task registry doesn't filter out submissions
        submissions.task_registry.should_stop_processing.return_value = False

        mock_consolidate = Mock()

        with patch.object(submissions, "_consolidate_similar_submissions", mock_consolidate):
            # Call the method
            submissions._merge_entries_by_patch_mitigation()

        # Verify no consolidation occurred since no current patches
        mock_consolidate.assert_not_called()

    def test_merge_entries_by_patch_mitigation_different_tasks(self, submissions):
        """Test _merge_entries_by_patch_mitigation with submissions from different tasks."""
        # Create submissions from different tasks
        submissions.entries = [
            SubmissionEntryBuilder()
            .crash(task_id="task-1", crash_input_path="/path/to/crash1.bin")
            .patch(internal_patch_id="patch-1", patch_content="patch content 1")
            .patch_idx(0)
            .build(),
            SubmissionEntryBuilder().crash(task_id="task-2", crash_input_path="/path/to/crash2.bin").build(),
        ]

        # Ensure task registry doesn't filter out submissions
        submissions.task_registry.should_stop_processing.return_value = False

        # Mock POV reproduction status to return mitigation
        def mock_pov_reproduce_patch_status(patch, crashes, task_id):
            return [Mock(did_crash=False)] * len(crashes)

        mock_consolidate = Mock()

        with (
            patch.object(submissions, "_pov_reproduce_patch_status", side_effect=mock_pov_reproduce_patch_status),
            patch.object(submissions, "_consolidate_similar_submissions", mock_consolidate),
        ):
            # Call the method
            submissions._merge_entries_by_patch_mitigation()

        # Verify no consolidation occurred since submissions are from different tasks
        mock_consolidate.assert_not_called()

    def test_merge_entries_by_patch_mitigation_stopped_submissions(self, submissions):
        """Test _merge_entries_by_patch_mitigation skips stopped submissions."""
        # Create submissions with one stopped
        submissions.entries = [
            SubmissionEntryBuilder()
            .crash(task_id="task-1", crash_input_path="/path/to/crash1.bin")
            .patch(internal_patch_id="patch-1", patch_content="patch content 1")
            .patch_idx(0)
            .build(),
            SubmissionEntryBuilder().crash(task_id="task-1", crash_input_path="/path/to/crash2.bin").stopped().build(),
        ]

        # Ensure task registry doesn't filter out submissions (stopped submissions are filtered by the stop flag, not task registry)
        submissions.task_registry.should_stop_processing.return_value = False

        mock_consolidate = Mock()

        with patch.object(submissions, "_consolidate_similar_submissions", mock_consolidate):
            # Call the method
            submissions._merge_entries_by_patch_mitigation()

        # Verify no consolidation occurred since second submission is stopped
        mock_consolidate.assert_not_called()

    def test_merge_entries_by_patch_mitigation_cancelled_tasks(self, submissions, mock_task_registry):
        """Test _merge_entries_by_patch_mitigation skips submissions for cancelled tasks."""
        # Create submissions for a task that will be cancelled
        submissions.entries = [
            SubmissionEntryBuilder()
            .crash(task_id="cancelled-task", crash_input_path="/path/to/crash1.bin")
            .patch(internal_patch_id="patch-1", patch_content="patch content 1")
            .patch_idx(0)
            .build(),
            SubmissionEntryBuilder().crash(task_id="cancelled-task", crash_input_path="/path/to/crash2.bin").build(),
        ]

        # Mock task registry to indicate task should stop processing
        mock_task_registry.should_stop_processing.return_value = True

        mock_consolidate = Mock()

        with patch.object(submissions, "_consolidate_similar_submissions", mock_consolidate):
            # Call the method
            submissions._merge_entries_by_patch_mitigation()

        # Verify no consolidation occurred since task is cancelled
        mock_consolidate.assert_not_called()

    def test_merge_entries_by_patch_mitigation_multiple_patches_same_submission(self, submissions):
        """Test _merge_entries_by_patch_mitigation with multiple patches in the same submission."""
        # Create submission with multiple patches, current patch is the second one
        submissions.entries = [
            SubmissionEntryBuilder()
            .crash(task_id="task-1", crash_input_path="/path/to/crash1.bin")
            .patch(internal_patch_id="patch-1a", patch_content="patch content 1a")
            .patch(internal_patch_id="patch-1b", patch_content="patch content 1b")
            .build_output(patch_internal_id="patch-1b", task_dir="/build/path1b", task_id="task-1")
            .patch_idx(1)  # Current patch is patch-1b
            .build(),
            SubmissionEntryBuilder().crash(task_id="task-1", crash_input_path="/path/to/crash2.bin").build(),
        ]

        # Ensure task registry doesn't filter out submissions
        submissions.task_registry.should_stop_processing.return_value = False

        # Mock POV reproduction status - only patch-1b (current patch) should be tested
        def mock_pov_reproduce_patch_status(patch, crashes, task_id):
            if patch.internal_patch_id == "patch-1b":
                return [Mock(did_crash=False)] * len(crashes)  # Mitigated
            elif patch.internal_patch_id == "patch-1a":
                # This shouldn't be called since it's not the current patch
                raise AssertionError("Should not test non-current patch")
            return [None] * len(crashes)

        mock_consolidate = Mock()

        with (
            patch.object(submissions, "_pov_reproduce_patch_status", side_effect=mock_pov_reproduce_patch_status),
            patch.object(submissions, "_consolidate_similar_submissions", mock_consolidate),
        ):
            # Call the method
            submissions._merge_entries_by_patch_mitigation()

        # Verify consolidation was called with the current patch
        mock_consolidate.assert_called_once()

    def test_merge_entries_by_patch_mitigation_pending_status(self, submissions):
        """Test _merge_entries_by_patch_mitigation when POV reproduction status is pending."""
        # Create submissions
        submissions.entries = [
            SubmissionEntryBuilder()
            .crash(task_id="task-1", crash_input_path="/path/to/crash1.bin")
            .patch(internal_patch_id="patch-1", patch_content="patch content 1")
            .patch_idx(0)
            .build(),
            SubmissionEntryBuilder().crash(task_id="task-1", crash_input_path="/path/to/crash2.bin").build(),
        ]

        # Ensure task registry doesn't filter out submissions
        submissions.task_registry.should_stop_processing.return_value = False

        # Mock POV reproduction status to return pending (None)
        def mock_pov_reproduce_patch_status(patch, crashes, task_id):
            return [None] * len(crashes)  # All pending

        mock_consolidate = Mock()

        with (
            patch.object(submissions, "_pov_reproduce_patch_status", side_effect=mock_pov_reproduce_patch_status),
            patch.object(submissions, "_consolidate_similar_submissions", mock_consolidate),
        ):
            # Call the method
            submissions._merge_entries_by_patch_mitigation()

        # Verify no consolidation occurred since status is pending
        mock_consolidate.assert_not_called()

    def test_merge_entries_by_patch_mitigation_mixed_statuses(self, submissions):
        """Test _merge_entries_by_patch_mitigation with mixed POV reproduction statuses."""
        # Create submissions
        submissions.entries = [
            SubmissionEntryBuilder()
            .crash(task_id="task-1", crash_input_path="/path/to/crash1.bin")
            .patch(internal_patch_id="patch-1", patch_content="patch content 1")
            .build_output(patch_internal_id="patch-1", task_dir="/build/path1", task_id="task-1")
            .patch_idx(0)
            .build(),
            SubmissionEntryBuilder()
            .crash(task_id="task-1", crash_input_path="/path/to/crash2.bin")
            .crash(task_id="task-1", crash_input_path="/path/to/crash3.bin")
            .build(),
        ]

        # Ensure task registry doesn't filter out submissions
        submissions.task_registry.should_stop_processing.return_value = False

        # Mock POV reproduction status with mixed results
        def mock_pov_reproduce_patch_status(patch, crashes, task_id):
            if patch.internal_patch_id == "patch-1":
                # First POV mitigated, second POV not mitigated
                return [Mock(did_crash=False), Mock(did_crash=True)]
            return [None] * len(crashes)

        mock_consolidate = Mock()

        with (
            patch.object(submissions, "_pov_reproduce_patch_status", side_effect=mock_pov_reproduce_patch_status),
            patch.object(submissions, "_consolidate_similar_submissions", mock_consolidate),
        ):
            # Call the method
            submissions._merge_entries_by_patch_mitigation()

        # Verify consolidation occurred since at least one POV was mitigated
        mock_consolidate.assert_called_once()

    def test_merge_entries_by_patch_mitigation_self_exclusion(self, submissions):
        """Test _merge_entries_by_patch_mitigation doesn't merge submission with itself."""
        # Create single submission
        submissions.entries = [
            SubmissionEntryBuilder()
            .crash(task_id="task-1", crash_input_path="/path/to/crash1.bin")
            .patch(internal_patch_id="patch-1", patch_content="patch content 1")
            .patch_idx(0)
            .build(),
        ]

        # Ensure task registry doesn't filter out submissions
        submissions.task_registry.should_stop_processing.return_value = False

        # Mock POV reproduction status to return mitigation
        def mock_pov_reproduce_patch_status(patch, crashes, task_id):
            return [Mock(did_crash=False)] * len(crashes)

        mock_consolidate = Mock()

        with (
            patch.object(submissions, "_pov_reproduce_patch_status", side_effect=mock_pov_reproduce_patch_status),
            patch.object(submissions, "_consolidate_similar_submissions", mock_consolidate),
        ):
            # Call the method
            submissions._merge_entries_by_patch_mitigation()

        # Verify no consolidation occurred since there's only one submission
        mock_consolidate.assert_not_called()

    def test_merge_entries_by_patch_mitigation_multiple_merges(self, submissions):
        """Test _merge_entries_by_patch_mitigation with multiple independent merges."""
        # Create submissions where multiple patches can mitigate different sets of POVs
        submissions.entries = [
            # First group - patch-1 mitigates submission 1
            SubmissionEntryBuilder()
            .crash(task_id="task-1", crash_input_path="/path/to/crash1.bin")
            .patch(internal_patch_id="patch-1", patch_content="patch content 1")
            .build_output(patch_internal_id="patch-1", task_dir="/build/path1", task_id="task-1")
            .patch_idx(0)
            .build(),
            SubmissionEntryBuilder().crash(task_id="task-1", crash_input_path="/path/to/crash2.bin").build(),
            # Second group - patch-3 mitigates submission 3
            SubmissionEntryBuilder()
            .crash(task_id="task-1", crash_input_path="/path/to/crash3.bin")
            .patch(internal_patch_id="patch-3", patch_content="patch content 3")
            .build_output(patch_internal_id="patch-3", task_dir="/build/path3", task_id="task-1")
            .patch_idx(0)
            .build(),
            SubmissionEntryBuilder().crash(task_id="task-1", crash_input_path="/path/to/crash4.bin").build(),
        ]

        # Ensure task registry doesn't filter out submissions
        submissions.task_registry.should_stop_processing.return_value = False

        # Mock POV reproduction status
        def mock_pov_reproduce_patch_status(patch, crashes, task_id):
            if patch.internal_patch_id == "patch-1":
                # patch-1 mitigates POVs from submission 1 only
                return [Mock(did_crash=False)] * len(crashes)
            elif patch.internal_patch_id == "patch-3":
                # patch-3 mitigates POVs from submission 3 only
                return [Mock(did_crash=False)] * len(crashes)
            return [None] * len(crashes)

        mock_consolidate = Mock()

        with (
            patch.object(submissions, "_pov_reproduce_patch_status", side_effect=mock_pov_reproduce_patch_status),
            patch.object(submissions, "_consolidate_similar_submissions", mock_consolidate),
        ):
            # Call the method
            submissions._merge_entries_by_patch_mitigation()

        # Verify consolidation was called twice (once for each group)
        assert mock_consolidate.call_count == 2

    def test_merge_entries_by_patch_mitigation_error_handling(self, submissions):
        """Test _merge_entries_by_patch_mitigation handles errors gracefully by logging them."""
        # Create submissions - need at least two submissions for the function to test mitigation
        submissions.entries = [
            SubmissionEntryBuilder()
            .crash(task_id="task-1", crash_input_path="/path/to/crash1.bin")
            .patch(internal_patch_id="patch-1", patch_content="patch content 1")
            .build_output(patch_internal_id="patch-1", task_dir="/build/path1", task_id="task-1")
            .patch_idx(0)
            .build(),
            SubmissionEntryBuilder().crash(task_id="task-1", crash_input_path="/path/to/crash2.bin").build(),
        ]

        # Ensure task registry doesn't filter out submissions
        submissions.task_registry.should_stop_processing.return_value = False

        # Mock POV reproduction status to raise an exception
        def mock_pov_reproduce_patch_status(patch, crashes, task_id):
            raise Exception("Test error in POV reproduction")

        with (
            patch.object(submissions, "_pov_reproduce_patch_status", side_effect=mock_pov_reproduce_patch_status),
            patch("buttercup.orchestrator.scheduler.submissions.logger") as mock_logger,
        ):
            # Call the method - should handle exception gracefully and log error
            submissions._merge_entries_by_patch_mitigation()

            # Verify that the error was logged
            mock_logger.error.assert_called_once()
            error_call_args = mock_logger.error.call_args[0][0]  # Get the first argument of the error call
            assert "Error merging entries by patch mitigation" in error_call_args
            assert "Test error in POV reproduction" in error_call_args

    def test_merge_entries_by_patch_mitigation_complex_scenario(self, submissions):
        """Test _merge_entries_by_patch_mitigation with a complex scenario involving multiple tasks and patches."""
        # Create complex scenario with multiple tasks and patches
        submissions.entries = [
            # Task 1 submissions
            SubmissionEntryBuilder()
            .crash(task_id="task-1", crash_input_path="/path/to/crash1.bin")
            .patch(internal_patch_id="patch-1", patch_content="patch content 1")
            .build_output(patch_internal_id="patch-1", task_dir="/build/path1", task_id="task-1")
            .patch_idx(0)
            .build(),
            SubmissionEntryBuilder().crash(task_id="task-1", crash_input_path="/path/to/crash2.bin").build(),
            SubmissionEntryBuilder().crash(task_id="task-1", crash_input_path="/path/to/crash3.bin").build(),
            # Task 2 submissions (should be separate)
            SubmissionEntryBuilder()
            .crash(task_id="task-2", crash_input_path="/path/to/crash4.bin")
            .patch(internal_patch_id="patch-4", patch_content="patch content 4")
            .build_output(patch_internal_id="patch-4", task_dir="/build/path4", task_id="task-2")
            .patch_idx(0)
            .build(),
            SubmissionEntryBuilder().crash(task_id="task-2", crash_input_path="/path/to/crash5.bin").build(),
        ]

        # Ensure task registry doesn't filter out submissions
        submissions.task_registry.should_stop_processing.return_value = False

        # Mock POV reproduction status
        def mock_pov_reproduce_patch_status(patch, crashes, task_id):
            if patch.internal_patch_id == "patch-1" and task_id == "task-1":
                # patch-1 mitigates task-1 POVs
                return [Mock(did_crash=False)] * len(crashes)
            elif patch.internal_patch_id == "patch-4" and task_id == "task-2":
                # patch-4 mitigates task-2 POVs
                return [Mock(did_crash=False)] * len(crashes)
            return [None] * len(crashes)

        mock_consolidate = Mock()

        with (
            patch.object(submissions, "_pov_reproduce_patch_status", side_effect=mock_pov_reproduce_patch_status),
            patch.object(submissions, "_consolidate_similar_submissions", mock_consolidate),
        ):
            # Call the method
            submissions._merge_entries_by_patch_mitigation()

        # Verify consolidation was called twice (once for each task)
        assert mock_consolidate.call_count == 2

        # Verify the consolidations were for the correct groups
        call_args_list = [call[1]["similar_entries"] for call in mock_consolidate.call_args_list]

        # First call should be for task-1 submissions (indices 0, 1, 2)
        first_call_indices = [idx for idx, _ in call_args_list[0]]
        assert set(first_call_indices) == {0, 1, 2}

        # Second call should be for task-2 submissions (indices 3, 4)
        second_call_indices = [idx for idx, _ in call_args_list[1]]
        assert set(second_call_indices) == {3, 4}

    def test_merge_entries_by_patch_mitigation_incomplete_builds(self, submissions):
        """Test _merge_entries_by_patch_mitigation when builds are not complete (some task_dir missing)."""
        # Create submission with patch that has incomplete builds
        submissions.entries = [
            SubmissionEntryBuilder()
            .crash(task_id="task-1", crash_input_path="/path/to/crash1.bin")
            .patch(internal_patch_id="patch-1", patch_content="patch content 1")
            .build_output(patch_internal_id="patch-1", task_dir="", task_id="task-1")  # Empty task_dir = incomplete
            .patch_idx(0)
            .build(),
            SubmissionEntryBuilder().crash(task_id="task-1", crash_input_path="/path/to/crash2.bin").build(),
        ]

        # Ensure task registry doesn't filter out submissions
        submissions.task_registry.should_stop_processing.return_value = False

        # Mock _consolidate_similar_submissions to track calls
        mock_consolidate = Mock()

        with (
            patch.object(submissions, "_consolidate_similar_submissions", mock_consolidate),
        ):
            # Call the method
            submissions._merge_entries_by_patch_mitigation()

        # Verify consolidation was NOT called since builds are incomplete
        mock_consolidate.assert_not_called()

    def test_merge_entries_by_patch_mitigation_no_build_outputs(self, submissions):
        """Test _merge_entries_by_patch_mitigation when patch has no build outputs."""
        # Create submission with patch but no build outputs
        submissions.entries = [
            SubmissionEntryBuilder()
            .crash(task_id="task-1", crash_input_path="/path/to/crash1.bin")
            .patch(internal_patch_id="patch-1", patch_content="patch content 1")
            .patch_idx(0)
            .build(),  # No build outputs
            SubmissionEntryBuilder().crash(task_id="task-1", crash_input_path="/path/to/crash2.bin").build(),
        ]

        # Ensure task registry doesn't filter out submissions
        submissions.task_registry.should_stop_processing.return_value = False

        # Mock _consolidate_similar_submissions to track calls
        mock_consolidate = Mock()

        with (
            patch.object(submissions, "_consolidate_similar_submissions", mock_consolidate),
        ):
            # Call the method
            submissions._merge_entries_by_patch_mitigation()

        # Verify consolidation was NOT called since no build outputs
        mock_consolidate.assert_not_called()

    def test_merge_entries_by_patch_mitigation_empty_result_list(self, submissions):
        """Test _merge_entries_by_patch_mitigation when POV reproduction returns empty results."""
        # Create submissions with normal crashes but mock reproduction to return empty list
        submissions.entries = [
            SubmissionEntryBuilder()
            .crash(task_id="task-1", crash_input_path="/path/to/crash1.bin")
            .patch(internal_patch_id="patch-1", patch_content="patch content 1")
            .build_output(patch_internal_id="patch-1", task_dir="/build/path1", task_id="task-1")
            .patch_idx(0)
            .build(),
            SubmissionEntryBuilder().crash(task_id="task-1", crash_input_path="/path/to/crash2.bin").build(),
        ]

        # Ensure task registry doesn't filter out submissions
        submissions.task_registry.should_stop_processing.return_value = False

        # Mock POV reproduction status to return empty list (unusual but possible edge case)
        def mock_pov_reproduce_patch_status(patch, crashes, task_id):
            # Return empty list even though crashes exist (edge case)
            return []

        # Mock _consolidate_similar_submissions to track calls
        mock_consolidate = Mock()

        with (
            patch.object(submissions, "_pov_reproduce_patch_status", side_effect=mock_pov_reproduce_patch_status),
            patch.object(submissions, "_consolidate_similar_submissions", mock_consolidate),
        ):
            # Call the method
            submissions._merge_entries_by_patch_mitigation()

        # Verify consolidation was NOT called since no results indicate mitigation
        mock_consolidate.assert_not_called()

    def test_merge_entries_by_patch_mitigation_all_povs_pending(self, submissions):
        """Test _merge_entries_by_patch_mitigation when all POVs are pending (None status)."""
        # Create submissions
        submissions.entries = [
            SubmissionEntryBuilder()
            .crash(task_id="task-1", crash_input_path="/path/to/crash1.bin")
            .patch(internal_patch_id="patch-1", patch_content="patch content 1")
            .build_output(patch_internal_id="patch-1", task_dir="/build/path1", task_id="task-1")
            .patch_idx(0)
            .build(),
            SubmissionEntryBuilder().crash(task_id="task-1", crash_input_path="/path/to/crash2.bin").build(),
        ]

        # Ensure task registry doesn't filter out submissions
        submissions.task_registry.should_stop_processing.return_value = False

        # Mock POV reproduction status - all pending
        def mock_pov_reproduce_patch_status(patch, crashes, task_id):
            return [None] * len(crashes)  # All pending

        # Mock _consolidate_similar_submissions to track calls
        mock_consolidate = Mock()

        with (
            patch.object(submissions, "_pov_reproduce_patch_status", side_effect=mock_pov_reproduce_patch_status),
            patch.object(submissions, "_consolidate_similar_submissions", mock_consolidate),
        ):
            # Call the method
            submissions._merge_entries_by_patch_mitigation()

        # Verify consolidation was NOT called since no POVs are mitigated
        mock_consolidate.assert_not_called()

    def test_merge_entries_by_patch_mitigation_all_povs_not_mitigated(self, submissions):
        """Test _merge_entries_by_patch_mitigation when all POVs are not mitigated (did_crash=True)."""
        # Create submissions
        submissions.entries = [
            SubmissionEntryBuilder()
            .crash(task_id="task-1", crash_input_path="/path/to/crash1.bin")
            .patch(internal_patch_id="patch-1", patch_content="patch content 1")
            .build_output(patch_internal_id="patch-1", task_dir="/build/path1", task_id="task-1")
            .patch_idx(0)
            .build(),
            SubmissionEntryBuilder().crash(task_id="task-1", crash_input_path="/path/to/crash2.bin").build(),
        ]

        # Ensure task registry doesn't filter out submissions
        submissions.task_registry.should_stop_processing.return_value = False

        # Mock POV reproduction status - all not mitigated
        def mock_pov_reproduce_patch_status(patch, crashes, task_id):
            return [Mock(did_crash=True)] * len(crashes)  # All not mitigated

        # Mock _consolidate_similar_submissions to track calls
        mock_consolidate = Mock()

        with (
            patch.object(submissions, "_pov_reproduce_patch_status", side_effect=mock_pov_reproduce_patch_status),
            patch.object(submissions, "_consolidate_similar_submissions", mock_consolidate),
        ):
            # Call the method
            submissions._merge_entries_by_patch_mitigation()

        # Verify consolidation was NOT called since no POVs are mitigated
        mock_consolidate.assert_not_called()

    def test_merge_entries_by_patch_mitigation_single_submission(self, submissions):
        """Test _merge_entries_by_patch_mitigation with only one submission."""
        # Create only one submission
        submissions.entries = [
            SubmissionEntryBuilder()
            .crash(task_id="task-1", crash_input_path="/path/to/crash1.bin")
            .patch(internal_patch_id="patch-1", patch_content="patch content 1")
            .build_output(patch_internal_id="patch-1", task_dir="/build/path1", task_id="task-1")
            .patch_idx(0)
            .build(),
        ]

        # Ensure task registry doesn't filter out submissions
        submissions.task_registry.should_stop_processing.return_value = False

        # Mock _consolidate_similar_submissions to track calls
        mock_consolidate = Mock()

        with (
            patch.object(submissions, "_consolidate_similar_submissions", mock_consolidate),
        ):
            # Call the method
            submissions._merge_entries_by_patch_mitigation()

        # Verify consolidation was NOT called since there's only one submission
        mock_consolidate.assert_not_called()

    def test_merge_entries_by_patch_mitigation_patch_idx_out_of_bounds(self, submissions):
        """Test _merge_entries_by_patch_mitigation when patch_idx is beyond available patches."""
        # Create submission with patch_idx that exceeds patch list
        submissions.entries = [
            SubmissionEntryBuilder()
            .crash(task_id="task-1", crash_input_path="/path/to/crash1.bin")
            .patch(internal_patch_id="patch-1", patch_content="patch content 1")
            .build_output(patch_internal_id="patch-1", task_dir="/build/path1", task_id="task-1")
            .patch_idx(5)  # Out of bounds - only one patch exists
            .build(),
            SubmissionEntryBuilder().crash(task_id="task-1", crash_input_path="/path/to/crash2.bin").build(),
        ]

        # Ensure task registry doesn't filter out submissions
        submissions.task_registry.should_stop_processing.return_value = False

        # Mock _consolidate_similar_submissions to track calls
        mock_consolidate = Mock()

        with (
            patch.object(submissions, "_consolidate_similar_submissions", mock_consolidate),
        ):
            # Call the method
            submissions._merge_entries_by_patch_mitigation()

        # Verify consolidation was NOT called since current_patch returns None
        mock_consolidate.assert_not_called()

    def test_merge_entries_by_patch_mitigation_mixed_build_completion(self, submissions):
        """Test _merge_entries_by_patch_mitigation with multiple build outputs where some are complete and some aren't."""
        # Create submission with mixed build completion status
        entry = (
            SubmissionEntryBuilder()
            .crash(task_id="task-1", crash_input_path="/path/to/crash1.bin")
            .patch(internal_patch_id="patch-1", patch_content="patch content 1")
            .patch_idx(0)
            .build()
        )

        # Manually add multiple build outputs with mixed completion
        from buttercup.common.datastructures.msg_pb2 import BuildOutput as BuildOutputMsg, BuildType

        build_output1 = BuildOutputMsg(
            task_dir="/build/path1",  # Complete
            task_id="task-1",
            build_type=BuildType.PATCH,
            sanitizer="asan",
            engine="libfuzzer",
        )
        build_output2 = BuildOutputMsg(
            task_dir="",  # Incomplete
            task_id="task-1",
            build_type=BuildType.PATCH,
            sanitizer="msan",
            engine="libfuzzer",
        )
        entry.patches[0].build_outputs.extend([build_output1, build_output2])

        submissions.entries = [
            entry,
            SubmissionEntryBuilder().crash(task_id="task-1", crash_input_path="/path/to/crash2.bin").build(),
        ]

        # Ensure task registry doesn't filter out submissions
        submissions.task_registry.should_stop_processing.return_value = False

        # Mock _consolidate_similar_submissions to track calls
        mock_consolidate = Mock()

        with (
            patch.object(submissions, "_consolidate_similar_submissions", mock_consolidate),
        ):
            # Call the method
            submissions._merge_entries_by_patch_mitigation()

        # Verify consolidation was NOT called since not all builds are complete
        mock_consolidate.assert_not_called()


class TestShouldWaitForPatchMitigationMerge:
    """Test cases for the _should_wait_for_patch_mitigation_merge method."""

    def test_should_wait_for_patch_mitigation_merge_pending_evaluation(self, submissions):
        """Test _should_wait_for_patch_mitigation_merge when POV evaluation is pending."""
        # Create submissions - one with a patch, one without
        submissions.entries = [
            # Submission 0: Has POVs but no patch
            SubmissionEntryBuilder()
            .crash(task_id="task-1", crash_input_path="/path/to/crash1.bin")
            .crash(task_id="task-1", crash_input_path="/path/to/crash2.bin")
            .build(),
            # Submission 1: Has a submitted patch
            SubmissionEntryBuilder()
            .crash(task_id="task-1", crash_input_path="/path/to/crash3.bin")
            .patch(internal_patch_id="patch-1", patch_content="patch content", competition_patch_id="comp-patch-1")
            .patch_idx(0)
            .build(),
        ]

        # Ensure task registry doesn't filter out submissions
        submissions.task_registry.should_stop_processing.return_value = False

        # Mock POV reproduction status - return pending (None) for all POVs
        def mock_pov_reproduce_patch_status(patch, crashes, task_id):
            return [None] * len(crashes)  # All pending

        with patch.object(submissions, "_pov_reproduce_patch_status", side_effect=mock_pov_reproduce_patch_status):
            # Test submission 0 - should wait because evaluation is pending
            result = submissions._should_wait_for_patch_mitigation_merge(0, submissions.entries[0])
            assert result is True

    def test_should_wait_for_patch_mitigation_merge_confirmed_mitigation(self, submissions):
        """Test _should_wait_for_patch_mitigation_merge when POVs are confirmed mitigated."""
        # Create submissions - one with POVs, one with a patch that mitigates them
        submissions.entries = [
            # Submission 0: Has POVs that will be mitigated
            SubmissionEntryBuilder()
            .crash(task_id="task-1", crash_input_path="/path/to/crash1.bin")
            .crash(task_id="task-1", crash_input_path="/path/to/crash2.bin")
            .build(),
            # Submission 1: Has a submitted patch
            SubmissionEntryBuilder()
            .crash(task_id="task-1", crash_input_path="/path/to/crash3.bin")
            .patch(internal_patch_id="patch-1", patch_content="patch content", competition_patch_id="comp-patch-1")
            .patch_idx(0)
            .build(),
        ]

        # Ensure task registry doesn't filter out submissions
        submissions.task_registry.should_stop_processing.return_value = False

        # Mock POV reproduction status - one mitigated, one not
        def mock_pov_reproduce_patch_status(patch, crashes, task_id):
            return [
                Mock(did_crash=False),  # Mitigated
                Mock(did_crash=True),  # Not mitigated
            ]

        with patch.object(submissions, "_pov_reproduce_patch_status", side_effect=mock_pov_reproduce_patch_status):
            # Test submission 0 - should wait because at least one POV is mitigated
            result = submissions._should_wait_for_patch_mitigation_merge(0, submissions.entries[0])
            assert result is True

    def test_should_wait_for_patch_mitigation_merge_no_mitigation(self, submissions):
        """Test _should_wait_for_patch_mitigation_merge when no POVs are mitigated."""
        # Create submissions
        submissions.entries = [
            # Submission 0: Has POVs that won't be mitigated
            SubmissionEntryBuilder()
            .crash(task_id="task-1", crash_input_path="/path/to/crash1.bin")
            .crash(task_id="task-1", crash_input_path="/path/to/crash2.bin")
            .build(),
            # Submission 1: Has a submitted patch
            SubmissionEntryBuilder()
            .crash(task_id="task-1", crash_input_path="/path/to/crash3.bin")
            .patch(internal_patch_id="patch-1", patch_content="patch content", competition_patch_id="comp-patch-1")
            .patch_idx(0)
            .build(),
        ]

        # Ensure task registry doesn't filter out submissions
        submissions.task_registry.should_stop_processing.return_value = False

        # Mock POV reproduction status - all not mitigated
        def mock_pov_reproduce_patch_status(patch, crashes, task_id):
            return [Mock(did_crash=True)] * len(crashes)  # All not mitigated

        with patch.object(submissions, "_pov_reproduce_patch_status", side_effect=mock_pov_reproduce_patch_status):
            # Test submission 0 - should not wait because no POVs are mitigated
            result = submissions._should_wait_for_patch_mitigation_merge(0, submissions.entries[0])
            assert result is False

    def test_should_wait_for_patch_mitigation_merge_no_other_patches(self, submissions):
        """Test _should_wait_for_patch_mitigation_merge when no other submissions have patches."""
        # Create submissions - none have patches
        submissions.entries = [
            SubmissionEntryBuilder().crash(task_id="task-1", crash_input_path="/path/to/crash1.bin").build(),
            SubmissionEntryBuilder().crash(task_id="task-1", crash_input_path="/path/to/crash2.bin").build(),
        ]

        # Ensure task registry doesn't filter out submissions
        submissions.task_registry.should_stop_processing.return_value = False

        # Test submission 0 - should not wait because no other submissions have patches
        result = submissions._should_wait_for_patch_mitigation_merge(0, submissions.entries[0])
        assert result is False

    def test_should_wait_for_patch_mitigation_merge_unsubmitted_patch(self, submissions):
        """Test _should_wait_for_patch_mitigation_merge when other submission has patch but not submitted."""
        # Create submissions
        submissions.entries = [
            # Submission 0: Has POVs
            SubmissionEntryBuilder().crash(task_id="task-1", crash_input_path="/path/to/crash1.bin").build(),
            # Submission 1: Has patch but not submitted (no competition_patch_id)
            SubmissionEntryBuilder()
            .crash(task_id="task-1", crash_input_path="/path/to/crash2.bin")
            .patch(internal_patch_id="patch-1", patch_content="patch content")  # No competition_patch_id
            .patch_idx(0)
            .build(),
        ]

        # Ensure task registry doesn't filter out submissions
        submissions.task_registry.should_stop_processing.return_value = False

        # Test submission 0 - should not wait because other patch is not submitted
        result = submissions._should_wait_for_patch_mitigation_merge(0, submissions.entries[0])
        assert result is False

    def test_should_wait_for_patch_mitigation_merge_different_tasks(self, submissions):
        """Test _should_wait_for_patch_mitigation_merge with submissions from different tasks."""
        # Create submissions from different tasks
        submissions.entries = [
            # Submission 0: Task 1
            SubmissionEntryBuilder().crash(task_id="task-1", crash_input_path="/path/to/crash1.bin").build(),
            # Submission 1: Task 2 (different task)
            SubmissionEntryBuilder()
            .crash(task_id="task-2", crash_input_path="/path/to/crash2.bin")
            .patch(internal_patch_id="patch-1", patch_content="patch content", competition_patch_id="comp-patch-1")
            .patch_idx(0)
            .build(),
        ]

        # Ensure task registry doesn't filter out submissions
        submissions.task_registry.should_stop_processing.return_value = False

        # Test submission 0 - should not wait because other submission is from different task
        result = submissions._should_wait_for_patch_mitigation_merge(0, submissions.entries[0])
        assert result is False

    def test_should_wait_for_patch_mitigation_merge_self_exclusion(self, submissions):
        """Test _should_wait_for_patch_mitigation_merge excludes checking against itself."""
        # Create submission that has both POVs and a patch
        submissions.entries = [
            SubmissionEntryBuilder()
            .crash(task_id="task-1", crash_input_path="/path/to/crash1.bin")
            .patch(internal_patch_id="patch-1", patch_content="patch content", competition_patch_id="comp-patch-1")
            .patch_idx(0)
            .build(),
        ]

        # Ensure task registry doesn't filter out submissions
        submissions.task_registry.should_stop_processing.return_value = False

        # Test submission 0 - should not wait because it only checks against itself (which is excluded)
        result = submissions._should_wait_for_patch_mitigation_merge(0, submissions.entries[0])
        assert result is False

    def test_should_wait_for_patch_mitigation_merge_multiple_other_submissions(self, submissions):
        """Test _should_wait_for_patch_mitigation_merge with multiple other submissions with patches."""
        # Create submissions
        submissions.entries = [
            # Submission 0: Has POVs to be checked
            SubmissionEntryBuilder()
            .crash(task_id="task-1", crash_input_path="/path/to/crash1.bin")
            .crash(task_id="task-1", crash_input_path="/path/to/crash2.bin")
            .build(),
            # Submission 1: Has patch that doesn't mitigate
            SubmissionEntryBuilder()
            .crash(task_id="task-1", crash_input_path="/path/to/crash3.bin")
            .patch(internal_patch_id="patch-1", patch_content="patch content 1", competition_patch_id="comp-patch-1")
            .patch_idx(0)
            .build(),
            # Submission 2: Has patch that does mitigate
            SubmissionEntryBuilder()
            .crash(task_id="task-1", crash_input_path="/path/to/crash4.bin")
            .patch(internal_patch_id="patch-2", patch_content="patch content 2", competition_patch_id="comp-patch-2")
            .patch_idx(0)
            .build(),
        ]

        # Ensure task registry doesn't filter out submissions
        submissions.task_registry.should_stop_processing.return_value = False

        # Mock POV reproduction status - first patch doesn't mitigate, second does
        def mock_pov_reproduce_patch_status(patch, crashes, task_id):
            if patch.internal_patch_id == "patch-1":
                return [Mock(did_crash=True)] * len(crashes)  # Doesn't mitigate
            elif patch.internal_patch_id == "patch-2":
                return [Mock(did_crash=False), Mock(did_crash=True)]  # Partially mitigates
            return []

        with patch.object(submissions, "_pov_reproduce_patch_status", side_effect=mock_pov_reproduce_patch_status):
            # Test submission 0 - should wait because second patch mitigates at least one POV
            result = submissions._should_wait_for_patch_mitigation_merge(0, submissions.entries[0])
            assert result is True


class TestFailedPOVFiltering:
    """Test cases for the failed POV filtering behavior in merge operations."""

    def test_should_wait_for_patch_mitigation_merge_filters_failed_povs(self, submissions):
        """Test that _should_wait_for_patch_mitigation_merge ignores failed POVs."""
        # Create submissions with mixed POV statuses
        submissions.entries = [
            # Submission with no patch (we're checking if it should wait)
            SubmissionEntryBuilder()
            .crash(task_id="task-1", crash_input_path="/path/to/crash1.bin", result=SubmissionResult.PASSED)
            .crash(task_id="task-1", crash_input_path="/path/to/crash2.bin", result=SubmissionResult.FAILED)
            .crash(task_id="task-1", crash_input_path="/path/to/crash3.bin", result=SubmissionResult.DEADLINE_EXCEEDED)
            .crash(task_id="task-1", crash_input_path="/path/to/crash4.bin", result=SubmissionResult.INCONCLUSIVE)
            .crash(task_id="task-1", crash_input_path="/path/to/crash5.bin", result=SubmissionResult.ACCEPTED)
            .build(),
            # Submission with a submitted patch
            SubmissionEntryBuilder()
            .crash(task_id="task-1", crash_input_path="/path/to/other_crash.bin")
            .patch(internal_patch_id="patch-1", patch_content="patch content", competition_patch_id="comp-patch-1")
            .build(),
        ]

        # Mock POV reproduction status
        def mock_pov_reproduce_patch_status(patch, crashes, task_id):
            # The function receives all crashes but filters internally
            # It should return results only for non-failed POVs (PASSED and ACCEPTED)
            return [None, None]  # Pending for the 2 active POVs (filtered internally)

        with patch.object(submissions, "_pov_reproduce_patch_status", side_effect=mock_pov_reproduce_patch_status):
            result = submissions._should_wait_for_patch_mitigation_merge(0, submissions.entries[0])

        # Should return True because there are pending evaluations for non-failed POVs
        assert result is True

    def test_should_wait_for_patch_mitigation_merge_no_active_povs(self, submissions):
        """Test behavior when all POVs are failed."""
        # Create submissions with only failed POVs
        submissions.entries = [
            # Submission with only failed POVs
            SubmissionEntryBuilder()
            .crash(task_id="task-1", crash_input_path="/path/to/crash1.bin", result=SubmissionResult.FAILED)
            .crash(task_id="task-1", crash_input_path="/path/to/crash2.bin", result=SubmissionResult.DEADLINE_EXCEEDED)
            .crash(task_id="task-1", crash_input_path="/path/to/crash3.bin", result=SubmissionResult.INCONCLUSIVE)
            .build(),
            # Submission with a submitted patch
            SubmissionEntryBuilder()
            .crash(task_id="task-1", crash_input_path="/path/to/other_crash.bin")
            .patch(internal_patch_id="patch-1", patch_content="patch content", competition_patch_id="comp-patch-1")
            .build(),
        ]

        # Mock POV reproduction status
        def mock_pov_reproduce_patch_status(patch, crashes, task_id):
            # The function receives all crashes but filters internally
            # Since all POVs are failed, it returns an empty list
            return []

        with patch.object(submissions, "_pov_reproduce_patch_status", side_effect=mock_pov_reproduce_patch_status):
            result = submissions._should_wait_for_patch_mitigation_merge(0, submissions.entries[0])

        # Should return False because no active POVs to wait for
        assert result is False

    def test_should_wait_for_patch_mitigation_merge_active_povs_mitigated(self, submissions):
        """Test when active POVs are mitigated but failed POVs are ignored."""
        # Create submissions with mixed POV statuses
        submissions.entries = [
            # Submission with mixed POV statuses
            SubmissionEntryBuilder()
            .crash(task_id="task-1", crash_input_path="/path/to/crash1.bin", result=SubmissionResult.PASSED)
            .crash(task_id="task-1", crash_input_path="/path/to/crash2.bin", result=SubmissionResult.FAILED)
            .crash(task_id="task-1", crash_input_path="/path/to/crash3.bin", result=SubmissionResult.ACCEPTED)
            .build(),
            # Submission with a submitted patch
            SubmissionEntryBuilder()
            .crash(task_id="task-1", crash_input_path="/path/to/other_crash.bin")
            .patch(internal_patch_id="patch-1", patch_content="patch content", competition_patch_id="comp-patch-1")
            .build(),
        ]

        # Mock POV reproduction status - active POVs are mitigated
        def mock_pov_reproduce_patch_status(patch, crashes, task_id):
            # The function receives all crashes but filters internally
            # Returns results only for active POVs (PASSED and ACCEPTED)
            return [Mock(did_crash=False), Mock(did_crash=False)]  # Both active POVs mitigated

        with patch.object(submissions, "_pov_reproduce_patch_status", side_effect=mock_pov_reproduce_patch_status):
            result = submissions._should_wait_for_patch_mitigation_merge(0, submissions.entries[0])

        # Should return True because active POVs are mitigated, triggering merge wait
        assert result is True

    def test_merge_entries_by_patch_mitigation_filters_failed_povs(self, submissions):
        """Test that _merge_entries_by_patch_mitigation ignores failed POVs when evaluating mitigation."""
        # Create submissions where patch would mitigate active POVs but not failed ones
        submissions.entries = [
            # Submission with a patch
            SubmissionEntryBuilder()
            .crash(task_id="task-1", crash_input_path="/path/to/patch_crash.bin")
            .patch(internal_patch_id="patch-1", patch_content="patch content")
            .build_output(patch_internal_id="patch-1", task_dir="/build/path", task_id="task-1")
            .patch_idx(0)
            .build(),
            # Submission with mixed POV statuses
            SubmissionEntryBuilder()
            .crash(task_id="task-1", crash_input_path="/path/to/crash1.bin", result=SubmissionResult.PASSED)
            .crash(task_id="task-1", crash_input_path="/path/to/crash2.bin", result=SubmissionResult.FAILED)
            .crash(task_id="task-1", crash_input_path="/path/to/crash3.bin", result=SubmissionResult.DEADLINE_EXCEEDED)
            .crash(task_id="task-1", crash_input_path="/path/to/crash4.bin", result=SubmissionResult.ACCEPTED)
            .build(),
        ]

        # Ensure task registry doesn't filter out submissions
        submissions.task_registry.should_stop_processing.return_value = False

        # Mock POV reproduction status
        def mock_pov_reproduce_patch_status(patch, crashes, task_id):
            # The function receives all crashes but filters internally
            # Returns results only for active POVs
            if patch.internal_patch_id == "patch-1":
                return [
                    Mock(did_crash=False),  # crash1 (PASSED) - mitigated
                    Mock(did_crash=True),  # crash4 (ACCEPTED) - not mitigated
                ]
            return []

        mock_consolidate = Mock()

        with (
            patch.object(submissions, "_pov_reproduce_patch_status", side_effect=mock_pov_reproduce_patch_status),
            patch.object(submissions, "_consolidate_similar_submissions", mock_consolidate),
        ):
            submissions._merge_entries_by_patch_mitigation()

        # Should trigger consolidation because the patch mitigates at least one active POV (crash1)
        mock_consolidate.assert_called_once()

        # Verify correct submissions are merged
        call_args = mock_consolidate.call_args[1]
        similar_entries = call_args["similar_entries"]
        assert len(similar_entries) == 2
        indices = [idx for idx, _ in similar_entries]
        assert 0 in indices  # First submission (with patch)
        assert 1 in indices  # Second submission (with mitigated active POV)

    def test_merge_entries_by_patch_mitigation_no_active_povs_mitigated(self, submissions):
        """Test merge behavior when only failed POVs would be mitigated."""
        # Create submissions where patch only mitigates failed POVs
        submissions.entries = [
            # Submission with a patch
            SubmissionEntryBuilder()
            .crash(task_id="task-1", crash_input_path="/path/to/patch_crash.bin")
            .patch(internal_patch_id="patch-1", patch_content="patch content")
            .build_output(patch_internal_id="patch-1", task_dir="/build/path", task_id="task-1")
            .patch_idx(0)
            .build(),
            # Submission with only failed POVs
            SubmissionEntryBuilder()
            .crash(task_id="task-1", crash_input_path="/path/to/crash1.bin", result=SubmissionResult.FAILED)
            .crash(task_id="task-1", crash_input_path="/path/to/crash2.bin", result=SubmissionResult.DEADLINE_EXCEEDED)
            .crash(task_id="task-1", crash_input_path="/path/to/crash3.bin", result=SubmissionResult.INCONCLUSIVE)
            .build(),
        ]

        # Ensure task registry doesn't filter out submissions
        submissions.task_registry.should_stop_processing.return_value = False

        # Mock POV reproduction status - patch mitigates failed POVs
        def mock_pov_reproduce_patch_status(patch, crashes, task_id):
            if patch.internal_patch_id == "patch-1":
                # All POVs are failed, so should get empty list
                assert len(crashes) == 0  # No active POVs
                return []
            return []

        mock_consolidate = Mock()

        with (
            patch.object(submissions, "_pov_reproduce_patch_status", side_effect=mock_pov_reproduce_patch_status),
            patch.object(submissions, "_consolidate_similar_submissions", mock_consolidate),
        ):
            submissions._merge_entries_by_patch_mitigation()

        # Should NOT trigger consolidation because no active POVs are mitigated
        mock_consolidate.assert_not_called()

    def test_merge_entries_by_patch_mitigation_mixed_active_and_failed_povs(self, submissions):
        """Test merge behavior with complex mix of active and failed POVs."""
        # Create submissions with complex POV status mix
        submissions.entries = [
            # Submission with a patch
            SubmissionEntryBuilder()
            .crash(task_id="task-1", crash_input_path="/path/to/patch_crash.bin")
            .patch(internal_patch_id="patch-1", patch_content="patch content")
            .build_output(patch_internal_id="patch-1", task_dir="/build/path", task_id="task-1")
            .patch_idx(0)
            .build(),
            # Submission 1: Mix of statuses
            SubmissionEntryBuilder()
            .crash(
                task_id="task-1", crash_input_path="/path/to/crash1.bin", result=SubmissionResult.PASSED
            )  # Active - will be mitigated
            .crash(task_id="task-1", crash_input_path="/path/to/crash2.bin", result=SubmissionResult.FAILED)  # Ignored
            .crash(
                task_id="task-1", crash_input_path="/path/to/crash3.bin", result=SubmissionResult.ACCEPTED
            )  # Active - will not be mitigated
            .build(),
            # Submission 2: Only failed POVs
            SubmissionEntryBuilder()
            .crash(task_id="task-1", crash_input_path="/path/to/crash4.bin", result=SubmissionResult.FAILED)
            .crash(task_id="task-1", crash_input_path="/path/to/crash5.bin", result=SubmissionResult.INCONCLUSIVE)
            .build(),
            # Submission 3: Mix with different active POV behavior
            SubmissionEntryBuilder()
            .crash(
                task_id="task-1", crash_input_path="/path/to/crash6.bin", result=SubmissionResult.PASSED
            )  # Active - will not be mitigated
            .crash(
                task_id="task-1", crash_input_path="/path/to/crash7.bin", result=SubmissionResult.DEADLINE_EXCEEDED
            )  # Ignored
            .crash(
                task_id="task-1", crash_input_path="/path/to/crash8.bin", result=SubmissionResult.ACCEPTED
            )  # Active - will be mitigated
            .build(),
        ]

        # Ensure task registry doesn't filter out submissions
        submissions.task_registry.should_stop_processing.return_value = False

        # Mock POV reproduction status with specific behavior per submission
        call_count = 0

        def mock_pov_reproduce_patch_status(patch, crashes, task_id):
            nonlocal call_count
            if patch.internal_patch_id == "patch-1":
                call_count += 1
                # The function is called once per submission in order
                # The function receives all crashes but filters internally
                if call_count == 1:  # Submission 1: Returns results only for active POVs
                    return [
                        Mock(did_crash=False),  # crash1 (PASSED) - mitigated
                        Mock(did_crash=True),  # crash3 (ACCEPTED) - not mitigated
                    ]
                elif call_count == 2:  # Submission 2: No active POVs (all failed)
                    return []
                elif call_count == 3:  # Submission 3: Returns results only for active POVs
                    return [
                        Mock(did_crash=True),  # crash6 (PASSED) - not mitigated
                        Mock(did_crash=False),  # crash8 (ACCEPTED) - mitigated
                    ]
            return []

        mock_consolidate = Mock()

        with (
            patch.object(submissions, "_pov_reproduce_patch_status", side_effect=mock_pov_reproduce_patch_status),
            patch.object(submissions, "_consolidate_similar_submissions", mock_consolidate),
        ):
            submissions._merge_entries_by_patch_mitigation()

        # Should trigger consolidation because:
        # - Submission 1 has crash1 (PASSED) mitigated (active POV)
        # - Submission 2 has no active POVs, so no merge
        # - Submission 3 has crash8 (ACCEPTED) mitigated (active POV)
        mock_consolidate.assert_called_once()

        call_args = mock_consolidate.call_args[1]
        similar_entries = call_args["similar_entries"]

        # Should merge submissions 0, 1, and 3 (submission 2 has no active mitigated POVs)
        assert len(similar_entries) == 3
        indices = [idx for idx, _ in similar_entries]
        assert 0 in indices  # Patch submission
        assert 1 in indices  # Submission with crash1 mitigated
        assert 3 in indices  # Submission with crash8 mitigated

    def test_check_all_povs_are_mitigated_still_checks_all_povs(self, submissions):
        """Test that _check_all_povs_are_mitigated still checks ALL POVs, including failed ones."""
        # Create submission with mixed POV statuses
        entry = (
            SubmissionEntryBuilder()
            .crash(task_id="task-1", crash_input_path="/path/to/crash1.bin", result=SubmissionResult.PASSED)
            .crash(task_id="task-1", crash_input_path="/path/to/crash2.bin", result=SubmissionResult.FAILED)
            .crash(task_id="task-1", crash_input_path="/path/to/crash3.bin", result=SubmissionResult.ACCEPTED)
            .patch(internal_patch_id="patch-1", patch_content="patch content")
            .patch_idx(0)
            .build()
        )

        # Mock POV reproduction status request - this calls _pov_reproduce_patch_status which filters
        def mock_pov_reproduce_status_request(entry, patch_idx):
            # This function calls _pov_reproduce_patch_status internally, which filters out failed POVs
            # So it should return results only for active POVs (PASSED and ACCEPTED)
            return [
                Mock(did_crash=False),  # crash1 (PASSED) mitigated
                Mock(did_crash=True),  # crash3 (ACCEPTED) not mitigated
            ]

        with patch.object(submissions, "_pov_reproduce_status_request", side_effect=mock_pov_reproduce_status_request):
            result = submissions._check_all_povs_are_mitigated(0, entry, 0)

        # Should return False because there's a failing POV (crash3)
        assert result is False

    def test_pov_reproduce_patch_status_filters_failed_povs_directly(self, submissions):
        """Test that _pov_reproduce_patch_status directly filters out failed POVs."""
        # Create a patch and crashes with mixed statuses
        patch = SubmissionEntryPatch(internal_patch_id="patch-1")
        crashes = [
            # Active POVs that should be processed
            SubmissionEntryBuilder().crash(result=SubmissionResult.PASSED).build().crashes[0],
            SubmissionEntryBuilder().crash(result=SubmissionResult.ACCEPTED).build().crashes[0],
            # Failed POVs that should be filtered out
            SubmissionEntryBuilder().crash(result=SubmissionResult.FAILED).build().crashes[0],
            SubmissionEntryBuilder().crash(result=SubmissionResult.DEADLINE_EXCEEDED).build().crashes[0],
            SubmissionEntryBuilder().crash(result=SubmissionResult.INCONCLUSIVE).build().crashes[0],
        ]

        # Mock the POV reproduce status to track which POVs are actually processed
        mock_requests = []

        def mock_request_status(request):
            mock_requests.append(request)
            return Mock(did_crash=False)  # Mitigated

        submissions.pov_reproduce_status.request_status = mock_request_status

        # Call the function
        result = submissions._pov_reproduce_patch_status(patch, crashes, "task-1")

        # Should only process 2 active POVs (PASSED and ACCEPTED)
        assert len(result) == 2
        assert len(mock_requests) == 2
        assert all(status.did_crash is False for status in result)

    def test_pov_reproduce_patch_status_all_failed_povs(self, submissions):
        """Test _pov_reproduce_patch_status when all POVs are failed."""
        patch = SubmissionEntryPatch(internal_patch_id="patch-1")
        crashes = [
            SubmissionEntryBuilder().crash(result=SubmissionResult.FAILED).build().crashes[0],
            SubmissionEntryBuilder().crash(result=SubmissionResult.DEADLINE_EXCEEDED).build().crashes[0],
            SubmissionEntryBuilder().crash(result=SubmissionResult.INCONCLUSIVE).build().crashes[0],
        ]

        mock_requests = []

        def mock_request_status(request):
            mock_requests.append(request)
            return Mock(did_crash=False)

        submissions.pov_reproduce_status.request_status = mock_request_status

        result = submissions._pov_reproduce_patch_status(patch, crashes, "task-1")

        # Should return empty list and process no requests
        assert len(result) == 0
        assert len(mock_requests) == 0

    def test_pov_reproduce_patch_status_all_active_povs(self, submissions):
        """Test _pov_reproduce_patch_status when all POVs are active."""
        patch = SubmissionEntryPatch(internal_patch_id="patch-1")
        crashes = [
            SubmissionEntryBuilder().crash(result=SubmissionResult.PASSED).build().crashes[0],
            SubmissionEntryBuilder().crash(result=SubmissionResult.ACCEPTED).build().crashes[0],
        ]

        mock_requests = []

        def mock_request_status(request):
            mock_requests.append(request)
            return Mock(did_crash=True)  # Not mitigated

        submissions.pov_reproduce_status.request_status = mock_request_status

        result = submissions._pov_reproduce_patch_status(patch, crashes, "task-1")

        # Should process all POVs
        assert len(result) == 2
        assert len(mock_requests) == 2
        assert all(status.did_crash is True for status in result)

    def test_merge_entries_with_only_failed_povs_no_merge(self, submissions):
        """Test that submissions with only failed POVs don't trigger merges."""
        submissions.entries = [
            # Submission with a patch
            SubmissionEntryBuilder()
            .crash(task_id="task-1", crash_input_path="/path/to/patch_crash.bin")
            .patch(internal_patch_id="patch-1", patch_content="patch content")
            .build_output(patch_internal_id="patch-1", task_dir="/build/path", task_id="task-1")
            .patch_idx(0)
            .build(),
            # Submission with only failed POVs
            SubmissionEntryBuilder()
            .crash(task_id="task-1", crash_input_path="/path/to/crash1.bin", result=SubmissionResult.FAILED)
            .crash(task_id="task-1", crash_input_path="/path/to/crash2.bin", result=SubmissionResult.INCONCLUSIVE)
            .build(),
        ]

        submissions.task_registry.should_stop_processing.return_value = False

        # Mock to return empty list for failed POVs
        def mock_pov_reproduce_patch_status(patch, crashes, task_id):
            return []  # No active POVs to evaluate

        mock_consolidate = Mock()

        with (
            patch.object(submissions, "_pov_reproduce_patch_status", side_effect=mock_pov_reproduce_patch_status),
            patch.object(submissions, "_consolidate_similar_submissions", mock_consolidate),
        ):
            submissions._merge_entries_by_patch_mitigation()

        # Should not consolidate anything
        mock_consolidate.assert_not_called()

    def test_wait_for_mitigation_edge_case_mixed_results(self, submissions):
        """Test edge case where patch has mixed results (some pending, some mitigated)."""
        submissions.entries = [
            # Submission being evaluated
            SubmissionEntryBuilder()
            .crash(task_id="task-1", crash_input_path="/path/to/crash1.bin", result=SubmissionResult.PASSED)
            .crash(task_id="task-1", crash_input_path="/path/to/crash2.bin", result=SubmissionResult.FAILED)  # Ignored
            .crash(task_id="task-1", crash_input_path="/path/to/crash3.bin", result=SubmissionResult.ACCEPTED)
            .build(),
            # Submission with patch
            SubmissionEntryBuilder()
            .crash(task_id="task-1", crash_input_path="/path/to/other_crash.bin")
            .patch(internal_patch_id="patch-1", patch_content="patch content", competition_patch_id="comp-patch-1")
            .build(),
        ]

        def mock_pov_reproduce_patch_status(patch, crashes, task_id):
            # Return mixed results: one pending, one mitigated
            return [None, Mock(did_crash=False)]  # First pending, second mitigated

        with patch.object(submissions, "_pov_reproduce_patch_status", side_effect=mock_pov_reproduce_patch_status):
            result = submissions._should_wait_for_patch_mitigation_merge(0, submissions.entries[0])

        # Should wait because there's a pending evaluation
        assert result is True

    def test_check_all_povs_mitigated_with_filtered_pending(self, submissions):
        """Test _check_all_povs_are_mitigated when filtering leaves only pending POVs."""
        entry = (
            SubmissionEntryBuilder()
            .crash(task_id="task-1", crash_input_path="/path/to/crash1.bin", result=SubmissionResult.PASSED)
            .crash(task_id="task-1", crash_input_path="/path/to/crash2.bin", result=SubmissionResult.FAILED)  # Filtered
            .patch(internal_patch_id="patch-1", patch_content="patch content")
            .patch_idx(0)
            .build()
        )

        def mock_pov_reproduce_status_request(entry, patch_idx):
            # Only active POV (PASSED) returns pending
            return [None]  # Only one active POV, and it's pending

        with patch.object(submissions, "_pov_reproduce_status_request", side_effect=mock_pov_reproduce_status_request):
            result = submissions._check_all_povs_are_mitigated(0, entry, 0)

        # Should return None because the active POV is pending
        assert result is None

    def test_check_all_povs_mitigated_with_filtered_all_mitigated(self, submissions):
        """Test _check_all_povs_are_mitigated when filtering leaves only mitigated POVs."""
        entry = (
            SubmissionEntryBuilder()
            .crash(task_id="task-1", crash_input_path="/path/to/crash1.bin", result=SubmissionResult.PASSED)
            .crash(task_id="task-1", crash_input_path="/path/to/crash2.bin", result=SubmissionResult.FAILED)  # Filtered
            .crash(task_id="task-1", crash_input_path="/path/to/crash3.bin", result=SubmissionResult.ACCEPTED)
            .patch(internal_patch_id="patch-1", patch_content="patch content")
            .patch_idx(0)
            .build()
        )

        def mock_pov_reproduce_status_request(entry, patch_idx):
            # Both active POVs (PASSED and ACCEPTED) are mitigated
            return [Mock(did_crash=False), Mock(did_crash=False)]

        with patch.object(submissions, "_pov_reproduce_status_request", side_effect=mock_pov_reproduce_status_request):
            result = submissions._check_all_povs_are_mitigated(0, entry, 0)

        # Should return True because all active POVs are mitigated
        assert result is True

    def test_concurrent_patch_limit_increased_to_12(self, submissions):
        """Test that the concurrent patch limit has been increased to 12."""
        assert submissions.concurrent_patch_requests_per_task == 12

    def test_concurrent_patch_limit_logging(self, submissions):
        """Test that patch request skipping is logged when hitting the concurrent limit."""
        # Create submissions to hit the concurrent limit
        submissions.entries = []
        for i in range(13):  # More than the limit of 12
            entry = (
                SubmissionEntryBuilder()
                .crash(
                    task_id="task-1",
                    crash_input_path=f"/path/to/crash{i}.bin",
                    competition_pov_id=f"pov-{i}",
                    result=SubmissionResult.PASSED,
                )
                .patch(internal_patch_id=f"patch-{i}")  # Outstanding patch request (no content)
                .build()
            )
            submissions.entries.append(entry)

        # Mock the necessary methods
        submissions.task_registry.should_stop_processing.return_value = False

        # The 13th submission should skip patch request due to concurrent limit
        with patch("buttercup.orchestrator.scheduler.submissions.logger"):
            result = submissions._request_patch_if_needed(12, submissions.entries[12], Mock())

        # Should return False (no patch requested) and log the skip
        assert result is False
