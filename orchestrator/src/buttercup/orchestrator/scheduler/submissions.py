import base64
import logging
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from buttercup.common import node_local
from buttercup.common.challenge_task import ChallengeTask
from buttercup.common.clusterfuzz_parser.crash_comparer import CrashComparer
from buttercup.common.constants import ARCHITECTURE
from buttercup.common.datastructures.msg_pb2 import (
    BuildOutput,
    BuildRequest,
    BuildType,
    Bundle,
    ConfirmedVulnerability,
    CrashWithId,
    Patch,
    POVReproduceRequest,
    POVReproduceResponse,
    SubmissionEntry,
    SubmissionEntryPatch,
    SubmissionResult,
    TracedCrash,
)
from buttercup.common.project_yaml import ProjectYaml
from buttercup.common.queues import QueueFactory, QueueNames, ReliableQueue
from buttercup.common.sarif_store import SARIFBroadcastDetail, SARIFStore
from buttercup.common.sets import PoVReproduceStatus
from buttercup.common.stack_parsing import get_crash_data, get_inst_key
from buttercup.common.task_registry import TaskRegistry
from buttercup.common.telemetry import CRSActionCategory, set_crs_attributes
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode
from redis import Redis

from buttercup.orchestrator.competition_api_client.api import BroadcastSarifAssessmentApi, BundleApi, PatchApi, PovApi
from buttercup.orchestrator.competition_api_client.api_client import ApiClient
from buttercup.orchestrator.competition_api_client.models.types_architecture import TypesArchitecture
from buttercup.orchestrator.competition_api_client.models.types_assessment import TypesAssessment
from buttercup.orchestrator.competition_api_client.models.types_bundle_submission import TypesBundleSubmission
from buttercup.orchestrator.competition_api_client.models.types_patch_submission import TypesPatchSubmission
from buttercup.orchestrator.competition_api_client.models.types_pov_submission import TypesPOVSubmission
from buttercup.orchestrator.competition_api_client.models.types_sarif_assessment_submission import (
    TypesSarifAssessmentSubmission,
)
from buttercup.orchestrator.competition_api_client.models.types_submission_status import TypesSubmissionStatus
from buttercup.orchestrator.scheduler.sarif_matcher import match

logger = logging.getLogger(__name__)


def _map_submission_status_to_result(status: TypesSubmissionStatus) -> SubmissionResult:
    """Map TypesSubmissionStatus to SubmissionResult enum."""
    mapping = {
        TypesSubmissionStatus.SubmissionStatusAccepted: SubmissionResult.ACCEPTED,
        TypesSubmissionStatus.SubmissionStatusPassed: SubmissionResult.PASSED,
        TypesSubmissionStatus.SubmissionStatusFailed: SubmissionResult.FAILED,
        TypesSubmissionStatus.SubmissionStatusDeadlineExceeded: SubmissionResult.DEADLINE_EXCEEDED,
        TypesSubmissionStatus.SubmissionStatusErrored: SubmissionResult.ERRORED,
        TypesSubmissionStatus.SubmissionStatusInconclusive: SubmissionResult.INCONCLUSIVE,
    }
    return mapping.get(status, SubmissionResult.ERRORED)  # Default to ERRORED for unknown statuses


def _task_id(e: SubmissionEntry | TracedCrash) -> str:
    """Get the task_id from the SubmissionEntry or TracedCrash."""
    if isinstance(e, TracedCrash):
        return e.crash.target.task_id
    if isinstance(e, SubmissionEntry):
        return e.crashes[0].crash.crash.target.task_id
    raise ValueError(f"Unknown submission entry type: {type(e)}")


def log_entry(
    e: SubmissionEntry,
    msg: str = "",
    i: int | None = None,
    fn: Callable[[str], None] = logger.info,
) -> None:
    """Log a structured message for easy grepping and filtering."""
    task_id = _task_id(e)
    idx_msg = f"{i}:" if i is not None else ""

    log_msg = f"[{idx_msg}{task_id}]"

    def _truncate_join(items: list[str], max_length: int = 256) -> str:
        """Join list items with commas, truncating if the result exceeds max_length."""
        joined = ",".join(items)
        if len(joined) <= max_length:
            return joined
        # Truncate and add ellipsis
        return joined[: max_length - 3] + "..."

    competition_pov_ids = [c.competition_pov_id for c in e.crashes if c.competition_pov_id]
    if competition_pov_ids:
        log_msg += f" pov_id={_truncate_join(competition_pov_ids)}"

    if len(e.patches) > 0:
        log_msg += f" patches={len(e.patches)}"

    if e.patch_idx:
        log_msg += f" patch_idx={e.patch_idx}"

    if e.patch_submission_attempts:
        log_msg += f" patch_submission_attempts={e.patch_submission_attempts}"

    competition_patch_ids = [p.competition_patch_id for p in e.patches if p.competition_patch_id]
    if competition_patch_ids:
        log_msg += f" competition_patch_id={_truncate_join(competition_patch_ids)}"

    competition_bundle_ids = [b.bundle_id for b in e.bundles if b.bundle_id]
    if competition_bundle_ids:
        log_msg += f" bundle_id={_truncate_join(competition_bundle_ids)}"

    sarif_ids = [b.competition_sarif_id for b in e.bundles if b.competition_sarif_id]
    if sarif_ids:
        log_msg += f" sarif_id={_truncate_join(sarif_ids)}"

    if msg:
        log_msg += f" {msg}"

    fn(log_msg)


def _advance_patch_idx(e: SubmissionEntry) -> None:
    """Advance the patch index to the next patch."""
    e.patch_idx += 1
    e.patch_submission_attempts = 0


def _increase_submission_attempts(e: SubmissionEntry) -> None:
    """Increase the submission attempts for the current patch."""
    e.patch_submission_attempts += 1


def _current_patch(e: SubmissionEntry) -> SubmissionEntryPatch | None:
    """Get the current patch."""
    if not e.patches:
        return None
    if e.patch_idx >= len(e.patches):
        return None
    return e.patches[e.patch_idx]


def _get_pending_patch_submissions(e: SubmissionEntry) -> list[SubmissionEntryPatch]:
    """Get all pending patch submissions from the submission entry.
    It is considered pending if it has a competition_patch_id and is in the ACCEPTED state.
    """
    return [patch for patch in e.patches if patch.competition_patch_id and patch.result == SubmissionResult.ACCEPTED]


def _get_first_successful_pov(e: SubmissionEntry) -> CrashWithId | None:
    """Get the first successful POV from the submission entry.

    Returns None if no successful POV is found.
    """
    return next(
        (crash for crash in e.crashes if crash.competition_pov_id and crash.result == SubmissionResult.PASSED),
        None,
    )


def _get_pending_pov_submissions(e: SubmissionEntry) -> list[CrashWithId]:
    """Get all pending POVs from the submission entry.
    It is considered pending if the POV is accepted but not yet passed.

    Returns None if no pending POV is found.
    """
    return [crash for crash in e.crashes if crash.competition_pov_id and crash.result == SubmissionResult.ACCEPTED]


def _get_first_successful_pov_id(e: SubmissionEntry) -> str | None:
    """Get the first successful POV ID from the submission entry.

    Returns None if no successful POV is found.
    """
    pov = _get_first_successful_pov(e)
    if pov:
        return pov.competition_pov_id
    return None


def _get_eligible_povs_for_submission(e: SubmissionEntry) -> list[CrashWithId]:
    """Get all POVs that are eligible for submission.

    A POV is eligible for submission if:
    - It doesn't have a competition_pov_id, or
    - It has a competition_pov_id but is in ERRORED state (can be retried)

    Returns:
        List of CrashWithId objects that are eligible for submission

    """
    return [
        crash
        for crash in e.crashes
        if not crash.competition_pov_id or (crash.competition_pov_id and crash.result == SubmissionResult.ERRORED)
    ]


def _find_matching_build_output(patch: SubmissionEntryPatch, build_output: BuildOutput) -> BuildOutput | None:
    """Find the matching build output in the patch."""
    # Found the patch, now locate the placeholder for the build output
    return next(
        (
            bo
            for bo in patch.build_outputs
            if (
                bo.engine == build_output.engine
                and bo.sanitizer == build_output.sanitizer
                and bo.build_type == build_output.build_type
                and bo.apply_diff == build_output.apply_diff
            )
        ),
        None,
    )


class CompetitionAPI:
    """Simplified interface for the competition API.

    Handles submission formatting, error handling, and response parsing for:
    - Vulnerability proofs (POVs)
    - Patches
    - Bundles (vulnerability + patch combinations)

    Each method handles errors and returns results in a consistent format.
    """

    def __init__(self, api_client: ApiClient, task_registry: TaskRegistry) -> None:
        """Initialize with an API client.

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
        task = self.task_registry.get(task_id)
        assert task is not None, f"Task {task_id} not found"
        return dict(task.metadata)

    def submit_pov(self, crash: TracedCrash) -> tuple[str | None, SubmissionResult]:
        """Submit a vulnerability (POV) to the competition API.

        Reads crash input, encodes as base64, and submits with required metadata.

        Args:
            crash: TracedCrash with crash details and metadata

        Returns:
            Tuple[str | None, SubmissionResult]:
                - POV ID if successful, None otherwise
                - Submission status

        """
        try:
            # Read crash input file contents and encode as base64
            with node_local.lopen(Path(crash.crash.crash_input_path), "rb") as f:
                crash_data = base64.b64encode(f.read()).decode()

            # Create submission payload from crash data
            submission = TypesPOVSubmission(
                architecture=TypesArchitecture(ARCHITECTURE),
                engine=crash.crash.target.engine,  # type: ignore[invalid-argument-type]  # protobuf type mismatch
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

                logger.debug(f"[{crash.crash.target.task_id}] Submitting POV for harness: {crash.crash.harness_name}")

                # Submit Pov and get response
                response = PovApi(api_client=self.api_client).v1_task_task_id_pov_post(
                    task_id=crash.crash.target.task_id,
                    payload=submission,
                )
                logger.debug(f"[{crash.crash.target.task_id}] POV submission response: {response}")
                mapped_status = _map_submission_status_to_result(response.status)
                if mapped_status not in [
                    SubmissionResult.ACCEPTED,
                    SubmissionResult.PASSED,
                ]:
                    logger.error(
                        f"[{crash.crash.target.task_id}] POV submission rejected (status: {response.status}) for harness: {crash.crash.harness_name}",  # noqa: E501
                    )
                    span.set_status(Status(StatusCode.ERROR))
                    return None, mapped_status

                span.set_status(Status(StatusCode.OK))
                return response.pov_id, mapped_status
        except Exception as e:
            logger.error(f"[{crash.crash.target.task_id}] Failed to submit vulnerability: {e}")
            return None, SubmissionResult.ERRORED

    def get_pov_status(self, task_id: str, pov_id: str) -> SubmissionResult:
        """Get vulnerability submission status.

        Args:
            task_id: Task ID associated with the vulnerability
            pov_id: POV ID from submit_vulnerability

        Returns:
            SubmissionResult: Current status (ACCEPTED, PASSED, FAILED, ERRORED, DEADLINE_EXCEEDED)

        """
        assert task_id
        assert pov_id

        response = PovApi(api_client=self.api_client).v1_task_task_id_pov_pov_id_get(task_id=task_id, pov_id=pov_id)
        return _map_submission_status_to_result(response.status)

    def submit_patch(self, task_id: str, patch: str) -> tuple[str | None, SubmissionResult]:
        """Submit a patch to the competition API.

        Args:
            task_id: Task ID of the vulnerability being patched
            patch: Patch content string

        Returns:
            Tuple[str | None, SubmissionResult]:
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

            logger.debug(f"[{task_id}] Submitting patch")

            response = PatchApi(api_client=self.api_client).v1_task_task_id_patch_post(
                task_id=task_id,
                payload=submission,
            )
            logger.debug(f"[{task_id}] Patch submission response: {response}")
            mapped_status = _map_submission_status_to_result(response.status)
            if mapped_status not in [
                SubmissionResult.ACCEPTED,
                SubmissionResult.PASSED,
            ]:
                logger.error(f"[{task_id}] Patch submission rejected (status: {response.status}) for harness: {patch}")
                span.set_status(Status(StatusCode.ERROR))
                return (None, mapped_status)

            span.set_status(Status(StatusCode.OK))
            return (response.patch_id, mapped_status)

    def get_patch_status(self, task_id: str, patch_id: str) -> SubmissionResult:
        """Get patch submission status.

        Args:
            task_id: Task ID associated with the patch
            patch_id: Patch ID from submit_patch

        Returns:
            SubmissionResult: Current status (ACCEPTED, PASSED, FAILED, ERRORED, DEADLINE_EXCEEDED)

        """
        assert task_id
        assert patch_id

        response = PatchApi(api_client=self.api_client).v1_task_task_id_patch_patch_id_get(
            task_id=task_id,
            patch_id=patch_id,
        )
        if response.functionality_tests_passing is not None:
            logger.info(
                f"[{task_id}] Patch {patch_id} functionality tests passing: {response.functionality_tests_passing}",
            )
        return _map_submission_status_to_result(response.status)

    def submit_bundle(
        self,
        task_id: str,
        pov_id: str,
        patch_id: str,
        sarif_id: str,
    ) -> tuple[str | None, SubmissionResult]:
        """Submit a bundle (vulnerability + patch).

        Args:
            task_id: Task ID for the submission
            pov_id: POV ID of verified vulnerability
            patch_id: Patch ID of verified patch

        Returns:
            Tuple[str | None, SubmissionResult]:
                - Bundle ID if successful, None otherwise
                - Submission status

        """
        assert task_id
        assert pov_id

        submission = TypesBundleSubmission(
            pov_id=pov_id,
        )
        if sarif_id:
            submission.broadcast_sarif_id = sarif_id
        if patch_id:
            submission.patch_id = patch_id

        # Telemetry
        tracer = trace.get_tracer(__name__)
        with tracer.start_as_current_span("submit_bundle_for_scoring") as span:
            set_crs_attributes(
                span,
                crs_action_category=CRSActionCategory.SCORING_SUBMISSION,
                crs_action_name="submit_bundle_for_scoring",
                task_metadata=self._get_task_metadata(task_id),
            )

            logger.debug(f"[{task_id}] Submitting bundle for harness: {pov_id} {patch_id} {sarif_id}")

            response = BundleApi(api_client=self.api_client).v1_task_task_id_bundle_post(
                task_id=task_id,
                payload=submission,
            )
            logger.debug(f"[{task_id}] Bundle submission response: {response}")
            mapped_status = _map_submission_status_to_result(response.status)
            if mapped_status not in [
                SubmissionResult.ACCEPTED,
                SubmissionResult.PASSED,
            ]:
                logger.error(f"[{task_id}] Bundle submission rejected (status: {response.status})")
                span.set_status(Status(StatusCode.ERROR))
                return (None, mapped_status)

            span.set_status(Status(StatusCode.OK))
            return (response.bundle_id, mapped_status)

    def patch_bundle(
        self,
        task_id: str,
        bundle_id: str,
        pov_id: str,
        patch_id: str,
        sarif_id: str,
    ) -> tuple[bool, SubmissionResult]:
        """Submit a bundle patch with SARIF association.

        Args:
            task_id: Task ID for the submission
            bundle_id: Bundle ID to patch
            pov_id: POV ID of verified vulnerability
            patch_id: Patch ID of verified patch
            sarif_id: SARIF ID to associate with the bundle

        Returns:
            Tuple[bool, SubmissionResult]:
                - True if successful, False otherwise
                - Submission status

        """
        assert task_id
        assert bundle_id
        assert pov_id
        assert patch_id
        assert sarif_id

        submission = TypesBundleSubmission(
            bundle_id=bundle_id,  # type: ignore[unknown-argument]  # stale proto field
            pov_id=pov_id,
            patch_id=patch_id,
            broadcast_sarif_id=sarif_id,
        )
        tracer = trace.get_tracer(__name__)
        with tracer.start_as_current_span("patch_bundle") as span:
            set_crs_attributes(
                span,
                crs_action_category=CRSActionCategory.SCORING_SUBMISSION,
                crs_action_name="patch_bundle",
                task_metadata=self._get_task_metadata(task_id),
            )
            response = BundleApi(api_client=self.api_client).v1_task_task_id_bundle_bundle_id_patch(
                task_id=task_id,
                bundle_id=bundle_id,
                payload=submission,
            )
            logger.debug(f"[{task_id}] Bundle patch submission response: {response}")
            mapped_status = _map_submission_status_to_result(response.status)
            if mapped_status not in [
                SubmissionResult.ACCEPTED,
                SubmissionResult.PASSED,
            ]:
                logger.error(
                    f"[{task_id}] Bundle patch submission rejected (status: {response.status}) for harness: {pov_id} {patch_id} {sarif_id}",  # noqa: E501
                )
                span.set_status(Status(StatusCode.ERROR))
                return (False, mapped_status)

            span.set_status(Status(StatusCode.OK))
            return (True, mapped_status)

    def delete_bundle(self, task_id: str, bundle_id: str) -> bool:
        """Delete a bundle by bundle_id.

        Args:
            task_id: Task ID for the submission
            bundle_id: Bundle ID to delete

        Returns:
            bool: True if successful, False otherwise

        """
        assert task_id
        assert bundle_id

        tracer = trace.get_tracer(__name__)
        with tracer.start_as_current_span("delete_bundle") as span:
            set_crs_attributes(
                span,
                crs_action_category=CRSActionCategory.SCORING_SUBMISSION,
                crs_action_name="delete_bundle",
                task_metadata=self._get_task_metadata(task_id),
            )

            try:
                logger.debug(f"[{task_id}] Deleting bundle: {bundle_id}")
                response = BundleApi(api_client=self.api_client).v1_task_task_id_bundle_bundle_id_delete(
                    task_id=task_id,
                    bundle_id=bundle_id,
                )
                logger.debug(f"[{task_id}] Bundle deletion response: {response}")
                span.set_status(Status(StatusCode.OK))
                return True

            except Exception as e:
                logger.error(f"[{task_id}] Bundle deletion failed for bundle_id: {bundle_id}, error: {e}")
                span.set_status(Status(StatusCode.ERROR))
                return False

    def submit_matching_sarif(self, task_id: str, sarif_id: str) -> tuple[bool, SubmissionResult]:
        """Submit a matching assessment for a SARIF report.

        Used to claim overlap between our vulnerability findings and a broadcast SARIF.

        Args:
            task_id: Task ID for the submission
            sarif_id: ID of the broadcast SARIF report to assess

        Returns:
            Tuple[bool, SubmissionResult]:
                - True if successful, False otherwise
                - Submission status

        """
        assert task_id
        assert sarif_id

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
                api_client=self.api_client,
            ).v1_task_task_id_broadcast_sarif_assessment_broadcast_sarif_id_post(
                task_id=task_id,
                broadcast_sarif_id=sarif_id,
                payload=submission,
            )
            logger.debug(f"[{task_id}] Matching SARIF submission response: {response}")
            mapped_status = _map_submission_status_to_result(response.status)
            if mapped_status not in [
                SubmissionResult.ACCEPTED,
                SubmissionResult.PASSED,
            ]:
                logger.error(
                    f"[{task_id}] Matching SARIF submission rejected (status: {response.status}) for sarif_id: {sarif_id}",  # noqa: E501
                )
                span.set_status(Status(StatusCode.ERROR))
                return (False, mapped_status)

            span.set_status(Status(StatusCode.OK))
            return (True, mapped_status)


@dataclass
class Submissions:
    """Manages the complete lifecycle of vulnerability submissions to the competition API.

    This class implements a state machine that coordinates the submission of vulnerabilities (POVs),
    patches, and bundles to a competition API. It handles deduplication, async patch generation,
    validation, and cross-submission optimization.

    High-Level Approach
    ------------------

    **Entry Points:**
    - `submit_vulnerability()`: Called when fuzzers find new crashes
    - `record_patch()`: Called when patch generators complete work
    - `record_patched_build()`: Called when patched builds are ready
    - `process_cycle()`: Main processing loop that advances all state machines

    **Competition API Interaction Strategy:**
    1. Submit POVs immediately to claim vulnerabilities
    2. Request patches asynchronously via queues while POVs are being validated
    3. Test patches against all POVs to ensure complete mitigation
    4. Submit patches only after POV validation passes and patch effectiveness is confirmed
    5. Create bundles combining POVs + patches + optional SARIF matches
    6. Handle retries, errors, and state synchronization with competition API

    **Deduplication and Optimization:**
    - Similar crashes are detected and consolidated into single submissions
    - Cross-submission patch sharing: if one submission's patch fixes another's POVs, merge them
    - SARIF matching to claim overlap with external vulnerability reports
    - Resource limits prevent too many concurrent patch requests per task

    **State Persistence:**
    - All state stored in Redis for crash recovery
    - In-memory cache for performance
    - Atomic updates using Redis pipelines

    State Machine Details
    --------------------

    **POV States:**
    - Submit immediately via `submit_vulnerability()` → ACCEPTED
    - ACCEPTED → PASSED/FAILED/ERRORED (via competition API polling)
    - ERRORED → retry submission

    **Patch States:**
    - Request via queues → patch generated → recorded via `record_patch()`
    - Test against all POVs for effectiveness → submit if all POVs mitigated
    - ACCEPTED → PASSED/FAILED/ERRORED (via competition API polling)
    - FAILED/ERRORED → advance to next patch or retry

    **Bundle States:**
    - Create when POV=PASSED and patch=PASSED
    - ACCEPTED → PASSED/FAILED/ERRORED (via competition API polling)
    - Support SARIF associations for additional scoring

    **Processing Flow (process_cycle):**
    1. POV management: submit new POVs, update statuses, handle retries
    2. Patch management: request patches, test effectiveness, submit good patches, update statuses
    3. Bundle management: create/update bundles, handle SARIF matching
    4. Cross-submission merging: consolidate entries when patches fix other POVs

    Thread Safety: Designed for single-instance operation with Redis providing persistence.
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
    concurrent_patch_requests_per_task: int = 12
    entries: list[SubmissionEntry] = field(init=False)
    sarif_store: SARIFStore = field(init=False)
    matched_sarifs: set[str] = field(default_factory=set)
    build_requests_queue: ReliableQueue[BuildRequest] = field(init=False)
    pov_reproduce_status: PoVReproduceStatus = field(init=False)

    def __post_init__(self) -> None:
        logger.info(
            f"Initializing Submissions, patch_submission_retry_limit={self.patch_submission_retry_limit}, patch_requests_per_vulnerability={self.patch_requests_per_vulnerability}, concurrent_patch_requests_per_task={self.concurrent_patch_requests_per_task}",  # noqa: E501
        )
        self.entries = self._get_stored_submissions()
        self.sarif_store = SARIFStore(self.redis)
        self.matched_sarifs = self._get_matched_sarifs(self.redis)
        queue_factory = QueueFactory(self.redis)
        self.build_requests_queue = queue_factory.create(QueueNames.BUILD, block_time=None)
        self.pov_reproduce_status = PoVReproduceStatus(self.redis)

    def _insert_matched_sarif(self, redis: Redis, sarif_id: str) -> None:
        """Insert a matched SARIF ID into Redis."""
        self.matched_sarifs.add(sarif_id)
        redis.sadd(self.MATCHED_SARIFS, sarif_id)

    def _get_matched_sarifs(self, redis: Redis) -> set[str]:
        """Get all matched SARIF IDs from Redis."""
        matched_sarifs = redis.smembers(self.MATCHED_SARIFS)
        return set(matched_sarifs)

    def _get_stored_submissions(self) -> list[SubmissionEntry]:
        """Get all stored submissions from Redis."""
        submissions_data = self.redis.lrange(self.SUBMISSIONS, 0, -1)
        return [SubmissionEntry.FromString(raw) for raw in submissions_data]

    def _persist(self, redis: Redis, index: int, entry: SubmissionEntry) -> None:
        """Persist the submissions to Redis."""
        redis.lset(self.SUBMISSIONS, index, entry.SerializeToString())

    def _push(self, entry: SubmissionEntry) -> int:
        """Push a submission to Redis."""
        result = self.redis.rpush(self.SUBMISSIONS, entry.SerializeToString())
        return int(result)

    def _enumerate_submissions(self) -> Iterator[tuple[int, SubmissionEntry]]:
        """Enumerate all submissions belonging to active tasks."""
        for i, e in enumerate(self.entries):
            if e.stop:
                continue
            if self.task_registry.should_stop_processing(_task_id(e)):
                continue
            yield i, e

    def _enumerate_task_submissions(self, task_id: str) -> Iterator[tuple[int, SubmissionEntry]]:
        """Enumerate all submissions belonging to a specific task (if it is active)."""
        for i, e in self._enumerate_submissions():
            if _task_id(e) != task_id:
                continue
            yield i, e

    def _find_patch(self, internal_patch_id: str) -> tuple[int, SubmissionEntry, SubmissionEntryPatch] | None:
        """Find a patch by its internal patch id."""
        for i, e in self._enumerate_submissions():
            for patch in e.patches:
                if patch.internal_patch_id == internal_patch_id:
                    return i, e, patch
        return None

    def find_similar_entries(self, crash: TracedCrash) -> list[tuple[int, SubmissionEntry]]:
        """Find existing submissions that have crashes similar to the given crash.

        Args:
            crash: The traced crash to compare against existing submissions

        Returns:
            List of (index, SubmissionEntry) tuples for similar submissions

        """
        crash_data = get_crash_data(crash.crash.stacktrace)
        inst_key = get_inst_key(crash.crash.stacktrace)
        task_id = _task_id(crash)

        similar_entries = []
        for i, e in self._enumerate_task_submissions(task_id):
            for existing_crash_with_id in e.crashes:
                submission_crash_data = get_crash_data(existing_crash_with_id.crash.crash.stacktrace)
                submission_inst_key = get_inst_key(existing_crash_with_id.crash.crash.stacktrace)

                cf_comparator = CrashComparer(crash_data, submission_crash_data)
                instkey_comparator = CrashComparer(inst_key, submission_inst_key)

                if cf_comparator.is_similar() or instkey_comparator.is_similar():
                    log_entry(
                        e,
                        f"Incoming PoV crash_data: {crash_data}, inst_key: {inst_key}, existing crash_data: {submission_crash_data}, existing inst_key: {submission_inst_key} are duplicates. ",  # noqa: E501
                        i,
                        fn=logger.debug,
                    )

                    similar_entries.append((i, e))
                    # No need to check other crashes in this submission
                    break

        return similar_entries

    def _add_to_similar_submission(self, crash: TracedCrash) -> bool:
        """Check if the crash is similar to an existing submission and add it if so.

        This method performs deduplication by comparing the crash data and instruction keys
        of the new crash against existing submissions for the same task. If the crash is
        similar to multiple submissions, it consolidates them by merging all data into
        the first similar submission and stopping the others.

        Args:
            crash: The traced crash to check for similarity

        Returns:
            True if the crash was added to an existing submission (duplicate found),
            False if no similar submission was found

        """
        similar_entries = self.find_similar_entries(crash)

        if len(similar_entries) == 0:
            # Unique PoV
            return False
        # Similar submissions found - consolidate them (handles both single and multiple cases)
        return self._consolidate_similar_submissions(crash, similar_entries)

    def _consolidate_similar_submissions(
        self,
        crash: TracedCrash | None,
        similar_entries: list[tuple[int, SubmissionEntry]],
    ) -> bool:
        """Consolidate multiple similar submissions into the first one.

        Args:
            crash: The new crash that triggered the consolidation (if any)
            similar_entries: List of (index, SubmissionEntry) tuples for similar submissions

        Returns:
            True indicating the crash was handled (consolidated)

        """
        # Use the first similar submission as the target
        target_index, target_entry = similar_entries[0]

        if crash is not None:
            # Add the new crash to the target
            crash_with_id = CrashWithId()
            crash_with_id.crash.CopyFrom(crash)
            target_entry.crashes.append(crash_with_id)

        log_entry(
            target_entry,
            i=target_index,
            msg=f"Consolidating {len(similar_entries)} similar submissions into this one. Adding new crash."
            if crash is not None
            else f"Consolidating {len(similar_entries)} similar submissions into this one.",
        )

        # Use a Redis pipeline to ensure all operations are persisted atomically
        pipeline = self.redis.pipeline()

        # Merge all other similar submissions into the target
        for source_index, source_entry in similar_entries[1:]:
            log_entry(source_entry, i=source_index, msg=f"Merging submission into target at index {target_index}")

            # Copy all crashes from source to target
            target_entry.crashes.extend(source_entry.crashes)

            # Copy non-discarded patches from source (starting from source's current patch_idx)
            if source_entry.patch_idx < len(source_entry.patches):
                target_entry.patches.extend(source_entry.patches[source_entry.patch_idx :])

            # Copy bundles from source to target
            target_entry.bundles.extend(source_entry.bundles)

            # Stop the source submission and add to pipeline
            source_entry.stop = True
            self._persist(pipeline, source_index, source_entry)

            log_entry(
                source_entry,
                i=source_index,
                msg=f"Submission consolidated and stopped. Total crashes in target: {len(target_entry.crashes)}, total patches: {len(target_entry.patches)}",  # noqa: E501
            )

        # Reorder patches after consolidation to ensure optimal processing order
        self._reorder_patches_by_completion(target_entry)

        # Add the updated target entry to pipeline
        self._persist(pipeline, target_index, target_entry)

        # Execute all operations atomically
        pipeline.execute()

        log_entry(
            target_entry,
            i=target_index,
            msg=f"Consolidation complete. Final submission has {len(target_entry.crashes)} crashes and {len(target_entry.patches)} patches.",  # noqa: E501
        )

        return True

    def submit_vulnerability(self, crash: TracedCrash) -> bool:
        """Entry point for new vulnerability discoveries from fuzzers.

        Performs deduplication against existing submissions and either:
        - Consolidates with similar existing submissions, or
        - Creates a new submission entry that will be processed by process_cycle()

        Note: This method does NOT submit to the competition API immediately.
        The actual API submission happens asynchronously in process_cycle().

        Args:
            crash: The traced crash representing the vulnerability

        Returns:
            True if the crash was handled (new submission or consolidated), False otherwise

        """
        if self.task_registry.should_stop_processing(_task_id(crash)):
            logger.info("Task is cancelled or expired, will not submit vulnerability.")
            logger.debug(f"CrashInfo: {crash}")
            return True

        # Check if the crash is a variant of an existing submission
        if self._add_to_similar_submission(crash):
            return True

        e = SubmissionEntry()
        crash_with_id = CrashWithId()
        crash_with_id.crash.CopyFrom(crash)
        e.crashes.append(crash_with_id)

        # Persist to Redis
        length = self._push(e)
        index = length - 1

        # If this fails, we have a bug.  Let it crash. Reloading the Submissions object will "fix it".
        assert index == len(self.entries)

        # Keep the entries list in sync
        self.entries.append(e)
        log_entry(e, i=index, msg="Recorded unique PoV")
        return True

    def _submit_pov_if_needed(self, i: int, e: SubmissionEntry, _redis: Redis) -> bool:
        """Submit first eligible POV to competition API if none are pending/successful.
        Returns True if entry needs persistence, False otherwise.
        """
        if _get_first_successful_pov(e):
            # We already have a successful POV, we don't need to submit more.
            return False

        if _get_pending_pov_submissions(e):
            # We have pending POVs, no need to submit yet another one.
            return False

        # No successful POV, and no pending POVs, we can submit a new one.
        for pov in _get_eligible_povs_for_submission(e):
            # A previous submission attempt errored, we want to submit again, but all other states are final.
            pov_id, status = self.competition_api.submit_pov(pov.crash)
            if pov_id:
                pov.competition_pov_id = pov_id
                pov.result = status
                log_entry(e, i=i, msg="Submitted POV")
                return True
            logger.error(
                f"[{_task_id(pov.crash)}] Failed to submit vulnerability. Competition API returned {status}. Will attempt the next PoV.",  # noqa: E501
            )
            logger.debug(f"CrashInfo: {pov.crash}")
            log_entry(e, i=i, msg="Failed to submit POV")

        return False

    def _update_pov_status(self, i: int, e: SubmissionEntry, _redis: Redis) -> bool:
        """Poll competition API for status updates on pending POVs.
        Returns True if any status changed and entry needs persistence.
        """
        updated = False
        for pov in _get_pending_pov_submissions(e):
            status = self.competition_api.get_pov_status(_task_id(pov.crash), pov.competition_pov_id)
            if status != SubmissionResult.ACCEPTED:
                pov.result = status
                log_entry(e, i=i, msg=f"Updated POV status. New status {SubmissionResult.Name(status)}")
                updated = True
        return updated

    def _task_outstanding_patch_requests(self, task_id: str) -> int:
        """Check the number of patch requests that have not been completed for the given task."""
        n = 0
        for _, e in self._enumerate_task_submissions(task_id):
            maybe_patch = _current_patch(e)
            if maybe_patch and not maybe_patch.patch:
                n += 1
        return n

    def _request_patch_if_needed(self, i: int, e: SubmissionEntry, redis: Redis) -> bool:
        """Request patch generation via queue if no current patch and conditions are met.
        Respects concurrency limits and waits for potential cross-submission merging.
        Returns True if patch request was made and entry needs persistence.
        """
        # If we already have the "current patch" no need to request more.
        if _current_patch(e):
            return False

        # Do not request a patch until we know if the PoV is already mitigated by an already submitted patch from
        # another submission
        # If this returns False, this will later be merged.
        if self._should_wait_for_patch_mitigation_merge(i, e):
            return False

        # Do not request a patch if there are already too many outstanding patch requests for the task
        if self._task_outstanding_patch_requests(_task_id(e)) >= self.concurrent_patch_requests_per_task:
            log_entry(
                e,
                i=i,
                msg=f"Skipping patch request because there are already {self._task_outstanding_patch_requests(_task_id(e))} outstanding patch requests for the task",  # noqa: E501
                fn=logger.debug,
            )
            return False

        log_entry(e, i=i, msg="Submitting patch request")

        patch_tracker = self._new_patch_tracker()
        confirmed = ConfirmedVulnerability()
        for crash_with_id in e.crashes:
            confirmed.crashes.append(crash_with_id.crash)
        confirmed.internal_patch_id = patch_tracker.internal_patch_id
        e.patches.append(patch_tracker)

        q = QueueFactory(redis).create(QueueNames.CONFIRMED_VULNERABILITIES, block_time=None)
        self._enqueue_patch_requests(confirmed_vulnerability=confirmed, q=q)

        log_entry(e, i=i, msg="Patch request submitted")

        return True

    def _request_patched_builds_if_needed(self, i: int, e: SubmissionEntry, redis: Redis) -> bool:
        """Make sure that builds are available for the current patch, if any."""
        patch = _current_patch(e)
        if not patch:
            # No current patch, nothing to do.
            return False

        if not patch.patch:
            # Patch has been requested but not yet generated, nothing to do.
            return False

        if patch.build_outputs:
            # We already have build outputs (or we are waiting for them), nothing to do.
            return False

        # Request the patched builds
        task_id = _task_id(e)
        task = ChallengeTask(read_only_task_dir=self.tasks_storage_dir / task_id)
        project_yaml = ProjectYaml(task, task.task_meta.project_name)
        engine = "libfuzzer"
        if engine not in project_yaml.fuzzing_engines:
            engine = project_yaml.fuzzing_engines[0]
        sanitizers = project_yaml.sanitizers
        q = QueueFactory(redis).create(QueueNames.BUILD, block_time=None)
        for san in sanitizers:
            # Create a BuildOutput placeholder for the patched build
            build_output = BuildOutput(
                engine=engine,
                sanitizer=san,
                task_dir="",  # placeholder,  will be updated when the build request is processed
                task_id=task_id,
                build_type=BuildType.PATCH,
                apply_diff=True,
                internal_patch_id=patch.internal_patch_id,
            )
            build_req = BuildRequest(
                engine=build_output.engine,
                task_dir=str(task.task_dir),
                task_id=build_output.task_id,
                build_type=build_output.build_type,
                sanitizer=build_output.sanitizer,
                apply_diff=build_output.apply_diff,
                patch=patch.patch,
                internal_patch_id=build_output.internal_patch_id,
            )
            q.push(build_req)
            # Add the build output placeholder to the list of patch builds
            patch.build_outputs.append(build_output)
            logger.info(
                f"[{task_id}] Pushed build request {BuildType.Name(build_req.build_type)} | {build_req.sanitizer} | {build_req.engine} | {build_req.apply_diff} | {build_req.internal_patch_id}",  # noqa: E501
            )
        return True

    def record_patched_build(self, build_output: BuildOutput) -> bool:
        """Entry point for completed patched builds from build system.

        Updates the build output placeholder in the patch entry with the actual
        build directory path. This enables POV reproduction testing to validate
        patch effectiveness before submission to competition API.

        Args:
            build_output: Completed build with task directory path filled in

        Returns:
            True if build was recorded successfully

        """
        key = build_output.internal_patch_id
        maybe_patch = self._find_patch(key)
        if not maybe_patch:
            # If we get here, the build output is not associated with any patch,
            # it is possible that the task was cancelled or expired.
            logger.error(
                f"Build output {build_output.internal_patch_id} not found in any patch (task expired/cancelled?). Will discard.",  # noqa: E501
            )
            return True

        i, e, patch = maybe_patch

        bo = _find_matching_build_output(patch, build_output)
        if not bo:
            # This should never happen, but just in case.
            logger.error(
                f"Build output {build_output.internal_patch_id} not found in patch {patch.internal_patch_id}. Will discard.",  # noqa: E501
            )
            return True

        # Found the placeholder, now record the build output
        if bo.task_dir:
            # This could happen if the build takes longer than the build request timeout.
            logger.warning(
                f"Build output {build_output.internal_patch_id} already recorded for patch {patch.internal_patch_id}. Will discard.",  # noqa: E501
            )
            return True

        if bo.task_id != build_output.task_id:
            # This should never happen, but just in case.
            logger.error(
                f"Build output {build_output.internal_patch_id} has a different task id than the patch. Will discard.",
            )
            return True

        bo.task_dir = build_output.task_dir
        # Persist the entry to Redis
        self._persist(self.redis, i, e)
        log_entry(e, i=i, msg=f"Patched build recorded for patch {patch.internal_patch_id}")
        return True

    def _submit_patch_if_good(self, i: int, e: SubmissionEntry, redis: Redis) -> bool:
        """Test current patch effectiveness and submit to competition API if it mitigates all POVs.
        Advances to next patch if current one fails testing or submission retry limit exceeded.
        Returns True if entry needs persistence.
        """
        # Check that at least one POV has passed validation and has a competition_pov_id
        if not _get_first_successful_pov_id(e):
            return False

        # No patch has been requested yet, we don't need to submit anything.
        patch = _current_patch(e)
        if not patch:
            return False

        # No patch has been received yet, we don't need to submit anything.
        if not patch.patch:
            return False

        # Check if all POVs have been mitigated by running them against the patched build.
        # NOTE: We only test POVs that passed competition validation (ignoring FAILED ones).
        # This is safe because we know at least one POV passed (checked above).
        status = self._check_all_povs_are_mitigated(i, e, e.patch_idx)
        if status is None:
            return False  # Pending evaluation
        if not status:
            # Patch doesn't mitigate all POVs, advance to next patch
            _advance_patch_idx(e)
            return True

        # Check if the patch has already been submitted.
        if patch.competition_patch_id:
            # This patch has already been submitted, we don't need to submit it again.
            # It is either that the current patch is good, or, we advanced to the next patch (which was
            # previously merged from a different SubmissionEntry)
            return False

        # Check if this submission's POVs are mitigated by patches from other submissions
        if self._should_wait_for_patch_mitigation_merge(i, e):
            return False

        # If we have tried submitting the patch too many times, we will move on to the next patch.
        if e.patch_submission_attempts >= self.patch_submission_retry_limit:
            # Hopefully, it was something wrong with our previous patch that made the submission fail and not the
            # competition-API side. If it is the competition-API that is the issue, we will end up in a loop
            # requesting new patches and submitting them. This is not ideal, however the alternative scenario is that
            # we are stuck submitting the same patch over and over again.
            _advance_patch_idx(e)
            return True

        # At this point, we have a good patch to submit.
        competition_patch_id, status = self.competition_api.submit_patch(_task_id(e), patch.patch)
        patch.result = status
        if competition_patch_id:
            # Good submission, record the patch id
            patch.competition_patch_id = competition_patch_id
            log_entry(e, i=i, msg=f"Patch successfully submitted id={competition_patch_id}")
        elif status == SubmissionResult.ERRORED:
            _increase_submission_attempts(e)
            log_entry(e, i=i, msg=f"Patch submission errored, will try again. Attempts={e.patch_submission_attempts}")
        elif status == SubmissionResult.FAILED or status == SubmissionResult.INCONCLUSIVE:
            # Bad patch (or undecided state), move on to next
            _advance_patch_idx(e)
            log_entry(
                e,
                i=i,
                msg=f"Patch submission failed, advancing to next patch. Attempts={e.patch_submission_attempts}",
            )
        else:
            # This is a status we won't do anything about, just record it. If it is a timeout, next iteration
            # will probably filter the SubmissionEntry so we won't try this patch again.
            log_entry(e, i=i, msg=f"Patch submission returned unknown status {status}")

        return True

    def _update_patch_status(self, i: int, e: SubmissionEntry, redis: Redis) -> bool:
        """Update the status of any patch in the ACCEPTED state."""
        updated = False
        for patch in _get_pending_patch_submissions(e):
            status = self.competition_api.get_patch_status(_task_id(e), patch.competition_patch_id)
            patch.result = status
            match status:
                case SubmissionResult.PASSED:
                    log_entry(e, i=i, msg="Patch passed")
                    updated = True
                case SubmissionResult.FAILED | SubmissionResult.INCONCLUSIVE:
                    log_entry(e, i=i, msg="Patch failed. Will advance to next patch.")
                    _advance_patch_idx(e)
                    updated = True
                case SubmissionResult.ERRORED:
                    patch.competition_patch_id = None  # type: ignore[invalid-assignment]  # field should be Optional
                    log_entry(e, i=i, msg="Patch errored. Will try again. Attempts={e.patch_submission_attempts}")
                    _increase_submission_attempts(e)
                    updated = True
                case SubmissionResult.DEADLINE_EXCEEDED:
                    patch.competition_patch_id = None  # type: ignore[invalid-assignment]  # field should be Optional
                    log_entry(e, i=i, msg="Patch deadline exceeded. Will stop trying.")
                    # NOTE: Not increasing patch index as we don't want another patch to be generated
                    updated = True
                case SubmissionResult.ACCEPTED:
                    # No change
                    pass

        return updated

    def _ensure_single_bundle(self, i: int, e: SubmissionEntry, redis: Redis) -> bool:
        """When SubmissionEntries are merged, we might end up having multiple bundles.
        We want to avoid that so delete one bundle to get us closer to single bundle.
        We only do one delete each iteration to prevent loosing too much data if something goes wrong.
        """
        if len(e.bundles) <= 1:
            # All good
            return False

        last_bundle_id = e.bundles[-1].bundle_id
        task_id = _task_id(e)
        logger.debug(f"[{task_id}] Deleting bundle {last_bundle_id}")
        if self.competition_api.delete_bundle(task_id, last_bundle_id):
            log_entry(e, i=i, msg=f"Deleted bundle {last_bundle_id}")
            e.bundles.pop()
            return True

        log_entry(e, i=i, msg=f"Failed to delete bundle {last_bundle_id}. Will keep trying.")
        return False

    def _ensure_bundle_contents(
        self,
        i: int,
        e: SubmissionEntry,
        redis: Redis,
        competition_pov_id: str,
        competition_patch_id: str | None = None,
        competition_sarif_id: str | None = None,
    ) -> bool:
        """ "Ensures there is a single bundle with the given competition_pov_id, competition_patch_id and
        competition_sarif_id
        NOTE: Only called when bundles < 2
        NOTE: competition_patch_id and competition_sarif_id can be None if we are not submitting a patch or sarif
        when they are not set, for a new bundle we will set them to empty strings,
        for an existing bundle we will not change them.
        """
        nbundles = len(e.bundles)
        if nbundles > 1:
            # We only process when there is at most one bundle
            return False

        task_id = _task_id(e)
        if nbundles == 0:
            competition_bundle_id, status = self.competition_api.submit_bundle(
                task_id,
                competition_pov_id,
                competition_patch_id or "",
                competition_sarif_id or "",
            )
            if competition_bundle_id:
                bundle = Bundle(
                    bundle_id=competition_bundle_id,
                    task_id=task_id,
                    competition_pov_id=competition_pov_id,
                    competition_patch_id=competition_patch_id,
                    competition_sarif_id=competition_sarif_id,
                )

                e.bundles.append(bundle)
                log_entry(
                    e,
                    i=i,
                    msg=f"Submitted bundle {competition_bundle_id} for patch {competition_patch_id} and sarif {competition_sarif_id}",  # noqa: E501
                )
                return True
            log_entry(
                e,
                i=i,
                msg=f"Failed to submit bundle, status: {status}. Will keep trying (not much else we can do).",
            )
            return False
        # We have a previous bundle, check if it is still valid
        bundle = e.bundles[0]
        bundle_needs_update = False
        if competition_patch_id is not None:
            # Want to make sure this is the value in the bundle, first check if it is already set
            if bundle.competition_patch_id != competition_patch_id:
                # If it is not set, set it
                bundle.competition_patch_id = competition_patch_id
                bundle_needs_update = True
        if competition_sarif_id is not None:
            # Want to make sure this is the value in the bundle, first check if it is already set
            if bundle.competition_sarif_id != competition_sarif_id:
                # If it is not set, set it
                bundle.competition_sarif_id = competition_sarif_id
                bundle_needs_update = True

        if not bundle_needs_update:
            # All good, no need to do anything
            return False

        log_entry(e, i=i, msg="Patching bundle")
        # It bundles the wrong contents, patch the bundle using the correct contents.
        success, status = self.competition_api.patch_bundle(
            bundle.task_id,
            bundle.bundle_id,
            bundle.competition_pov_id,
            bundle.competition_patch_id,
            bundle.competition_sarif_id,
        )
        if success:
            log_entry(
                e,
                i=i,
                msg=f"Patched bundle {bundle.bundle_id} with patch {competition_patch_id} and sarif {competition_sarif_id}",  # noqa: E501
            )
            return True

        log_entry(e, i=i, msg=f"Failed to patch bundle {bundle.bundle_id}. Status: {status}. Will keep trying.")
        return False

    def _ensure_patch_is_bundled(self, i: int, e: SubmissionEntry, redis: Redis) -> bool:
        """Create or update bundle to include current passed patch with successful POV.
        Returns True if bundle was modified and entry needs persistence.
        """
        current_patch = _current_patch(e)
        if not current_patch:
            return False

        if current_patch.result != SubmissionResult.PASSED:
            # We only process when the current patch is passed
            return False

        nbundles = len(e.bundles)
        if nbundles > 1:
            # We only process when there is at most one bundle
            return False

        # Either get the PoV from the bundle, or from the first successful PoV
        competition_pov_id = e.bundles[0].competition_pov_id if e.bundles else _get_first_successful_pov_id(e)

        # If we don't have a PoV, we can't bundle, this should never happen.
        if not competition_pov_id:
            logger.error(f"No competition PoV ID found for submission {e.id}")  # type: ignore[unresolved-attribute]
            return False

        # Update the bundle with the current patch
        return self._ensure_bundle_contents(
            i,
            e,
            redis,
            competition_pov_id,
            competition_patch_id=current_patch.competition_patch_id,
        )

    def _get_available_sarifs_for_matching(self, task_id: str) -> list[SARIFBroadcastDetail]:
        """Get SARIFs that are available for matching for the given task.

        Returns SARIFs for the task that haven't been used in any existing bundles.

        Args:
            task_id: The task ID to get SARIFs for

        Returns:
            List of SARIF objects that are available for matching

        """
        # Get SARIFs for the task, if none there is nothing to do.
        sarifs = self.sarif_store.get_by_task_id(task_id)
        if not sarifs:
            return []

        # Collect already used SARIFs, we can only bundle a SARIF once.
        # Only consider active submissions - stopped submissions release their SARIFs for reuse
        already_submitted_sarifs = {
            bundle.competition_sarif_id
            for _, submission_entry in self._enumerate_task_submissions(task_id)
            for bundle in submission_entry.bundles
            if bundle.competition_sarif_id
        }

        # Return only SARIFs that haven't been used yet
        return [sarif for sarif in sarifs if sarif.sarif_id not in already_submitted_sarifs]

    def _ensure_sarif_is_bundled(self, i: int, e: SubmissionEntry, redis: Redis) -> bool:
        """Find external SARIF reports that match this entry's POVs and bundle them for additional scoring.
        Requires line-level matching for confidence. Returns True if bundle was created/updated.
        """
        # If this already has a bundle with a SARIF no need to do anything
        if e.bundles and e.bundles[0].competition_sarif_id:
            return False

        # We need a successful POV to bundle a SARIF.
        competition_pov_id = _get_first_successful_pov_id(e)
        if not competition_pov_id:
            return False

        # Find a SARIF that matches a passed PoV
        for sarif in self._get_available_sarifs_for_matching(_task_id(e)):
            for crash in e.crashes:
                match_result = match(sarif, crash.crash)  # type: ignore[invalid-argument-type]
                if match_result:
                    log_entry(
                        e,
                        i=i,
                        msg=f"Found matching SARIF: {sarif.sarif_id}: {match_result}. Checking if it matches on lines.",
                        fn=logging.debug,
                    )
                    # We require a match on lines to be confident that the SARIF is a good match.
                    if not match_result.matches_lines:
                        continue
                    log_entry(
                        e,
                        i=i,
                        msg=f"Found matching SARIF: {sarif.sarif_id}: {match_result}. Will bundle it.",
                        fn=logging.info,
                    )
                    return self._ensure_bundle_contents(
                        i,
                        e,
                        redis,
                        competition_pov_id,
                        competition_sarif_id=sarif.sarif_id,
                    )
        return False

    def _confirm_matched_sarifs(self, i: int, e: SubmissionEntry, redis: Redis) -> bool:
        """Ensure the SARIF is submitted to the competition API"""
        if len(e.bundles) != 1:
            # Don't make any changes while we are fixing up bundles resulting from a merge
            return False

        bundle = e.bundles[0]
        if not bundle.competition_sarif_id:
            return False

        if bundle.competition_sarif_id not in self.matched_sarifs:
            # We have a bundle with a SARIF that hasn't been confirmed yet. Do that now.
            success, status = self.competition_api.submit_matching_sarif(_task_id(e), bundle.competition_sarif_id)
            if success:
                self._insert_matched_sarif(redis, bundle.competition_sarif_id)
                return True
            log_entry(
                e,
                i=i,
                msg=f"Failed to confirm SARIF {bundle.competition_sarif_id}. Status: {status}. Will keep trying.",
            )

        # We have a bundle with a SARIF that has been confirmed, no need to do anything (or confirmation failed)
        return True

    def _reorder_patches_by_completion(self, e: SubmissionEntry) -> None:
        """Reorder patches starting from patch_idx so that patches with content come before those without.

        This ensures that completed patches are processed before outstanding patch requests,
        regardless of the order in which they were received.

        Args:
            e: The submission entry to reorder patches for

        """
        if not _current_patch(e):
            return

        # Convert to list for easier manipulation
        all_patches = list(e.patches)

        # Split patches into those before patch_idx (already processed) and those from patch_idx onwards
        processed_patches = all_patches[: e.patch_idx]
        pending_patches = all_patches[e.patch_idx :]

        # Sort pending patches: those with content first, then those without
        # Maintain relative order within each group to preserve original request order
        patches_with_content = [p for p in pending_patches if p.patch]
        patches_without_content = [p for p in pending_patches if not p.patch]

        # Reconstruct the patches list
        reordered_patches = processed_patches + patches_with_content + patches_without_content

        # Clear the protobuf repeated field and repopulate it
        del e.patches[:]
        for patch in reordered_patches:
            e.patches.append(patch)

    def record_patch(self, patch: Patch) -> bool:
        """Entry point for completed patches from patch generators.

        Finds the submission entry associated with the patch's internal_patch_id and
        records the patch content. Reorders patches to prioritize completed ones for
        faster processing in process_cycle().

        Note: Does not submit to competition API immediately. Patches are tested for
        effectiveness and submitted in process_cycle() after POV validation passes.

        Args:
            patch: The completed patch with internal_patch_id and content

        Returns:
            True if patch was recorded successfully

        """
        key = patch.internal_patch_id
        maybe_patch = self._find_patch(key)
        if not maybe_patch:
            # The patch is not associated with any submission, it is possible that the task was cancelled or expired.
            logger.error(f"Patch {key} not found in any submission (task expired/cancelled?). Will discard.")
            return True

        i, e, entry_patch = maybe_patch
        if entry_patch.patch:
            # Patch tracker already has content - this can happen when patch request times out
            # but multiple patch generators complete the work. Create a new tracker for the duplicate.
            new_patch_tracker = self._new_patch_tracker()
            new_patch_tracker.patch = patch.patch
            e.patches.append(new_patch_tracker)
        else:
            # Normal case: fill in the empty patch tracker with generated content
            entry_patch.patch = patch.patch

        # Reorder patches to prioritize those with content
        self._reorder_patches_by_completion(e)

        # Persist the updated entry to Redis
        self._persist(self.redis, i, e)

        log_entry(e, i=i, msg="Patch added")
        return True

    def _pov_reproduce_patch_status(
        self,
        patch: SubmissionEntryPatch,
        crashes: list[CrashWithId],
        task_id: str,
    ) -> list[POVReproduceResponse | None]:
        result = []
        for crash_with_id in crashes:
            if crash_with_id.result in [
                SubmissionResult.FAILED,
                SubmissionResult.DEADLINE_EXCEEDED,
                SubmissionResult.INCONCLUSIVE,
            ]:
                continue

            request = POVReproduceRequest()
            request.task_id = task_id
            request.internal_patch_id = patch.internal_patch_id
            request.harness_name = crash_with_id.crash.crash.harness_name
            request.sanitizer = crash_with_id.crash.crash.target.sanitizer
            request.pov_path = crash_with_id.crash.crash.crash_input_path

            status = self.pov_reproduce_status.request_status(request)

            result.append(status)

        return result

    def _pov_reproduce_status_request(self, e: SubmissionEntry, patch_idx: int) -> list[POVReproduceResponse | None]:
        patch = e.patches[patch_idx]
        task_id = _task_id(e)
        return self._pov_reproduce_patch_status(patch, e.crashes, task_id)  # type: ignore[invalid-argument-type]

    def _check_all_povs_are_mitigated(self, i: int, e: SubmissionEntry, patch_idx: int) -> bool | None:
        """Test if patch at patch_idx mitigates all POVs by running them against patched builds.

        Returns:
            None: Some POV tests are still pending
            True: All POVs are mitigated (patch is effective)
            False: At least one POV still crashes (patch is ineffective)

        """
        statuses = self._pov_reproduce_status_request(e, patch_idx)
        n_pending = sum(1 for status in statuses if status is None)
        n_mitigated = sum(1 for status in statuses if status is not None and not status.did_crash)
        n_failed = sum(1 for status in statuses if status is not None and status.did_crash)
        log_entry(
            e,
            i=i,
            msg=f"Remediation status: Pending: {n_pending}, Mitigated: {n_mitigated}, Failed: {n_failed}",
            fn=logger.debug,
        )

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

    def _enqueue_patch_requests(
        self,
        confirmed_vulnerability: ConfirmedVulnerability,
        q: ReliableQueue[ConfirmedVulnerability] | None,
    ) -> None:
        """Push N copies of vulnerability to queue for parallel patch generation."""
        if q is None:
            q = QueueFactory(self.redis).create(QueueNames.CONFIRMED_VULNERABILITIES, block_time=None)

        for _ in range(self.patch_requests_per_vulnerability):
            q.push(confirmed_vulnerability)

    def _should_wait_for_patch_mitigation_merge(self, i: int, e: SubmissionEntry) -> bool:
        """Check if this submission's POVs are mitigated by patches from other submissions.

        If the POVs in this SubmissionEntry are mitigated by a patch in another SubmissionEntry,
        we will merge the two entries later on. However, for now we need to check each of the
        SubmissionEntries for this task that has submitted a patch and if the patch mitigates
        any of the POVs in this SubmissionEntry.

        Args:
            i: Index of the current submission entry
            e: The current submission entry

        Returns:
            True if we should wait for patch mitigation evaluation or merge, False otherwise

        """
        for j, e2 in self._enumerate_task_submissions(_task_id(e)):
            if i == j:
                continue

            maybe_patch = _current_patch(e2)
            # No patch, nothing to check.
            if not maybe_patch:
                continue

            # There is a patch, but it has not been submitted yet, nothing to check.
            if not maybe_patch.competition_patch_id:
                continue

            patch_mitigates_povs = self._pov_reproduce_patch_status(maybe_patch, e.crashes, _task_id(e))  # type: ignore[invalid-argument-type]
            if any(status is None for status in patch_mitigates_povs):
                # Wait until we have evaluated all our PoVs against the already submitted patch
                # there are still pending evaluations
                log_entry(e, i=i, msg="Waiting for patch mitigation evaluation")
                return True
            if any(status is not None and not status.did_crash for status in patch_mitigates_povs):
                # The patch mitigates at least one PoV in this SubmissionEntry, we will merge
                # the two entries later on.
                log_entry(
                    e,
                    i=i,
                    msg=f"Patch competition_patch_id={maybe_patch.competition_patch_id} mitigates at least one PoV, wait for merge",  # noqa: E501
                )
                return True

        return False

    def _merge_entries_by_patch_mitigation(self) -> None:
        """Cross-submission optimization: merge entries when one submission's patch fixes another's POVs.

        This consolidates resources and avoids duplicate patch work by identifying when
        a patch from submission A also mitigates POVs from submission B, then merging
        them into a single submission.
        """
        for i, e in self._enumerate_submissions():
            try:
                task_id = _task_id(e)

                current_patch = _current_patch(e)
                if current_patch is None:
                    # No patch to check
                    continue

                # This is actually a redundant check as we would only have build_outputs once the patch is received
                if not current_patch.patch:
                    continue

                if not current_patch.build_outputs:
                    # No builds requested
                    continue

                if not all(b.task_dir for b in current_patch.build_outputs):
                    # Builds aren't ready yet
                    continue

                # At this point we have the patched builds available, we can check if they mitigate any
                # PoVs in other entries (for the same task)

                to_merge = [(i, e)]
                for j, e2 in self._enumerate_task_submissions(task_id):
                    if i == j:
                        continue

                    pov_reproduce_statuses = self._pov_reproduce_patch_status(current_patch, e2.crashes, task_id)  # type: ignore[invalid-argument-type]
                    if any(status is not None and not status.did_crash for status in pov_reproduce_statuses):
                        # This patch mitigates at least one PoV from e2, we should merge the entries
                        # TODO: Does it need to mitigate all PoVs? I think not as the patch could be a partial fix.
                        to_merge.append((j, e2))

                if len(to_merge) > 1:
                    merged_indices = [j for j, _ in to_merge[1:]]  # Skip the first entry (i) since it's the target
                    logger.info(
                        f"[{i}:{_task_id(e)}] Merging {len(to_merge) - 1} similar submissions into this one. Merging indices: {', '.join(map(str, merged_indices))}",  # noqa: E501
                    )
                    self._consolidate_similar_submissions(crash=None, similar_entries=to_merge)
            except Exception as err:
                logger.error(f"[{i}:{_task_id(e)}] Error merging entries by patch mitigation: {err}")

    def process_cycle(self) -> None:
        """Main processing loop that advances all submission state machines.

        Called periodically by the scheduler to:
        1. Submit POVs to competition API and poll for status updates
        2. Request patches for validated POVs via async queues
        3. Test patch effectiveness and submit good patches to competition API
        4. Create and manage bundles (POV + patch + optional SARIF combinations)
        5. Handle retries, errors, and cross-submission consolidation

        All state changes are persisted to Redis atomically using pipelines.
        Designed to be resilient to failures and restartable.
        """
        for i, e in self._enumerate_submissions():
            try:
                needs_persist = False
                with self.redis.pipeline() as pipe:
                    # SARIF handling
                    if self._confirm_matched_sarifs(i, e, pipe):
                        needs_persist = True
                    if self._ensure_sarif_is_bundled(i, e, pipe):
                        needs_persist = True

                    # Patch handling
                    if self._ensure_patch_is_bundled(i, e, pipe):
                        needs_persist = True
                    if self._update_patch_status(i, e, pipe):
                        needs_persist = True
                    if self._request_patch_if_needed(i, e, pipe):
                        needs_persist = True
                    if self._request_patched_builds_if_needed(i, e, pipe):
                        needs_persist = True
                    if self._submit_patch_if_good(i, e, pipe):
                        needs_persist = True

                    # POV submission
                    if self._update_pov_status(i, e, pipe):
                        needs_persist = True
                    if self._submit_pov_if_needed(i, e, pipe):
                        needs_persist = True

                    # Post merge handling
                    if self._ensure_single_bundle(i, e, pipe):
                        needs_persist = True

                    if needs_persist:
                        self._persist(pipe, i, e)
                        pipe.execute()

            except Exception:
                logger.exception(f"[{i}:{_task_id(e)}] Error processing submission")
                # NOTE: The question is if we should raise at some point. Worst case we are stuck in a
                # error-condition that can only be fixed by a restart of the scheduler. However, we don't know that.
                # If we raise, we risk the scheduler only attempting the first vulnerability and the rest of the
                # cycle being skipped. This could lead to a situation where we don't attempt any submissions.
                # For now, we will just log the error and continue.

        # As a final phase we will check if active patches fixes vulnerabilities in other SubmissionEntries and for
        # those we will consolidate the SubmissionEntries.
        try:
            self._merge_entries_by_patch_mitigation()
        except Exception as err:
            logger.error(f"[{i}:{_task_id(e)}] Error merging entries by patch mitigation: {err}")
