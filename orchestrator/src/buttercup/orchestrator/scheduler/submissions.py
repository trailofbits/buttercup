from dataclasses import field, dataclass
import logging
import uuid
from redis import Redis
from typing import Callable, Iterator, List, Set, Tuple
from pathlib import Path
from buttercup.common.queues import ReliableQueue, QueueFactory, QueueNames
from buttercup.common.sets import PoVReproduceStatus
from buttercup.common.datastructures.msg_pb2 import (
    TracedCrash,
    ConfirmedVulnerability,
    SubmissionEntry,
    SubmissionEntryPatch,
    BuildRequest,
    BuildType,
    BuildOutput,
    POVReproduceRequest,
    POVReproduceResponse,
    CrashWithId,
    Bundle,
    SubmissionResult,
    Patch,
)
from buttercup.common.sarif_store import SARIFStore
from buttercup.common.task_registry import TaskRegistry

from buttercup.orchestrator.scheduler.sarif_matcher import match
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
        return e.crashes[0].crash.crash.target.task_id
    else:
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


@dataclass
class Submissions:
    """
    Manages the complete lifecycle of vulnerability processing and patch generation.

    This class implements a state machine that coordinates vulnerability (POV) processing,
    patch generation, and bundle creation. It handles deduplication, async patch generation,
    validation, and cross-submission optimization.

    High-Level Approach
    ------------------

    **Entry Points:**
    - `submit_vulnerability()`: Called when fuzzers find new crashes
    - `record_patch()`: Called when patch generators complete work
    - `record_patched_build()`: Called when patched builds are ready
    - `process_cycle()`: Main processing loop that advances all state machines

    **Internal Processing Strategy:**
    1. Process POVs for internal vulnerability tracking and analysis
    2. Request patches asynchronously via queues
    3. Test patches against all POVs to ensure complete mitigation
    4. Validate patches for effectiveness and correctness
    5. Create bundles combining POVs + patches + optional SARIF matches

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
    - Process immediately via `submit_vulnerability()` → ACCEPTED (internal processing)
    - ACCEPTED → PASSED (automatic outside of competition)

    **Patch States:**
    - Request via queues → patch generated → recorded via `record_patch()`
    - Test against all POVs for effectiveness → validate if all POVs mitigated
    - ACCEPTED → PASSED (internal validation and testing)
    - FAILED → advance to next patch or retry

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
    task_registry: TaskRegistry
    tasks_storage_dir: Path
    patch_submission_retry_limit: int = 60
    patch_requests_per_vulnerability: int = 1
    concurrent_patch_requests_per_task: int = 12
    entries: List[SubmissionEntry] = field(init=False)
    sarif_store: SARIFStore = field(init=False)
    matched_sarifs: Set[str] = field(default_factory=set)
    build_requests_queue: ReliableQueue[BuildRequest] = field(init=False)
    pov_reproduce_status: PoVReproduceStatus = field(init=False)

    def __post_init__(self) -> None:
        logger.info(
            f"Initializing Submissions, patch_submission_retry_limit={self.patch_submission_retry_limit}, patch_requests_per_vulnerability={self.patch_requests_per_vulnerability}, concurrent_patch_requests_per_task={self.concurrent_patch_requests_per_task}"
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

    def _get_matched_sarifs(self, redis: Redis) -> Set[str]:
        """Get all matched SARIF IDs from Redis."""
        return set(redis.smembers(self.MATCHED_SARIFS))

    def _get_stored_submissions(self) -> List[SubmissionEntry]:
        """Get all stored submissions from Redis."""
        return [SubmissionEntry.FromString(raw) for raw in self.redis.lrange(self.SUBMISSIONS, 0, -1)]

    def _persist(self, redis: Redis, index: int, entry: SubmissionEntry) -> None:
        """Persist the submissions to Redis."""
        redis.lset(self.SUBMISSIONS, index, entry.SerializeToString())

    def _push(self, entry: SubmissionEntry) -> int:
        """Push a submission to Redis."""
        return self.redis.rpush(self.SUBMISSIONS, entry.SerializeToString())

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

    def _find_patch(self, internal_patch_id: str) -> Tuple[int, SubmissionEntry, SubmissionEntryPatch] | None:
        """Find a patch by its internal patch id."""
        for i, e in self._enumerate_submissions():
            for patch in e.patches:
                if patch.internal_patch_id == internal_patch_id:
                    return i, e, patch
        return None

    def find_similar_entries(self, crash: TracedCrash) -> list[tuple[int, SubmissionEntry]]:
        """
        Find existing submissions that have crashes similar to the given crash.

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
                        f"Incoming PoV crash_data: {crash_data}, inst_key: {inst_key}, existing crash_data: {submission_crash_data}, existing inst_key: {submission_inst_key} are duplicates. ",
                        i,
                        fn=logger.debug,
                    )

                    similar_entries.append((i, e))
                    # No need to check other crashes in this submission
                    break

        return similar_entries

    def _add_to_similar_submission(self, crash: TracedCrash) -> bool:
        """
        Check if the crash is similar to an existing submission and add it if so.

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
        else:
            # Similar submissions found - consolidate them (handles both single and multiple cases)
            return self._consolidate_similar_submissions(crash, similar_entries)

    def _consolidate_similar_submissions(
        self, crash: TracedCrash | None, similar_entries: list[tuple[int, SubmissionEntry]]
    ) -> bool:
        """
        Consolidate multiple similar submissions into the first one.

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
                msg=f"Submission consolidated and stopped. Total crashes in target: {len(target_entry.crashes)}, total patches: {len(target_entry.patches)}",
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
            msg=f"Consolidation complete. Final submission has {len(target_entry.crashes)} crashes and {len(target_entry.patches)} patches.",
        )

        return True

    def submit_vulnerability(self, crash: TracedCrash) -> bool:
        """
        Entry point for new vulnerability discoveries from fuzzers.

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

    def _process_pov_if_needed(self, i: int, e: SubmissionEntry, _redis: Redis) -> bool:
        """
        Process first eligible POV for internal tracking if none are processed/successful.
        Returns True if entry needs persistence, False otherwise.
        """
        if _get_first_successful_pov(e):
            # We already have a successful POV, we don't need to process more.
            return False

        if _get_pending_pov_submissions(e):
            # We have pending POVs, no need to process yet another one.
            return False

        # No successful POV, and no pending POVs, we can process a new one.
        for pov in _get_eligible_povs_for_submission(e):
            # For internal processing, we automatically accept and mark as passed
            pov.competition_pov_id = f"internal_{uuid.uuid4().hex[:8]}"
            pov.result = SubmissionResult.ACCEPTED  # Auto accept outside of competition
            log_entry(e, i=i, msg="Processed POV internally")
            return True

        return False

    def _update_pov_status(self, i: int, e: SubmissionEntry, _redis: Redis) -> bool:
        """
        Update status of pending POVs to PASSED for internal processing.
        Returns True if any status changed and entry needs persistence.
        """
        updated = False
        for pov in _get_pending_pov_submissions(e):
            # For internal processing, automatically promote ACCEPTED to PASSED
            if pov.result == SubmissionResult.ACCEPTED:
                pov.result = SubmissionResult.PASSED
                log_entry(e, i=i, msg=f"Updated POV status. New status {SubmissionResult.Name(pov.result)}")
                updated = True
        return updated

    def _task_outstanding_patch_requests(self, task_id: str) -> int:
        """
        Check the number of patch requests that have not been completed for the given task.
        """
        n = 0
        for _, e in self._enumerate_task_submissions(task_id):
            maybe_patch = _current_patch(e)
            if maybe_patch and not maybe_patch.patch:
                n += 1
        return n

    def _request_patch_if_needed(self, i: int, e: SubmissionEntry, redis: Redis) -> bool:
        """
        Request patch generation via queue if no current patch and conditions are met.
        Respects concurrency limits and waits for potential cross-submission merging.
        Returns True if patch request was made and entry needs persistence.
        """

        # If we already have the "current patch" no need to request more.
        if _current_patch(e):
            return False

        # Do not request a patch until we know if the PoV is already mitigated by an already submitted patch from another submission
        # If this returns False, this will later be merged.
        if self._should_wait_for_patch_mitigation_merge(i, e):
            return False

        # Do not request a patch if there are already too many outstanding patch requests for the task
        if self._task_outstanding_patch_requests(_task_id(e)) >= self.concurrent_patch_requests_per_task:
            log_entry(
                e,
                i=i,
                msg=f"Skipping patch request because there are already {self._task_outstanding_patch_requests(_task_id(e))} outstanding patch requests for the task",
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
        """
        Make sure that builds are available for the current patch, if any.
        """

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
                task_dir="",  # Use a placeholder for the task dir, it will be updated when the build request is processed
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
                f"[{task_id}] Pushed build request {BuildType.Name(build_req.build_type)} | {build_req.sanitizer} | {build_req.engine} | {build_req.apply_diff} | {build_req.internal_patch_id}"
            )
        return True

    def record_patched_build(self, build_output: BuildOutput) -> bool:
        """
        Entry point for completed patched builds from build system.

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
                f"Build output {build_output.internal_patch_id} not found in any patch (task expired/cancelled?). Will discard."
            )
            return True

        i, e, patch = maybe_patch

        bo = _find_matching_build_output(patch, build_output)
        if not bo:
            # This should never happen, but just in case.
            logger.error(
                f"Build output {build_output.internal_patch_id} not found in patch {patch.internal_patch_id}. Will discard."
            )
            return True

        # Found the placeholder, now record the build output
        if bo.task_dir:
            # This could happen if the build takes longer than the build request timeout.
            logger.warning(
                f"Build output {build_output.internal_patch_id} already recorded for patch {patch.internal_patch_id}. Will discard."
            )
            return True

        if bo.task_id != build_output.task_id:
            # This should never happen, but just in case.
            logger.error(
                f"Build output {build_output.internal_patch_id} has a different task id than the patch. Will discard."
            )
            return True

        bo.task_dir = build_output.task_dir
        # Persist the entry to Redis
        self._persist(self.redis, i, e)
        log_entry(e, i=i, msg=f"Patched build recorded for patch {patch.internal_patch_id}")
        return True

    def _submit_patch_if_good(self, i: int, e: SubmissionEntry, redis: Redis) -> bool:
        """
        Test current patch effectiveness and submit to competition API if it mitigates all POVs.
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
            # It is either that the current patch is good, or, we advanced to the next patch (which was previously merged from a different SubmissionEntry)
            return False

        # Check if this submission's POVs are mitigated by patches from other submissions
        if self._should_wait_for_patch_mitigation_merge(i, e):
            return False

        # If we have tried submitting the patch too many times, we will move on to the next patch.
        if e.patch_submission_attempts >= self.patch_submission_retry_limit:
            # Hopefully, it was something wrong with our previous patch that made the submission fail and not the competition-API side.
            # If it is the competition-API that is the issue, we will end up in a loop requesting new patches and submitting them. This
            # is not ideal, however the alternative scenario is that we are stuck submitting the same patch over and over again.
            _advance_patch_idx(e)
            return True

        # At this point, we have a good patch for internal processing.
        competition_patch_id = f"internal_patch_{uuid.uuid4().hex[:8]}"
        status = SubmissionResult.ACCEPTED  # automatically accepted outside of competition
        patch.result = status
        patch.competition_patch_id = competition_patch_id
        log_entry(e, i=i, msg=f"Patch successfully processed internally id={competition_patch_id}")

        return True

    def _update_patch_status(self, i: int, e: SubmissionEntry, redis: Redis) -> bool:
        """
        Update the status of any patch in the ACCEPTED state to PASSED for internal processing.
        """
        updated = False
        for patch in _get_pending_patch_submissions(e):
            # For internal processing, automatically promote ACCEPTED patches to PASSED
            if patch.result == SubmissionResult.ACCEPTED:
                patch.result = SubmissionResult.PASSED
                log_entry(e, i=i, msg="Patch passed internal validation")
                updated = True
        return updated

    def _ensure_single_bundle(self, i: int, e: SubmissionEntry, redis: Redis) -> bool:
        """
        When SubmissionEntries are merged, we might end up having multiple bundles.
        We want to avoid that so delete one bundle to get us closer to single bundle.
        We only do one delete each iteration to prevent loosing too much data if something goes wrong.
        """

        if len(e.bundles) <= 1:
            # All good
            return False

        last_bundle_id = e.bundles[-1].bundle_id
        task_id = _task_id(e)
        logger.debug(f"[{task_id}] Deleting bundle {last_bundle_id}")
        # For internal processing, always succeed in "deleting" bundles
        log_entry(e, i=i, msg=f"Deleted bundle {last_bundle_id} (internal)")
        e.bundles.pop()
        return True

    def _ensure_bundle_contents(
        self,
        i: int,
        e: SubmissionEntry,
        redis: Redis,
        competition_pov_id: str,
        competition_patch_id: str | None = None,
        competition_sarif_id: str | None = None,
    ) -> bool:
        """ "Ensures there is a single bundle with the given competition_pov_id, competition_patch_id and competition_sarif_id
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
            # For internal processing, create bundle with internal ID
            competition_bundle_id = f"internal_bundle_{uuid.uuid4().hex[:8]}"
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
                msg=f"Created internal bundle {competition_bundle_id} for patch {competition_patch_id} and sarif {competition_sarif_id}",
            )
            return True
        else:
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
            # For internal processing, always succeed in patching bundles
            log_entry(
                e,
                i=i,
                msg=f"Patched bundle {bundle.bundle_id} with patch {competition_patch_id} and sarif {competition_sarif_id} (internal)",
            )
            return True

    def _ensure_patch_is_bundled(self, i: int, e: SubmissionEntry, redis: Redis) -> bool:
        """
        Create or update bundle to include current passed patch with successful POV.
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
            logger.error(f"No competition PoV ID found for submission {e.submission_id}")
            return False

        # Update the bundle with the current patch
        return self._ensure_bundle_contents(
            i, e, redis, competition_pov_id, competition_patch_id=current_patch.competition_patch_id
        )

    def _get_available_sarifs_for_matching(self, task_id: str):
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
        """
        Find external SARIF reports that match this entry's POVs and bundle them for additional scoring.
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
                match_result = match(sarif, crash.crash)
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
                        i, e, redis, competition_pov_id, competition_sarif_id=sarif.sarif_id
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
            # For internal processing, always succeed in matching SARIF
            self._insert_matched_sarif(redis, bundle.competition_sarif_id)
            log_entry(
                e,
                i=i,
                msg=f"Matched SARIF {bundle.competition_sarif_id} internally",
            )
            return True

        # We have a bundle with a SARIF that has been confirmed, no need to do anything (or confirmation failed)
        return True

    def _reorder_patches_by_completion(self, e: SubmissionEntry) -> None:
        """
        Reorder patches starting from patch_idx so that patches with content come before those without.

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
        """
        Entry point for completed patches from patch generators.

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
        self, patch: SubmissionEntryPatch, crashes: List[CrashWithId], task_id: str
    ) -> List[POVReproduceResponse | None]:
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

    def _pov_reproduce_status_request(self, e: SubmissionEntry, patch_idx: int) -> List[POVReproduceResponse | None]:
        patch = e.patches[patch_idx]
        task_id = _task_id(e)
        return self._pov_reproduce_patch_status(patch, e.crashes, task_id)

    def _check_all_povs_are_mitigated(self, i: int, e: SubmissionEntry, patch_idx: int) -> bool | None:
        """
        Test if patch at patch_idx mitigates all POVs by running them against patched builds.

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
        self, confirmed_vulnerability: ConfirmedVulnerability, q: ReliableQueue[ConfirmedVulnerability] | None
    ) -> None:
        """Push N copies of vulnerability to queue for parallel patch generation."""
        if q is None:
            q = QueueFactory(self.redis).create(QueueNames.CONFIRMED_VULNERABILITIES, block_time=None)

        for _ in range(self.patch_requests_per_vulnerability):
            q.push(confirmed_vulnerability)

    def _should_wait_for_patch_mitigation_merge(self, i: int, e: SubmissionEntry) -> bool:
        """
        Check if this submission's POVs are mitigated by patches from other submissions.

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

            patch_mitigates_povs = self._pov_reproduce_patch_status(maybe_patch, e.crashes, _task_id(e))
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
                    msg=f"Patch competition_patch_id={maybe_patch.competition_patch_id} mitigates at least one PoV, wait for merge",
                )
                return True

        return False

    def _merge_entries_by_patch_mitigation(self) -> None:
        """
        Cross-submission optimization: merge entries when one submission's patch fixes another's POVs.

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

                # At this point we have the patched builds available, we can check if they mitigate any PoVs in other entries (for the same task)

                to_merge = [(i, e)]
                for j, e2 in self._enumerate_task_submissions(task_id):
                    if i == j:
                        continue

                    pov_reproduce_statuses = self._pov_reproduce_patch_status(current_patch, e2.crashes, task_id)
                    if any(status is not None and not status.did_crash for status in pov_reproduce_statuses):
                        # This patch mitigates at least one PoV from e2, we should merge the entries
                        # TODO: Does it need to mitigate all PoVs? I think not as the patch could be a partial fix.
                        to_merge.append((j, e2))

                if len(to_merge) > 1:
                    merged_indices = [j for j, _ in to_merge[1:]]  # Skip the first entry (i) since it's the target
                    logger.info(
                        f"[{i}:{_task_id(e)}] Merging {len(to_merge) - 1} similar submissions into this one. Merging indices: {', '.join(map(str, merged_indices))}"
                    )
                    self._consolidate_similar_submissions(crash=None, similar_entries=to_merge)
            except Exception as err:
                logger.error(f"[{i}:{_task_id(e)}] Error merging entries by patch mitigation: {err}")

    def process_cycle(self) -> None:
        """
        Main processing loop that advances all submission state machines.

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
                    if self._process_pov_if_needed(i, e, pipe):
                        needs_persist = True

                    # Post merge handling
                    if self._ensure_single_bundle(i, e, pipe):
                        needs_persist = True

                    if needs_persist:
                        self._persist(pipe, i, e)
                        pipe.execute()

            except Exception as err:
                logger.error(f"[{i}:{_task_id(e)}] Error processing submission: {err}")
                # NOTE: The question is if we should raise at some point. Worst case we are stuck in a error-condition
                # that can only be fixed by a restart of the scheduler. However, we don't know that. If we raise, we risk
                # the scheduler only attempting the first vulnerability and the rest of the cycle being skipped. This could
                # lead to a situation where we don't attempt any submissions. For now, we will just log the error and continue.

        # As a final phase we will check if active patches fixes vulnerabilities in other SubmissionEntries and for those we will
        # consolidate the SubmissionEntries.
        try:
            self._merge_entries_by_patch_mitigation()
        except Exception as err:
            logger.error(f"[{i}:{_task_id(e)}] Error merging entries by patch mitigation: {err}")
