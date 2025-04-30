from dataclasses import field, dataclass
from functools import lru_cache
import logging
import base64
from redis import Redis
from typing import Iterator, List, Tuple
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode
import buttercup.common.node_local as node_local
from buttercup.common.datastructures.msg_pb2 import (
    TracedCrash,
    ConfirmedVulnerability,
    SubmissionEntry,
    Patch,
)
from buttercup.common.sarif_store import SARIFStore
from buttercup.common.constants import ARCHITECTURE
from buttercup.common.queues import QueueFactory, QueueNames
from buttercup.common.telemetry import set_crs_attributes, CRSActionCategory

from buttercup.orchestrator.registry import TaskRegistry
from buttercup.orchestrator.competition_api_client.models.types_pov_submission import TypesPOVSubmission
from buttercup.orchestrator.competition_api_client.models.types_patch_submission import TypesPatchSubmission
from buttercup.orchestrator.competition_api_client.models.types_bundle_submission import TypesBundleSubmission
from buttercup.orchestrator.competition_api_client.models.types_submission_status import TypesSubmissionStatus
from buttercup.orchestrator.competition_api_client.models.types_sarif_assessment_submission import (
    TypesSarifAssessmentSubmission,
)
from buttercup.orchestrator.competition_api_client.models.types_assessment import TypesAssessment
from buttercup.orchestrator.competition_api_client.api_client import ApiClient
from buttercup.orchestrator.competition_api_client.api import PovApi, PatchApi, BundleApi, BroadcastSarifAssessmentApi

logger = logging.getLogger(__name__)


def log_structured(
    fn,
    task_id: str,
    index: int | None = None,
    pov_id: str | None = None,
    patch_id: str | None = None,
    bundle_id: str | None = None,
    patch_idx: int | None = None,
    sarif_id: str | None = None,
    state_change: Tuple[str, str] | None = None,
    msg: str = "",
):
    """Log a structured message for easy grepping and filtering."""
    log_msg = f"[{index}:{task_id}]"
    if pov_id:
        log_msg += f" pov_id={pov_id}"
    if patch_id:
        log_msg += f" patch_id={patch_id}"
    if bundle_id:
        log_msg += f" bundle_id={bundle_id}"
    if patch_idx:
        log_msg += f" patch_idx={patch_idx}"
    if sarif_id:
        log_msg += f" sarif_id={sarif_id}"

    if state_change:
        old_state, new_state = state_change
        log_msg += f" {old_state} -> {new_state}"

    if msg:
        log_msg += f" {msg}"

    fn(log_msg)


def _task_id(e: SubmissionEntry | TracedCrash) -> str:
    """Get the task_id from the SubmissionEntry or TracedCrash."""
    if isinstance(e, TracedCrash):
        return e.crash.target.task_id
    elif isinstance(e, SubmissionEntry):
        return e.crash.crash.target.task_id
    else:
        raise ValueError(f"Unknown submission entry type: {type(e)}")


def _have_more_patches(e: SubmissionEntry) -> bool:
    """Check if there are more patches to try (following the current patch if any)."""
    return e.patch_idx + 1 < len(e.patches)


def _advance_patch_idx(e: SubmissionEntry) -> None:
    """Advance the patch index to the next patch."""
    e.patch_idx += 1
    e.patch_submission_attempt = 0


class CompetitionAPI:
    """
    Simplified interface for the competition API.

    Handles submission formatting, error handling, and response parsing for:
    - Vulnerability proofs (POVs)
    - Patches
    - Bundles (vulnerability + patch combinations)

    Each method handles errors and returns results in a consistent format.
    """

    def __init__(self, api_client: ApiClient, task_registry: TaskRegistry):
        """
        Initialize with an API client.

        Args:
            api_client: Client for making HTTP requests
            task_registry: Task registry for getting task metadata
        """
        self.api_client = api_client
        self.task_registry = task_registry

    @lru_cache(maxsize=10)
    def _get_task_metadata(self, task_id: str) -> dict:
        """Get the task metadata for a given task ID.

        Note: this is cached because the task metadata is immutable.
        """
        return dict(self.task_registry.get(task_id).metadata)

    def submit_pov(self, crash: TracedCrash) -> Tuple[str | None, TypesSubmissionStatus]:
        """
        Submit a vulnerability (POV) to the competition API.

        Reads crash input, encodes as base64, and submits with required metadata.

        Args:
            crash: TracedCrash with crash details and metadata

        Returns:
            Tuple[str | None, TypesSubmissionStatus]:
                - POV ID if successful, None otherwise
                - Submission status
        """
        try:
            # Read crash input file contents and encode as base64
            with node_local.lopen(crash.crash.crash_input_path, "rb") as f:
                crash_data = base64.b64encode(f.read()).decode()

            # Create submission payload from crash data
            submission = TypesPOVSubmission(
                architecture=ARCHITECTURE,
                engine=crash.crash.target.engine,
                fuzzer_name=crash.crash.harness_name,
                sanitizer=crash.crash.target.sanitizer,
                testcase=crash_data,
            )

            # Telemetry
            tracer = trace.get_tracer(__name__)
            with tracer.start_as_current_span("submit_pov_for_scoring") as span:
                set_crs_attributes(
                    span,
                    crs_action_category=CRSActionCategory.SCORING_SUBMISSION,
                    crs_action_name="submit_pov_for_scoring",
                    task_metadata=self._get_task_metadata(_task_id(crash)),
                    extra_attributes={
                        "crs.action.target.harness": crash.crash.harness_name,
                    },
                )

                # Submit Pov and get response
                response = PovApi(api_client=self.api_client).v1_task_task_id_pov_post(
                    task_id=crash.crash.target.task_id,
                    payload=submission,
                )
                logger.debug(f"[{crash.crash.target.task_id}] POV submission response: {response}")
                if response.status not in [TypesSubmissionStatus.ACCEPTED, TypesSubmissionStatus.PASSED]:
                    logger.error(
                        f"[{crash.crash.target.task_id}] POV submission rejected (status: {response.status}) for harness: {crash.crash.harness_name}"
                    )
                    span.set_status(Status(StatusCode.ERROR))
                    return None, response.status

                span.set_status(Status(StatusCode.OK))
                return response.pov_id, response.status
        except Exception as e:
            logger.error(f"[{crash.crash.target.task_id}] Failed to submit vulnerability: {e}")
            return None, TypesSubmissionStatus.ERRORED

    def get_pov_status(self, task_id: str, pov_id: str) -> TypesSubmissionStatus:
        """
        Get vulnerability submission status.

        Args:
            task_id: Task ID associated with the vulnerability
            pov_id: POV ID from submit_vulnerability

        Returns:
            TypesSubmissionStatus: Current status (ACCEPTED, PASSED, FAILED, ERRORED, DEADLINE_EXCEEDED)
        """
        assert task_id
        assert pov_id

        return PovApi(api_client=self.api_client).v1_task_task_id_pov_pov_id_get(task_id=task_id, pov_id=pov_id).status

    def submit_patch(self, task_id: str, patch: str) -> Tuple[str | None, TypesSubmissionStatus]:
        """
        Submit a patch to the competition API.

        Args:
            task_id: Task ID of the vulnerability being patched
            patch: Patch content string

        Returns:
            Tuple[str | None, TypesSubmissionStatus]:
                - Patch ID if accepted, None otherwise
                - Submission status
        """
        assert task_id
        assert patch

        encoded_patch = base64.b64encode(patch.encode()).decode()
        submission = TypesPatchSubmission(
            patch=encoded_patch,
        )

        # Telemetry
        tracer = trace.get_tracer(__name__)
        with tracer.start_as_current_span("submit_patch_for_scoring") as span:
            set_crs_attributes(
                span,
                crs_action_category=CRSActionCategory.SCORING_SUBMISSION,
                crs_action_name="submit_patch_for_scoring",
                task_metadata=self._get_task_metadata(task_id),
            )

            response = PatchApi(api_client=self.api_client).v1_task_task_id_patch_post(
                task_id=task_id, payload=submission
            )
            logger.debug(f"[{task_id}] Patch submission response: {response}")
            if response.status not in [TypesSubmissionStatus.ACCEPTED, TypesSubmissionStatus.PASSED]:
                logger.error(f"[{task_id}] Patch submission rejected (status: {response.status}) for harness: {patch}")
                span.set_status(Status(StatusCode.ERROR))
                return (None, response.status)

            span.set_status(Status(StatusCode.OK))
            return (response.patch_id, response.status)

    def get_patch_status(self, task_id: str, patch_id: str) -> TypesSubmissionStatus:
        """
        Get patch submission status.

        Args:
            task_id: Task ID associated with the patch
            patch_id: Patch ID from submit_patch

        Returns:
            TypesSubmissionStatus: Current status (ACCEPTED, PASSED, FAILED, ERRORED, DEADLINE_EXCEEDED)
        """
        assert task_id
        assert patch_id

        response = PatchApi(api_client=self.api_client).v1_task_task_id_patch_patch_id_get(
            task_id=task_id, patch_id=patch_id
        )
        if response.functionality_tests_passing is not None:
            logger.info(
                f"[{task_id}] Patch {patch_id} functionality tests passing: {response.functionality_tests_passing}"
            )
        return response.status

    def submit_bundle(self, task_id: str, pov_id: str, patch_id: str) -> Tuple[str | None, TypesSubmissionStatus]:
        """
        Submit a bundle (vulnerability + patch).

        Args:
            task_id: Task ID for the submission
            pov_id: POV ID of verified vulnerability
            patch_id: Patch ID of verified patch

        Returns:
            Tuple[str | None, TypesSubmissionStatus]:
                - Bundle ID if successful, None otherwise
                - Submission status
        """
        assert task_id
        assert pov_id
        assert patch_id

        submission = TypesBundleSubmission(
            pov_id=pov_id,
            patch_id=patch_id,
        )

        # Telemetry
        tracer = trace.get_tracer(__name__)
        with tracer.start_as_current_span("submit_bundle_for_scoring") as span:
            set_crs_attributes(
                span,
                crs_action_category=CRSActionCategory.SCORING_SUBMISSION,
                crs_action_name="submit_bundle_for_scoring",
                task_metadata=self._get_task_metadata(task_id),
            )

            response = BundleApi(api_client=self.api_client).v1_task_task_id_bundle_post(
                task_id=task_id, payload=submission
            )
            logger.debug(f"[{task_id}] Bundle submission response: {response}")
            if response.status not in [TypesSubmissionStatus.ACCEPTED, TypesSubmissionStatus.PASSED]:
                logger.error(
                    f"[{task_id}] Bundle submission rejected (status: {response.status}) for harness: {pov_id} {patch_id}"
                )
                span.set_status(Status(StatusCode.ERROR))
                return (None, response.status)

            span.set_status(Status(StatusCode.OK))
            return (response.bundle_id, response.status)

    def patch_bundle(
        self, task_id: str, bundle_id: str, pov_id: str, patch_id: str, sarif_id: str
    ) -> Tuple[bool, TypesSubmissionStatus]:
        """
        Submit a bundle patch with SARIF association.

        Args:
            task_id: Task ID for the submission
            bundle_id: Bundle ID to patch
            pov_id: POV ID of verified vulnerability
            patch_id: Patch ID of verified patch
            sarif_id: SARIF ID to associate with the bundle

        Returns:
            Tuple[bool, TypesSubmissionStatus]:
                - True if successful, False otherwise
                - Submission status
        """
        assert task_id
        assert bundle_id
        assert pov_id
        assert patch_id
        assert sarif_id

        submission = TypesBundleSubmission(
            bundle_id=bundle_id,
            pov_id=pov_id,
            patch_id=patch_id,
            broadcast_sarif_id=sarif_id,
        )
        response = BundleApi(api_client=self.api_client).v1_task_task_id_bundle_bundle_id_patch_post(
            task_id=task_id, bundle_id=bundle_id, payload=submission
        )
        logger.debug(f"[{task_id}] Bundle patch submission response: {response}")
        if response.status not in [TypesSubmissionStatus.ACCEPTED, TypesSubmissionStatus.PASSED]:
            logger.error(
                f"[{task_id}] Bundle patch submission rejected (status: {response.status}) for harness: {pov_id} {patch_id} {sarif_id}"
            )
            return (False, response.status)
        return (True, response.status)

    def submit_matching_sarif(self, task_id: str, sarif_id: str) -> Tuple[bool, TypesSubmissionStatus]:
        """
        Submit a matching assessment for a SARIF report.

        Used to claim overlap between our vulnerability findings and a broadcast SARIF.

        Args:
            task_id: Task ID for the submission
            sarif_id: ID of the broadcast SARIF report to assess

        Returns:
            Tuple[bool, TypesSubmissionStatus]:
                - True if successful, False otherwise
                - Submission status
        """
        assert task_id
        assert sarif_id

        # TODO: The description is the most basic I could think of. I don't know if we wanted to do something more fancy.
        submission = TypesSarifAssessmentSubmission(
            assessment=TypesAssessment.CORRECT,
            description="Overlapping with our POV/patch",
        )

        # Telemetry
        tracer = trace.get_tracer(__name__)
        with tracer.start_as_current_span("submit_SARIF_for_scoring") as span:
            set_crs_attributes(
                span,
                crs_action_category=CRSActionCategory.SCORING_SUBMISSION,
                crs_action_name="submit_SARIF_for_scoring",
                task_metadata=self._get_task_metadata(task_id),
            )

            response = BroadcastSarifAssessmentApi(
                api_client=self.api_client
            ).v1_task_task_id_broadcast_sarif_assessment_broadcast_sarif_id_post(
                task_id=task_id, broadcast_sarif_id=sarif_id, payload=submission
            )
            logger.debug(f"[{task_id}] Matching SARIF submission response: {response}")
            if response.status not in [TypesSubmissionStatus.ACCEPTED, TypesSubmissionStatus.PASSED]:
                logger.error(
                    f"[{task_id}] Matching SARIF submission rejected (status: {response.status}) for sarif_id: {sarif_id}"
                )
                span.set_status(Status(StatusCode.ERROR))
                return (False, response.status)

            span.set_status(Status(StatusCode.OK))
            return (True, response.status)


@dataclass
class Submissions:
    """
    A class for managing submissions to the competition API.

    The Submissions class handles the lifecycle of three types of submissions:
    - Vulnerabilities (POVs) - Proof of Vulnerabilities submitted to the competition
    - Patches - Fixes for vulnerabilities
    - Bundles - Combinations of a vulnerability and its patch

    State Transitions
    ----------------

    Vulnerability (POV) States:

    1. Initial submission:
       - POV is submitted via submit_vulnerability()
       - Initial state: V_ACCEPTED

    2. State transitions:
       - V_ACCEPTED → V_PATCH_REQUESTED: When patch requests are sent via _submit_patch_requests()
       - V_PATCH_REQUESTED → V_PASSED: Competition API confirms the vulnerability is valid
       - V_PATCH_REQUESTED → V_FAILED: Competition API rejects the vulnerability
       - V_PATCH_REQUESTED → V_ERRORED: Competition API reports an error with the vulnerability
       - V_ERRORED → V_ACCEPTED: When resubmission succeeds via _resubmit_errored_submissions()

    Patch States:

    1. Initial recording:
       - Patch is recorded via record_patch()
       - No initial state - patch is just added to the list of patches for a vulnerability

    2. Submission:
       - Patches are submitted via _submit_patches() when the associated vulnerability has V_PASSED state
       - Initial state upon submission: P_ACCEPTED

    3. State transitions:
       - P_ACCEPTED → P_PASSED: Competition API confirms the patch is valid
       - P_ACCEPTED → P_FAILED: Competition API rejects the patch
       - P_ACCEPTED → P_ERRORED: Competition API reports an error with the patch
       - P_ERRORED → P_ACCEPTED: When resubmission succeeds via _resubmit_errored_patches()
       - P_ERRORED → P_FAILED: If patch submission fails too many times (patch_submission_attempt_limit reached)

    Bundle States:

    1. Initial submission:
       - Bundle is submitted via _submit_bundles() when both vulnerability has V_PASSED and patch has P_PASSED
       - Initial state: B_ACCEPTED

    2. State transitions:
       - B_ACCEPTED → B_PASSED: Competition API confirms the bundle is valid
       - B_ACCEPTED → B_FAILED: Competition API rejects the bundle
       - B_ACCEPTED → B_ERRORED: Competition API reports an error with the bundle
       - B_ERRORED → B_ACCEPTED: When resubmission is attempted via _resubmit_errored_bundles()

    Processing Cycles
    ----------------
    The process_cycle() method orchestrates all the state transitions in sequence:

    1. Vulnerability Processing:
       - _submit_patch_requests(): Request patches for newly accepted vulnerabilities
       - _update_vuln_status(): Update status of vulnerabilities with the competition API
       - _resubmit_errored_submissions(): Retry errored vulnerability submissions

    2. Patch Processing:
       - _submit_patches(): Submit patches for passed vulnerabilities
       - _update_patch_status(): Update status of patches with the competition API
       - _advance_patch_idx_for_failed_patches(): Move to next patch if current one failed
       - _resubmit_errored_patches(): Retry errored patch submissions

    3. Bundle Processing:
       - _submit_bundles(): Submit bundles for passed vulnerability-patch pairs
       - _update_bundle_status(): Update status of bundles with the competition API
       - _resubmit_errored_bundles(): Retry errored bundle submissions

    Assumptions:
    - Submissions are stored in redis but also kept in memory for fast access.
    - There is only ever one instance of this class.

    This class is mostly concerned with the submission logic and ensuring that state is persisted to Redis.
    The actual submission logic is delegated to the CompetitionAPI class.
    """

    # Redis names
    SUBMISSIONS = "submissions"

    redis: Redis
    competition_api: CompetitionAPI
    task_registry: TaskRegistry
    patch_submission_retry_limit: int = 60
    patch_requests_per_vulnerability: int = 1
    entries: List[SubmissionEntry] = field(init=False)
    sarif_store: SARIFStore = field(init=False)

    def __post_init__(self):
        logger.info(
            f"Initializing Submissions, patch_submission_retry_limit={self.patch_submission_retry_limit}, patch_requests_per_vulnerability={self.patch_requests_per_vulnerability}"
        )
        self.entries = self._get_stored_submissions()
        self.sarif_store = SARIFStore(self.redis)

    def _get_stored_submissions(self) -> List[SubmissionEntry]:
        """Get all stored submissions from Redis."""
        return [SubmissionEntry.FromString(raw) for raw in self.redis.lrange(self.SUBMISSIONS, 0, -1)]

    def _persist(self, redis: Redis, index: int, entry: SubmissionEntry):
        """Persist the submissions to Redis."""
        redis.lset(self.SUBMISSIONS, index, entry.SerializeToString())

    def _push(self, entry: SubmissionEntry):
        """Push a submission to Redis."""
        return self.redis.rpush(self.SUBMISSIONS, entry.SerializeToString())

    def _enumerate_submissions(self) -> Iterator[SubmissionEntry]:
        """Enumerate all submissions belonging to active tasks."""
        for i, e in enumerate(self.entries):
            if self.task_registry.should_stop_processing(_task_id(e)):
                continue
            yield i, e

    def _get_submission(self, index: int) -> SubmissionEntry | None:
        """
        Get a submission from the list of submissions if it is active.

        This method retrieves a submission entry by index and verifies if the associated task
        is still active (not cancelled or expired).

        Args:
            index: The index of the submission in the entries list

        Returns:
            The submission entry if found and active, None otherwise
        """
        try:
            e = self.entries[index]
            if self.task_registry.should_stop_processing(_task_id(e)):
                return None
            return e
        except IndexError:
            logger.error(
                f"BUG: Submission {index} not found. Entries (len={len(self.entries)}): {self.entries}.  This should never happen. Either the patcher was sent the wrong index or the patcher is buggy."
            )
            # Submission with this index doesn't exist
            return None

    def submit_vulnerability(self, crash: TracedCrash) -> bool:
        """
        Submit a vulnerability to the competition API and store the result in Redis.

        This method is the entry point for vulnerability submissions. It:
        1. Submits the crash information to the competition API
        2. If successful, creates a new SubmissionEntry with V_ACCEPTED state
        3. Persists the entry to Redis and adds it to the in-memory list

        Args:
            crash: The traced crash representing the vulnerability

        Returns:
            True if the submission was successful, False otherwise
        """
        if self.task_registry.should_stop_processing(_task_id(crash)):
            logger.info("Task is cancelled or expired, will not submit vulnerability.")
            logger.debug(f"CrashInfo: {crash}")
            return True

        pov_id, status = self.competition_api.submit_pov(crash)
        if not pov_id:
            log_structured(
                logger.error,
                _task_id(crash),
                msg=f"Failed to submit vulnerability. Competition API returned {status}.",
            )

            # If the API returned ERRORED, we want to retry.
            stop = status != TypesSubmissionStatus.ERRORED

            if stop:
                logger.info(f"Competition API returned {status}, will not retry.")
                logger.debug(f"CrashInfo: {crash}")
            return stop

        e = SubmissionEntry()
        e.crash.CopyFrom(crash)
        e.pov_id = pov_id
        e.state = SubmissionEntry.SUBMIT_PATCH_REQUEST

        # Persist to Redis
        length = self._push(e)
        index = length - 1

        # If this fails, we have a bug.  Let it crash. Reloading the Submissions object will "fix it".
        assert index == len(self.entries)

        # Keep the entries list in sync
        self.entries.append(e)
        log_structured(
            logger.info, _task_id(e), index=index, pov_id=e.pov_id, state_change=("", "SUBMIT_PATCH_REQUEST")
        )
        return True

    def record_patch(self, patch: Patch) -> bool:
        """
        Record a patch for a previously submitted vulnerability.

        This method:
        1. Retrieves the submission entry for the specified index
        2. Validates that the task IDs match
        3. Adds the patch to the entry's list of patches
        4. Persists the updated entry to Redis

        Note: This doesn't submit the patch to the competition API immediately.
        The patch will be submitted later when the vulnerability passes validation.

        Args:
            patch: The patch to record, containing submission_index and task_id

        Returns:
            True if the patch was successfully recorded, False if the submission doesn't exist
        """
        index = int(patch.submission_index)
        e = self._get_submission(index)
        if not e:
            logger.error(f"Submission {index} not found. Task might not be active.")
            return False

        assert _task_id(e) == patch.task_id
        e.patches.append(patch.patch)
        self._persist(self.redis, index, e)
        log_structured(
            logger.info, _task_id(e), index=index, pov_id=e.pov_id, patch_idx=len(e.patches) - 1, msg="Patch added"
        )
        return True

    def _submit_patch_request(self, i, e):
        """
        Request patch generation for a confirmed vulnerability.

        Pushes the vulnerability to the confirmed_vulnerabilities_queue
        and updates the state to WAIT_POV_PASS.

        Args:
            i: Index of the submission entry
            e: SubmissionEntry to process
        """
        log_structured(logger.info, _task_id(e), index=i, pov_id=e.pov_id, msg="Submitting patch request")
        confirmed = ConfirmedVulnerability()
        confirmed.crash.CopyFrom(e.crash)
        confirmed.submission_index = str(i)

        with self.redis.pipeline() as pipe:
            q = QueueFactory(pipe).create(QueueNames.CONFIRMED_VULNERABILITIES, block_time=None)
            for _ in range(self.patch_requests_per_vulnerability):
                q.push(confirmed)
            e.state = SubmissionEntry.WAIT_POV_PASS
            self._persist(pipe, i, e)
            pipe.execute()

        log_structured(
            logger.info, _task_id(e), pov_id=e.pov_id, index=i, state_change=("SUBMIT_PATCH_REQUEST", "WAIT_POV_PASS")
        )

    def _wait_pov_pass(self, i, e):
        """
        Check the status of a POV submission and update its state accordingly.

        Possible state transitions:
        - WAIT_POV_PASS → STOP: If POV failed or deadline exceeded
        - WAIT_POV_PASS → SUBMIT_PATCH: If POV passed validation
        - Resubmit if POV errored

        Args:
            i: Index of the submission entry
            e: SubmissionEntry to process
        """
        status = self.competition_api.get_pov_status(_task_id(e), e.pov_id)
        match status:
            case TypesSubmissionStatus.FAILED | TypesSubmissionStatus.DEADLINE_EXCEEDED:
                e.state = SubmissionEntry.STOP
                self._persist(self.redis, i, e)
                log_structured(
                    logger.info,
                    _task_id(e),
                    index=i,
                    pov_id=e.pov_id,
                    state_change=("WAIT_POV_PASS", "STOP"),
                    msg=f"POV failed (status={status}), stopping",
                )
            case TypesSubmissionStatus.PASSED:
                e.state = SubmissionEntry.SUBMIT_PATCH
                self._persist(self.redis, i, e)
                log_structured(
                    logger.info,
                    _task_id(e),
                    index=i,
                    pov_id=e.pov_id,
                    state_change=("WAIT_POV_PASS", "SUBMIT_PATCH"),
                    msg="POV passed, ready to submit patch when the patch is ready",
                )
            case TypesSubmissionStatus.ERRORED:
                log_structured(logger.info, _task_id(e), index=i, pov_id=e.pov_id, msg="POV errored, will resubmit")

                pov_id, status = self.competition_api.submit_pov(e.crash)
                if not pov_id:
                    log_structured(
                        logger.error,
                        _task_id(e),
                        msg=f"Failed to submit vulnerability. Competition API returned {status}.",
                    )

                    # If the API returned ERRORED, we want to retry.
                    if status != TypesSubmissionStatus.ERRORED:
                        e.state = SubmissionEntry.STOP
                        self._persist(self.redis, i, e)
                        log_structured(
                            logger.info,
                            _task_id(e),
                            index=i,
                            pov_id=e.pov_id,
                            state_change=("WAIT_POV_PASS", "STOP"),
                            msg=f"POV failed (status={status}), stopping",
                        )
                else:
                    e.pov_id = pov_id
                    self._persist(self.redis, i, e)
                    log_structured(
                        logger.info, _task_id(e), index=i, pov_id=e.pov_id, msg="POV resubmitted, waiting for pass"
                    )

            case _:
                assert status == TypesSubmissionStatus.ACCEPTED, f"Unexpected POV status: {status}"

    def _submit_patch(self, i, e):
        """
        Submit a patch to the competition API.

        Handles patch submission and updates state based on the result:
        - SUBMIT_PATCH → WAIT_PATCH_PASS: If patch is accepted
        - Advances to next patch if patch fails or deadline exceeded
        - Retries or advances patch if errors occur based on submission attempt count

        Args:
            i: Index of the submission entry
            e: SubmissionEntry to process
        """
        if e.patch_idx >= len(e.patches):
            # There are no patches to submit, or we've already submitted all patches
            return

        have_more_patches = _have_more_patches(e)
        patch = e.patches[e.patch_idx]
        log_structured(
            logger.info, _task_id(e), index=i, pov_id=e.pov_id, patch_idx=e.patch_idx, msg="Submitting patch"
        )
        logger.debug(f"patch: {patch[:512]}...")

        patch_id, status = self.competition_api.submit_patch(_task_id(e), patch)

        if patch_id:
            e.patch_id = patch_id
            e.patch_submission_attempt += 1
            e.state = SubmissionEntry.WAIT_PATCH_PASS
            self._persist(self.redis, i, e)
            log_structured(
                logger.info,
                _task_id(e),
                index=i,
                pov_id=e.pov_id,
                patch_idx=e.patch_idx,
                patch_id=patch_id,
                state_change=("SUBMIT_PATCH", "WAIT_PATCH_PASS"),
                msg="Patch accepted",
            )
        else:
            match status:
                case TypesSubmissionStatus.FAILED | TypesSubmissionStatus.DEADLINE_EXCEEDED:
                    # Deadline exceeded or failed, move on to next patch (for exceeded we won't try again due to deadline check)
                    e.patch_idx += 1
                    self._persist(self.redis, i, e)
                    log_structured(
                        logger.info,
                        _task_id(e),
                        index=i,
                        pov_id=e.pov_id,
                        patch_idx=e.patch_idx,
                        msg=f"Patch submission failed ({status}), will not attempt this patch again.",
                    )
                case TypesSubmissionStatus.ERRORED:
                    if have_more_patches and e.patch_submission_attempt >= self.patch_submission_retry_limit:
                        _advance_patch_idx(e)
                        self._persist(self.redis, i, e)
                        log_structured(
                            logger.info,
                            _task_id(e),
                            index=i,
                            pov_id=e.pov_id,
                            patch_idx=e.patch_idx,
                            msg=f"Patch submission errored too many times ({status}), moved on to next patch.",
                        )
                    else:
                        # Keep trying the same patch (if we don't have more patches or we haven't tried too many times)
                        e.patch_submission_attempt += 1
                        self._persist(self.redis, i, e)
                        log_structured(
                            logger.info,
                            _task_id(e),
                            index=i,
                            pov_id=e.pov_id,
                            patch_idx=e.patch_idx,
                            msg=f"Patch submission failed ({status}), will attempt this patch again (attempt={e.patch_submission_attempt}).",
                        )
                case _:
                    raise ValueError(f"Unexpected patch status: {status}")

    def _wait_patch_pass(self, i, e):
        """
        Check the status of a patch submission and update its state accordingly.

        Possible state transitions:
        - WAIT_PATCH_PASS → SUBMIT_PATCH: If patch failed, errored, or deadline exceeded
        - WAIT_PATCH_PASS → SUBMIT_BUNDLE: If patch passed validation

        Args:
            i: Index of the submission entry
            e: SubmissionEntry to process
        """
        status = self.competition_api.get_patch_status(_task_id(e), e.patch_id)
        match status:
            case TypesSubmissionStatus.FAILED | TypesSubmissionStatus.DEADLINE_EXCEEDED:
                _advance_patch_idx(e)
                e.state = SubmissionEntry.SUBMIT_PATCH
                self._persist(self.redis, i, e)
                log_structured(
                    logger.info,
                    _task_id(e),
                    index=i,
                    pov_id=e.pov_id,
                    patch_idx=e.patch_idx,
                    state_change=("WAIT_PATCH_PASS", "SUBMIT_PATCH"),
                    msg=f"Patch submission failed ({status}), will not attempt this patch again, moving on to next patch.",
                )
            case TypesSubmissionStatus.ERRORED:
                e.state = SubmissionEntry.SUBMIT_PATCH
                self._persist(self.redis, i, e)
                log_structured(
                    logger.info,
                    _task_id(e),
                    index=i,
                    pov_id=e.pov_id,
                    patch_idx=e.patch_idx,
                    state_change=("WAIT_PATCH_PASS", "SUBMIT_PATCH"),
                    msg=f"Patch submission errored ({status}), will attempt this patch again.",
                )
            case TypesSubmissionStatus.PASSED:
                e.state = SubmissionEntry.SUBMIT_BUNDLE
                self._persist(self.redis, i, e)
                log_structured(
                    logger.info,
                    _task_id(e),
                    index=i,
                    pov_id=e.pov_id,
                    patch_idx=e.patch_idx,
                    state_change=("WAIT_PATCH_PASS", "SUBMIT_BUNDLE"),
                    msg="Patch passed, submitting bundle",
                )
            case _:
                raise ValueError(f"Unexpected patch status: {status}")

    def _submit_bundle(self, i: int, e: SubmissionEntry) -> None:
        """
        Submit a bundle combining a validated vulnerability and patch.

        Possible state transitions:
        - SUBMIT_BUNDLE → STOP: If bundle submission failed or deadline exceeded
        - SUBMIT_BUNDLE → SUBMIT_MATCHING_SARIF: If bundle submission was successful

        Args:
            i: Index of the submission entry
            e: SubmissionEntry to process
        """
        bundle_id, status = self.competition_api.submit_bundle(_task_id(e), e.pov_id, e.patch_id)
        if not bundle_id:
            match status:
                case TypesSubmissionStatus.FAILED | TypesSubmissionStatus.DEADLINE_EXCEEDED:
                    e.state = SubmissionEntry.STOP
                    self._persist(self.redis, i, e)
                    log_structured(
                        logger.info,
                        _task_id(e),
                        index=i,
                        pov_id=e.pov_id,
                        patch_id=e.patch_id,
                        state_change=("SUBMIT_BUNDLE", "STOP"),
                        msg=f"Bundle submission failed ({status}), not much else to do but stop.",
                    )
                case TypesSubmissionStatus.ERRORED:
                    log_structured(
                        logger.info,
                        _task_id(e),
                        index=i,
                        pov_id=e.pov_id,
                        patch_id=e.patch_id,
                        msg="Bundle submission failed, will retry",
                    )
                case _:
                    # This should never happen, but we log it and hope to recover later? Not sure what else to do.
                    log_structured(
                        logger.info,
                        _task_id(e),
                        index=i,
                        pov_id=e.pov_id,
                        patch_id=e.patch_id,
                        msg=f"Unknown bundle status: {status}",
                    )
        else:
            e.bundle_id = bundle_id
            e.state = SubmissionEntry.SUBMIT_MATCHING_SARIF
            self._persist(self.redis, i, e)
            log_structured(
                logger.info,
                _task_id(e),
                index=i,
                pov_id=e.pov_id,
                patch_id=e.patch_id,
                bundle_id=bundle_id,
                state_change=("SUBMIT_BUNDLE", "SUBMIT_MATCHING_SARIF"),
                msg="Bundle submitted successfully",
            )

    def _submit_matching_sarif(self, i: int, e: SubmissionEntry) -> None:
        """
        Look for and submit a matching SARIF assessment if one exists.

        Finds SARIF reports that match our vulnerability and submits an assessment.

        Possible state transitions:
        - SUBMIT_MATCHING_SARIF → SUBMIT_BUNDLE_PATCH: If matching SARIF submission succeeded
        - SUBMIT_MATCHING_SARIF → STOP: If submission failed or deadline exceeded

        Args:
            i: Index of the submission entry
            e: SubmissionEntry to process
        """
        _sarif_list = self.sarif_store.get_by_task_id(_task_id(e))
        # TODO: Scan SARIFs to find a match.
        # TODO: Ensure once a SARIF is paired with a vulnerability, it is not paired with another vulnerability.
        matching_sarif_id = None
        if not matching_sarif_id:
            return

        success, status = self.competition_api.submit_matching_sarif(_task_id(e), matching_sarif_id)
        if success:
            e.sarif_id = matching_sarif_id
            e.state = SubmissionEntry.SUBMIT_BUNDLE_PATCH
            self._persist(self.redis, i, e)
            log_structured(
                logger.info,
                _task_id(e),
                index=i,
                pov_id=e.pov_id,
                patch_id=e.patch_id,
                bundle_id=e.bundle_id,
                state_change=("SUBMIT_MATCHING_SARIF", "SUBMIT_BUNDLE_PATCH"),
                msg="Matching SARIF submitted successfully",
            )
        else:
            match status:
                case TypesSubmissionStatus.FAILED | TypesSubmissionStatus.DEADLINE_EXCEEDED:
                    e.state = SubmissionEntry.STOP
                    self._persist(self.redis, i, e)
                    log_structured(
                        logger.info,
                        _task_id(e),
                        index=i,
                        pov_id=e.pov_id,
                        patch_id=e.patch_id,
                        bundle_id=e.bundle_id,
                        state_change=("SUBMIT_MATCHING_SARIF", "STOP"),
                        msg=f"Matching SARIF submission failed ({status}), not much else to do but stop.",
                    )
                case _:
                    log_structured(
                        logger.info,
                        _task_id(e),
                        index=i,
                        pov_id=e.pov_id,
                        patch_id=e.patch_id,
                        bundle_id=e.bundle_id,
                        msg=f"Submitting matching SARIF failed ({status}), will retry.",
                    )

    def _submit_bundle_patch(self, i: int, e: SubmissionEntry) -> None:
        """
        Submit a bundle patch with associated SARIF.

        Final step in the submission process that combines bundle and SARIF assessment.

        Possible state transitions:
        - SUBMIT_BUNDLE_PATCH → STOP: Whether submission succeeds or fails

        Args:
            i: Index of the submission entry
            e: SubmissionEntry to process
        """
        success, status = self.competition_api.submit_bundle_patch(
            _task_id(e), e.bundle_id, e.pov_id, e.patch_id, e.sarif_id
        )
        if success:
            e.state = SubmissionEntry.STOP
            self._persist(self.redis, i, e)
            log_structured(
                logger.info,
                _task_id(e),
                index=i,
                pov_id=e.pov_id,
                patch_id=e.patch_id,
                bundle_id=e.bundle_id,
                sarif_id=e.sarif_id,
                state_change=("SUBMIT_BUNDLE_PATCH", "STOP"),
                msg="Bundle patch submitted successfully. No more work to be done. Will stop.",
            )
        else:
            match status:
                case TypesSubmissionStatus.FAILED | TypesSubmissionStatus.DEADLINE_EXCEEDED:
                    e.state = SubmissionEntry.STOP
                    self._persist(self.redis, i, e)
                    log_structured(
                        logger.info,
                        _task_id(e),
                        index=i,
                        pov_id=e.pov_id,
                        patch_id=e.patch_id,
                        bundle_id=e.bundle_id,
                        sarif_id=e.sarif_id,
                        state_change=("SUBMIT_BUNDLE_PATCH", "STOP"),
                        msg=f"Bundle patch submission failed ({status}), not much else to do but stop.",
                    )
                case _:
                    log_structured(
                        logger.info,
                        _task_id(e),
                        index=i,
                        pov_id=e.pov_id,
                        patch_id=e.patch_id,
                        bundle_id=e.bundle_id,
                        sarif_id=e.sarif_id,
                        msg=f"Submitting bundle patch failed ({status}), will retry.",
                    )

    def process_cycle(self):
        """
        Process all active submissions through their state machine.

        Iterates through all entries and executes the appropriate state handler
        based on each entry's current state. This method is the main driver for
        the state-based submission workflow.
        """
        for i, e in self._enumerate_submissions():
            try:
                match e.state:
                    case SubmissionEntry.SUBMIT_PATCH_REQUEST:
                        self._submit_patch_request(i, e)
                    case SubmissionEntry.WAIT_POV_PASS:
                        self._wait_pov_pass(i, e)
                    case SubmissionEntry.SUBMIT_PATCH:
                        self._submit_patch(i, e)
                    case SubmissionEntry.WAIT_PATCH_PASS:
                        self._wait_patch_pass(i, e)
                    case SubmissionEntry.SUBMIT_BUNDLE:
                        self._submit_bundle(i, e)
                    case SubmissionEntry.SUBMIT_MATCHING_SARIF:
                        self._submit_matching_sarif(i, e)
                    case SubmissionEntry.SUBMIT_BUNDLE_PATCH:
                        self._submit_bundle_patch(i, e)
                    case SubmissionEntry.STOP:
                        continue
                    case _:
                        logger.error(f"[{i}: {_task_id(e)}] Unknown submission state: {e.state}")
            except Exception as err:
                logger.error(f"[{i}: {_task_id(e)}] Error processing submission: {err}")
                # NOTE: The question is if we should raise at some point. Worst case we are stuck in a error-condition
                # that can only be fixed by a restart of the scheduler. However, we don't know that. If we raise, we risk
                # the scheduler only attempting the first vulnerability and the rest of the cycle being skipped. This could
                # lead to a situation where we don't attempt any submissions. For now, we will just log the error and continue.
