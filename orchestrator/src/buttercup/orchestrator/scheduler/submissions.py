from dataclasses import field, dataclass
from functools import lru_cache
import logging
import base64
import uuid
from redis import Redis
from typing import Iterator, List, Set, Tuple
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode
import buttercup.common.node_local as node_local
from pathlib import Path
from buttercup.common.queues import ReliableQueue, QueueFactory, QueueNames
from buttercup.common.sets import PoVReproduceStatus
from buttercup.common.datastructures.msg_pb2 import (
    TracedCrash,
    ConfirmedVulnerability,
    SubmissionEntry,
    Patch,
    SubmissionEntryPatch,
    BuildRequest,
    BuildType,
    BuildOutput,
    POVReproduceRequest,
    POVReproduceResponse,
)
from buttercup.common.sarif_store import SARIFStore
from buttercup.common.task_registry import TaskRegistry
from buttercup.common.telemetry import set_crs_attributes, CRSActionCategory

from buttercup.orchestrator.scheduler.sarif_matcher import match
from buttercup.orchestrator.competition_api_client.models.types_architecture import TypesArchitecture
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
from buttercup.common.challenge_task import ChallengeTask
from buttercup.common.project_yaml import ProjectYaml
from buttercup.common.stack_parsing import get_crash_data, get_inst_key
from buttercup.common.clusterfuzz_parser.crash_comparer import CrashComparer

logger = logging.getLogger(__name__)


def _task_id(e: SubmissionEntry | TracedCrash) -> str:
    """Get the task_id from the SubmissionEntry or TracedCrash."""
    if isinstance(e, TracedCrash):
        return e.crash.target.task_id
    elif isinstance(e, SubmissionEntry):
        return e.crashes[0].crash.target.task_id
    else:
        raise ValueError(f"Unknown submission entry type: {type(e)}")


def log_entry(
    e: SubmissionEntry,
    msg: str = "",
    i: int | None = None,
    old_state: int | None = None,
    fn: logging.Logger = logger.info,
):
    """Log a structured message for easy grepping and filtering."""
    task_id = e.crashes[0].crash.target.task_id
    idx_msg = f"{i}:" if i is not None else ""

    log_msg = f"[{idx_msg}:{task_id}]"

    curr_state = SubmissionEntry.SubmissionState.Name(e.state)
    if old_state:
        old_state_name = SubmissionEntry.SubmissionState.Name(old_state)
        log_msg += f" {old_state_name} -> {curr_state}"
    else:
        log_msg += f" {curr_state}"

    if e.pov_id:
        log_msg += f" pov_id={e.pov_id}"
    if e.competition_patch_id:
        log_msg += f" competition_patch_id={e.competition_patch_id}"
    if e.bundle_id:
        log_msg += f" bundle_id={e.bundle_id}"
    if e.patch_idx:
        log_msg += f" patch_idx={e.patch_idx}"
    if e.sarif_id:
        log_msg += f" sarif_id={e.sarif_id}"

    if msg:
        log_msg += f" {msg}"

    fn(log_msg)


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
                architecture=TypesArchitecture.ArchitectureX8664,
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
                if response.status not in [
                    TypesSubmissionStatus.SubmissionStatusAccepted,
                    TypesSubmissionStatus.SubmissionStatusPassed,
                ]:
                    logger.error(
                        f"[{crash.crash.target.task_id}] POV submission rejected (status: {response.status}) for harness: {crash.crash.harness_name}"
                    )
                    span.set_status(Status(StatusCode.ERROR))
                    return None, response.status

                span.set_status(Status(StatusCode.OK))
                return response.pov_id, response.status
        except Exception as e:
            logger.error(f"[{crash.crash.target.task_id}] Failed to submit vulnerability: {e}")
            return None, TypesSubmissionStatus.SubmissionStatusErrored

    def get_pov_status(self, task_id: str, pov_id: str) -> TypesSubmissionStatus:
        """
        Get vulnerability submission status.

        Args:
            task_id: Task ID associated with the vulnerability
            pov_id: POV ID from submit_vulnerability

        Returns:
            TypesSubmissionStatus: Current status (SubmissionStatusAccepted, SubmissionStatusPassed, SubmissionStatusFailed, SubmissionStatusErrored, SubmissionStatusDeadlineExceeded)
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
            if response.status not in [
                TypesSubmissionStatus.SubmissionStatusAccepted,
                TypesSubmissionStatus.SubmissionStatusPassed,
            ]:
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
            TypesSubmissionStatus: Current status (SubmissionStatusAccepted, SubmissionStatusPassed, SubmissionStatusFailed, SubmissionStatusErrored, SubmissionStatusDeadlineExceeded)
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
            if response.status not in [
                TypesSubmissionStatus.SubmissionStatusAccepted,
                TypesSubmissionStatus.SubmissionStatusPassed,
            ]:
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
        response = BundleApi(api_client=self.api_client).v1_task_task_id_bundle_bundle_id_patch(
            task_id=task_id, bundle_id=bundle_id, payload=submission
        )
        logger.debug(f"[{task_id}] Bundle patch submission response: {response}")
        if response.status not in [
            TypesSubmissionStatus.SubmissionStatusAccepted,
            TypesSubmissionStatus.SubmissionStatusPassed,
        ]:
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
            assessment=TypesAssessment.AssessmentCorrect,
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
            if response.status not in [
                TypesSubmissionStatus.SubmissionStatusAccepted,
                TypesSubmissionStatus.SubmissionStatusPassed,
            ]:
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
       - V_PATCH_REQUESTED → V_INCONCLUSIVE: Competition API reports that the vulnerability is inconclusive, mark it as V_PASSED (it is going to be reviewed manually)
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
       - P_ACCEPTED -> P_INCONCLUSIVE: Competition API reports that the patch is inconclusive, mark it as P_FAILED and move to next patch
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
    MATCHED_SARIFS = "matched_sarifs"

    redis: Redis
    competition_api: CompetitionAPI
    task_registry: TaskRegistry
    tasks_storage_dir: Path
    patch_submission_retry_limit: int = 60
    patch_requests_per_vulnerability: int = 1
    entries: List[SubmissionEntry] = field(init=False)
    sarif_store: SARIFStore = field(init=False)
    matched_sarifs: Set[str] = field(default_factory=set)
    build_requests_queue: ReliableQueue[BuildRequest] = field(init=False)
    pov_reproduce_status: PoVReproduceStatus = field(init=False)

    def __post_init__(self):
        logger.info(
            f"Initializing Submissions, patch_submission_retry_limit={self.patch_submission_retry_limit}, patch_requests_per_vulnerability={self.patch_requests_per_vulnerability}"
        )
        self.entries = self._get_stored_submissions()
        self.sarif_store = SARIFStore(self.redis)
        self.matched_sarifs = self._get_matched_sarifs(self.redis)
        queue_factory = QueueFactory(self.redis)
        self.build_requests_queue = queue_factory.create(QueueNames.BUILD, block_time=None)
        self.pov_reproduce_status = PoVReproduceStatus(self.redis)

    def _insert_matched_sarif(self, redis: Redis, sarif_id: str):
        """Insert a matched SARIF ID into Redis."""
        self.matched_sarifs.add(sarif_id)
        redis.sadd(self.MATCHED_SARIFS, sarif_id)

    def _get_matched_sarifs(self, redis: Redis) -> Set[str]:
        """Get all matched SARIF IDs from Redis."""
        return set(redis.smembers(self.MATCHED_SARIFS))

    def _get_sarif_candidates(self, task_id: str) -> List[TracedCrash]:
        """Get all SARIFs for a task that are not matched to a vulnerability."""
        return [
            sarif for sarif in self.sarif_store.get_by_task_id(task_id) if sarif.sarif_id not in self.matched_sarifs
        ]

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

    def _stop(self, i: int, e: SubmissionEntry, msg: str):
        """Stop a SubmissionEntry from further processing."""
        old_state = e.state
        e.state = SubmissionEntry.STOP
        self._persist(self.redis, i, e)
        log_entry(e, msg, i, old_state=old_state)

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

        crash_data = get_crash_data(crash.crash.stacktrace)
        inst_key = get_inst_key(crash.crash.stacktrace)
        task_id = _task_id(crash)

        # Check if the crash is a variant of an existing submission
        similar_submissions = 0
        for i, e in self._enumerate_submissions():
            # Only check submissions for the same task
            if _task_id(e) != task_id:
                continue

            for existing_crash in e.crashes:
                submission_crash_data = get_crash_data(existing_crash.crash.stacktrace)
                submission_inst_key = get_inst_key(existing_crash.crash.stacktrace)

                cf_comparator = CrashComparer(crash_data, submission_crash_data)
                instkey_comparator = CrashComparer(inst_key, submission_inst_key)

                if cf_comparator.is_similar() or instkey_comparator.is_similar():
                    log_entry(
                        e,
                        f"Incoming PoV crash_data: {crash_data}, inst_key: {inst_key}, existing crash_data: {submission_crash_data}, existing inst_key: {submission_inst_key} are duplicates. ",
                        i,
                        fn=logger.debug,
                    )

                    e.crashes.append(crash)
                    log_entry(
                        e,
                        f"Adding a duplicate PoV based on similarity check. (n={len(e.crashes)})",
                        i,
                        fn=logger.info,
                    )

                    self._persist(self.redis, i, e)

                    similar_submissions += 1
                    # No need to check other crashes in this submission
                    break

        if similar_submissions > 1:
            logger.error(
                f"Found {similar_submissions} similar submissions. This is a indication that our deduplication logic isn't good enough."
            )

        if similar_submissions > 0:
            # No need to submit the crash, we already have a similar submission
            return True

        pov_id, status = self.competition_api.submit_pov(crash)
        if not pov_id:
            logger.error(f"[{_task_id(crash)}] Failed to submit vulnerability. Competition API returned {status}.")
            logger.debug(f"CrashInfo: {crash}")

            # If the API returned ERRORED, we want to retry.
            stop = status != TypesSubmissionStatus.SubmissionStatusErrored

            if stop:
                logger.info(f"Competition API returned {status}, will not retry.")
                logger.debug(f"CrashInfo: {crash}")
            return stop

        e = SubmissionEntry()
        e.crashes.append(crash)
        e.pov_id = pov_id
        e.state = SubmissionEntry.SUBMIT_PATCH_REQUEST

        # Persist to Redis
        length = self._push(e)
        index = length - 1

        # If this fails, we have a bug.  Let it crash. Reloading the Submissions object will "fix it".
        assert index == len(self.entries)

        # Keep the entries list in sync
        self.entries.append(e)
        log_entry(e, i=index)
        return True

    def _request_patched_builds(self, task_id: str, patch: SubmissionEntryPatch) -> None:
        """Request patched builds for a patch"""
        task = ChallengeTask(read_only_task_dir=self.tasks_storage_dir / task_id)

        project_yaml = ProjectYaml(task, task.task_meta.project_name)
        engine = "libfuzzer"
        if engine not in project_yaml.fuzzing_engines:
            engine = project_yaml.fuzzing_engines[0]

        sanitizers = project_yaml.sanitizers

        for san in sanitizers:
            build_req = BuildRequest(
                engine=engine,
                task_dir=str(task.task_dir),
                task_id=task_id,
                build_type=BuildType.PATCH,
                sanitizer=san,
                apply_diff=True,
                patch=patch.patch,
                internal_patch_id=patch.internal_patch_id,
            )
            self.build_requests_queue.push(build_req)
            logger.info(
                f"[{task_id}] Pushed build request {BuildType.Name(build_req.build_type)} | {build_req.sanitizer} | {build_req.engine} | {build_req.apply_diff} | {build_req.internal_patch_id}"
            )

    def record_patched_build(self, build_output: BuildOutput) -> bool:
        """Record a patched build"""

        key = build_output.internal_patch_id
        for i, e in self._enumerate_submissions():
            for patch in e.patches:
                if patch.internal_patch_id == key:
                    # Found the patch, now record the build output
                    # unless there are already build outputs for this patch/sanitizer/engine/build_type
                    if any(
                        bo.sanitizer == build_output.sanitizer
                        and bo.engine == build_output.engine
                        and bo.build_type == build_output.build_type
                        for bo in patch.build_outputs
                    ):
                        logger.warning(
                            f"Build output {build_output.internal_patch_id} already recorded for patch {patch.internal_patch_id}. Will discard."
                        )
                        # Still acknowledge the build output, but don't add it to the patch
                        return True
                    patch.build_outputs.append(build_output)

                    # Persist the entry to Redis
                    self._persist(self.redis, i, e)
                    log_entry(e, i=i, msg="Patched build recorded")
                    return True

        # If we get here, the build output is not associated with any patch,
        # it is possible that the task was cancelled or expired.
        logger.error(
            f"Build output {build_output.internal_patch_id} not found in any patch (task expired/cancelled?). Will discard."
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
            patch: The patch to record, containing internal_patch_id and task_id

        Returns:
            True if the patch was successfully recorded, False if the submission doesn't exist
        """
        key = patch.internal_patch_id
        entry_patch = None
        for i, e in self._enumerate_submissions():
            for entry_patch_tracker in e.patches:
                if entry_patch_tracker.internal_patch_id == key:
                    if entry_patch_tracker.patch:
                        # There is already a patch here, this is likely the result of the request timing out
                        # in the patcher but multiple patchers still completed the patch.
                        # In this case, we just generate a new patch tracker and add it.
                        new_patch_tracker = self._new_patch_tracker()
                        new_patch_tracker.patch = patch.patch
                        e.patches.append(new_patch_tracker)
                        entry_patch = e.patches[-1]
                    else:
                        # There is no patch here, this is the first time we are recording a patch for this patch tracker.
                        entry_patch_tracker.patch = patch.patch
                        entry_patch = entry_patch_tracker

                    # We have a patch now, persist the entry and double check if it will ever be used
                    self._persist(self.redis, i, e)
                    task_id = _task_id(e)
                    self._request_patched_builds(task_id, entry_patch)

                    log_entry(e, i=i, msg="Patch added")
                    return True

        logger.warning(
            f"Internal patch id {key} wasn't found in any active task. The original task might be cancelled or has expired. Will discard."
        )
        # Still acknowledge the patch, don't have much use for this message being showed repeatedly
        return True

    def _pov_reproduce_status_request(self, e: SubmissionEntry, patch_idx: int) -> List[POVReproduceResponse | None]:
        patch = e.patches[patch_idx]
        task_id = _task_id(e)
        result = []
        for crash in e.crashes:
            request = POVReproduceRequest()
            request.task_id = task_id
            request.internal_patch_id = patch.internal_patch_id
            request.harness_name = crash.crash.harness_name
            request.sanitizer = crash.crash.target.sanitizer
            request.pov_path = crash.crash.crash_input_path

            status = self.pov_reproduce_status.request_status(request)

            result.append(status)

        return result

    def _check_all_povs_are_mitigated(self, e: SubmissionEntry, patch_idx: int) -> bool | None:
        """
        Check if all POVs for a confirmed vulnerability are mitigated.

        Returns None if anyone is pending, returns True if all mitigated, returns False if any are failing.
        """
        logger.debug(f"Checking if all POVs for patch {patch_idx} are mitigated")
        statuses = self._pov_reproduce_status_request(e, patch_idx)
        logger.debug(f"Statuses: {statuses}")

        # If any patch is failing, we need to create a new patch.
        any_failing = any(status is not None and status.did_crash for status in statuses)
        if any_failing:
            return False

        # TODO: Add a parameter to ignore any "None" responses to be used when approaching the end of the task window
        # If any patch is pending, we need to wait for it.
        any_pending = any(status is None for status in statuses)
        if any_pending:
            return None

        return True

    @staticmethod
    def _new_patch_tracker() -> SubmissionEntryPatch:
        """Create a new patch tracker for a submission entry and assign it a new unique id."""
        return SubmissionEntryPatch(internal_patch_id=str(uuid.uuid4()))

    def _generate_patch_request(
        self, i: int, e: SubmissionEntry, patch_tracker: SubmissionEntryPatch
    ) -> ConfirmedVulnerability:
        """Create ConfirmedVulnerability from submission entry with all crashes and a new unique id."""
        confirmed = ConfirmedVulnerability()
        for crash in e.crashes:
            confirmed.crashes.append(crash)
        confirmed.internal_patch_id = patch_tracker.internal_patch_id

        return confirmed

    def _enqueue_patch_requests(
        self, confirmed_vulnerability: ConfirmedVulnerability, q: ReliableQueue[ConfirmedVulnerability] | None
    ) -> None:
        """Push N copies of vulnerability to queue for parallel patch generation."""
        if q is None:
            q = QueueFactory(self.redis).create(QueueNames.CONFIRMED_VULNERABILITIES, block_time=None)

        for _ in range(self.patch_requests_per_vulnerability):
            q.push(confirmed_vulnerability)

    def _persist_and_enqueue_patch_request_transaction(self, i, e, old_state: int | None = None):
        """
        Request patch generation for a confirmed vulnerability.

        Pushes the vulnerability to the confirmed_vulnerabilities_queue and persists the submission entry, all in a single transaction.

        Args:
            i: Index of the submission entry
            e: SubmissionEntry to process
        """
        log_entry(e, i=i, msg="Submitting patch request")

        patch_tracker = self._new_patch_tracker()

        confirmed = self._generate_patch_request(i, e, patch_tracker)
        e.patches.append(patch_tracker)

        with self.redis.pipeline() as pipe:
            q = QueueFactory(pipe).create(QueueNames.CONFIRMED_VULNERABILITIES, block_time=None)
            self._enqueue_patch_requests(confirmed_vulnerability=confirmed, q=q)
            self._persist(pipe, i, e)
            pipe.execute()

        log_entry(e, i=i, msg="Patch request submitted", old_state=old_state)

    def _attempt_next_patch(self, i, e):
        """
        Attempts to use any additional patch available. If none, requests a new one.

        This will also persist the SubmissionEntry
        """
        # NOTE: Don't advance patch index before checking if we have more patches.
        if _have_more_patches(e):
            _advance_patch_idx(e)
            self._persist(self.redis, i, e)
        else:
            _advance_patch_idx(e)
            self._persist_and_enqueue_patch_request_transaction(i, e)

    def _submit_patch_request(self, i, e):
        """
        Request patch generation for a confirmed vulnerability.

        Pushes the vulnerability to the confirmed_vulnerabilities_queue
        and updates the state to WAIT_POV_PASS.

        Args:
            i: Index of the submission entry
            e: SubmissionEntry to process
        """
        old_state = e.state
        e.state = SubmissionEntry.WAIT_POV_PASS
        self._persist_and_enqueue_patch_request_transaction(i, e, old_state=old_state)

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
            case (
                TypesSubmissionStatus.SubmissionStatusFailed
                | TypesSubmissionStatus.SubmissionStatusDeadlineExceeded
                | TypesSubmissionStatus.SubmissionStatusInconclusive
            ):
                self._stop(i, e, f"POV failed (status={status}), stopping")

            case TypesSubmissionStatus.SubmissionStatusPassed:
                self.task_registry.mark_successful(_task_id(e))
                old_state = e.state
                e.state = SubmissionEntry.SUBMIT_PATCH
                self._persist(self.redis, i, e)
                log_entry(e, i=i, msg="POV passed, ready to submit patch when the patch is ready", old_state=old_state)
            case TypesSubmissionStatus.SubmissionStatusErrored:
                self.task_registry.mark_errored(_task_id(e))
                log_entry(e, i=i, msg="POV errored, will resubmit")

                # NOTE: Currently only submitting the first crash. This might need to be changed in the future.
                pov_id, status = self.competition_api.submit_pov(e.crashes[0])
                if not pov_id:
                    log_entry(
                        e,
                        i=i,
                        msg=f"Failed to submit vulnerability. Competition API returned {status}.",
                        fn=logger.error,
                    )

                    # If the API returned ERRORED, we want to retry.
                    if status != TypesSubmissionStatus.SubmissionStatusErrored:
                        self._stop(i, e, f"POV failed (status={status}), stopping")
                else:
                    e.pov_id = pov_id
                    self._persist(self.redis, i, e)
                    log_entry(e, i=i, msg="POV resubmitted, waiting for pass")

            case TypesSubmissionStatus.SubmissionStatusAccepted:
                pass
            case _:
                log_entry(e, i=i, msg=f"Unexpected POV status: {status}", fn=logger.error)

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

        status = self._check_all_povs_are_mitigated(e, e.patch_idx)
        if status is None:
            # We haven't checked all POVs for this patch yet, so we can't submit the patch
            log_entry(e, i=i, msg="Pending POV check, will not submit patch yet.", fn=logger.debug)
            return

        if status is False:
            # All POVs for this patch are not mitigated, so we can't submit the patch
            log_entry(e, i=i, msg="Patch does not mitigate all POVs, will not submit patch")
            self._attempt_next_patch(i, e)
            return

        # All good, all PoVs for this patch are mitigated.

        have_more_patches = _have_more_patches(e)
        patch = e.patches[e.patch_idx].patch

        log_entry(e, i=i, msg="Submitting patch")
        logger.debug(f"patch: {patch[:512]}...")

        patch_id, status = self.competition_api.submit_patch(_task_id(e), patch)

        if patch_id:
            old_state = e.state
            e.competition_patch_id = patch_id
            e.patch_submission_attempt += 1
            e.patches[e.patch_idx].competition_patch_id = patch_id
            e.state = SubmissionEntry.WAIT_PATCH_PASS
            self._persist(self.redis, i, e)
            log_entry(e, i=i, msg="Patch accepted", old_state=old_state)
        else:
            match status:
                case TypesSubmissionStatus.SubmissionStatusDeadlineExceeded:
                    self._stop(i, e, "Patch submission deadline exceeded, stopping")
                case TypesSubmissionStatus.SubmissionStatusFailed | TypesSubmissionStatus.SubmissionStatusInconclusive:
                    # The patch failed for some reason. Try generating a new patch
                    self._attempt_next_patch(i, e)
                    log_entry(e, i=i, msg=f"Patch submission failed ({status}), will not attempt this patch again.")
                case TypesSubmissionStatus.SubmissionStatusErrored:
                    if have_more_patches and e.patch_submission_attempt >= self.patch_submission_retry_limit:
                        self._attempt_next_patch(i, e)
                        log_entry(
                            e, i=i, msg=f"Patch submission errored too many times ({status}), moved on to next patch."
                        )
                    else:
                        # Keep trying the same patch (if we don't have more patches or we haven't tried too many times)
                        e.patch_submission_attempt += 1
                        self._persist(self.redis, i, e)
                        log_entry(
                            e,
                            i=i,
                            msg=f"Patch submission failed ({status}), will attempt this patch again (attempt={e.patch_submission_attempt}).",
                        )
                case _:
                    log_entry(e, i=i, msg=f"Unexpected patch status: {status}", fn=logger.error)

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
        status = self.competition_api.get_patch_status(_task_id(e), e.competition_patch_id)
        match status:
            case TypesSubmissionStatus.SubmissionStatusAccepted:
                return  # No change.
            case TypesSubmissionStatus.SubmissionStatusDeadlineExceeded:
                self._stop(i, e, "Patch submission deadline exceeded, stopping")
            case TypesSubmissionStatus.SubmissionStatusFailed | TypesSubmissionStatus.SubmissionStatusInconclusive:
                old_state = e.state
                e.state = SubmissionEntry.SUBMIT_PATCH
                self._attempt_next_patch(i, e)
                log_entry(
                    e,
                    i=i,
                    msg=f"Patch submission failed ({status}), will not attempt this patch again, moving on to next patch.",
                    old_state=old_state,
                )
            case TypesSubmissionStatus.SubmissionStatusErrored:
                self.task_registry.mark_errored(_task_id(e))
                old_state = e.state
                e.state = SubmissionEntry.SUBMIT_PATCH
                self._persist(self.redis, i, e)
                log_entry(
                    e,
                    i=i,
                    msg=f"Patch submission errored ({status}), will attempt this patch again.",
                    old_state=old_state,
                )
            case TypesSubmissionStatus.SubmissionStatusPassed:
                self.task_registry.mark_successful(_task_id(e))
                old_state = e.state
                e.state = SubmissionEntry.SUBMIT_BUNDLE
                self._persist(self.redis, i, e)
                log_entry(e, i=i, msg="Patch passed, submitting bundle", old_state=old_state)
            case _:
                log_entry(e, i=i, msg=f"Unexpected patch status: {status}", fn=logger.error)

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
        bundle_id, status = self.competition_api.submit_bundle(_task_id(e), e.pov_id, e.competition_patch_id)
        if not bundle_id:
            match status:
                case (
                    TypesSubmissionStatus.SubmissionStatusFailed
                    | TypesSubmissionStatus.SubmissionStatusDeadlineExceeded
                    | TypesSubmissionStatus.SubmissionStatusInconclusive
                ):
                    self._stop(i, e, f"Bundle submission failed ({status}), not much else to do but stop.")
                case TypesSubmissionStatus.SubmissionStatusErrored:
                    log_entry(e, i=i, msg="Bundle submission failed, will retry")
                case _:
                    # This should never happen, but we log it and hope to recover later? Not sure what else to do.
                    log_entry(e, i=i, msg=f"Unknown bundle status: {status}", fn=logger.info)
        else:
            old_state = e.state
            e.bundle_id = bundle_id
            e.state = SubmissionEntry.SUBMIT_MATCHING_SARIF
            self._persist(self.redis, i, e)
            log_entry(e, i=i, msg="Bundle submitted successfully", old_state=old_state)

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
        sarif_list = self._get_sarif_candidates(_task_id(e))

        matching_sarif_id = None
        for sarif in sarif_list:
            for crash in e.crashes:
                match_result = match(sarif, crash)
                if match_result:
                    logger.debug(
                        f"[{i}:{_task_id(e)}] Found matching SARIF: {sarif.sarif_id}: {match_result}. Will check if it's a good enough match."
                    )
                    # We require a match on lines to be confident that the SARIF is a good match.
                    if not match_result.matches_lines:
                        continue
                    logger.info(f"[{i}:{_task_id(e)}] Found matching SARIF: {sarif.sarif_id}: {match_result}")
                    matching_sarif_id = sarif.sarif_id
                    break
        if not matching_sarif_id:
            return

        success, status = self.competition_api.submit_matching_sarif(_task_id(e), matching_sarif_id)
        if success:
            old_state = e.state
            with self.redis.pipeline() as pipe:
                e.sarif_id = matching_sarif_id
                e.state = SubmissionEntry.SUBMIT_BUNDLE_PATCH
                self._persist(pipe, i, e)
                self._insert_matched_sarif(pipe, matching_sarif_id)
                pipe.execute()
            log_entry(e, i=i, msg="Matching SARIF submitted successfully", old_state=old_state)
        else:
            match status:
                case (
                    TypesSubmissionStatus.SubmissionStatusFailed
                    | TypesSubmissionStatus.SubmissionStatusDeadlineExceeded
                    | TypesSubmissionStatus.SubmissionStatusInconclusive
                ):
                    self._stop(i, e, f"Matching SARIF submission failed ({status}), not much else to do but stop.")
                case _:
                    log_entry(e, i=i, msg=f"Submitting matching SARIF failed ({status}), will retry.")

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
        success, status = self.competition_api.patch_bundle(
            _task_id(e), e.bundle_id, e.pov_id, e.competition_patch_id, e.sarif_id
        )
        if success:
            self._stop(i, e, "Bundle patch submitted successfully. No more work to be done. Will stop.")
        else:
            match status:
                case (
                    TypesSubmissionStatus.SubmissionStatusFailed
                    | TypesSubmissionStatus.SubmissionStatusDeadlineExceeded
                    | TypesSubmissionStatus.SubmissionStatusInconclusive
                ):
                    self._stop(i, e, f"Bundle patch submission failed ({status}), not much else to do but stop.")
                case _:
                    log_entry(e, i=i, msg=f"Submitting bundle patch failed ({status}), will retry.")

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
