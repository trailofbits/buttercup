import logging
import random
from dataclasses import dataclass, field
from pathlib import Path

from redis import Redis

from buttercup.common.challenge_task import ChallengeTask
from buttercup.common.clusterfuzz_utils import get_fuzz_targets
from buttercup.common.datastructures.msg_pb2 import (
    BuildOutput,
    BuildRequest,
    BuildType,
    IndexRequest,
    Patch,
    Task,
    TaskReady,
    TracedCrash,
    WeightedHarness,
)
from buttercup.common.maps import BuildMap, HarnessWeights
from buttercup.common.project_yaml import ProjectYaml
from buttercup.common.queues import GroupNames, QueueFactory, QueueNames, ReliableQueue, RQItem
from buttercup.common.task_registry import TaskRegistry
from buttercup.common.utils import serve_loop
from buttercup.orchestrator.api_client_factory import create_api_client
from buttercup.orchestrator.scheduler.cancellation import Cancellation
from buttercup.orchestrator.scheduler.status_checker import StatusChecker
from buttercup.orchestrator.scheduler.submissions import CompetitionAPI, Submissions

logger = logging.getLogger(__name__)


@dataclass
class Scheduler:
    tasks_storage_dir: Path
    scratch_dir: Path
    redis: Redis | None = None
    sleep_time: float = 1.0
    competition_api_url: str = "http://competition-api:8080"
    competition_api_key_id: str = "api_key_id"
    competition_api_key_token: str = "api_key_token"
    competition_api_cycle_time: float = 10.0  # Min seconds between competition api interactions
    patch_submission_retry_limit: int = 60
    patch_requests_per_vulnerability: int = 1
    concurrent_patch_requests_per_task: int = 12

    ready_queue: ReliableQueue | None = field(init=False, default=None)
    build_requests_queue: ReliableQueue | None = field(init=False, default=None)
    build_output_queue: ReliableQueue | None = field(init=False, default=None)
    index_queue: ReliableQueue | None = field(init=False, default=None)
    index_output_queue: ReliableQueue | None = field(init=False, default=None)
    harness_map: HarnessWeights | None = field(init=False, default=None)
    build_map: BuildMap | None = field(init=False, default=None)
    cancellation: Cancellation | None = field(init=False, default=None)
    task_registry: TaskRegistry | None = field(init=False, default=None)
    cached_cancelled_ids: set[str] = field(init=False, default_factory=set)
    status_checker: StatusChecker | None = field(init=False, default=None)
    patches_queue: ReliableQueue | None = field(init=False, default=None)
    traced_vulnerabilities_queue: ReliableQueue | None = field(init=False, default=None)
    submissions: Submissions = field(init=False)

    def update_cached_cancelled_ids(self) -> bool:
        """Update the cached set of cancelled task IDs.

        Retrieves all cancelled task IDs from the registry and stores them in the cached_cancelled_ids set.

        Returns:
            bool: True if there were any cancelled task IDs, False otherwise

        """
        if self.task_registry is None:
            return False

        # Get cancelled task IDs from registry
        cancelled_ids = set(self.task_registry.get_cancelled_task_ids())

        # Update the cached set
        self.cached_cancelled_ids = cancelled_ids

        return len(self.cached_cancelled_ids) > 0

    def should_stop_processing(self, task_or_id: str | Task) -> bool:
        """Check if a task should no longer be processed due to cancellation or expiration.

        Wrapper around the registry.should_stop_processing method that uses the cached
        cancelled IDs instead of querying the registry each time.

        Args:
            task_or_id: Either a Task object or a string task ID to check

        Returns:
            bool: True if the task should not be processed (is cancelled or expired),
                 False otherwise

        """
        if self.task_registry is None:
            return False
        return self.task_registry.should_stop_processing(task_or_id, self.cached_cancelled_ids)

    def __post_init__(self) -> None:
        if self.redis is not None:
            queue_factory = QueueFactory(self.redis)
            api_client = create_api_client(
                self.competition_api_url,
                self.competition_api_key_id,
                self.competition_api_key_token,
            )
            # Input queues are non-blocking as we're already sleeping between iterations
            self.cancellation = Cancellation(redis=self.redis)
            self.ready_queue = queue_factory.create(QueueNames.READY_TASKS, GroupNames.ORCHESTRATOR, block_time=None)
            self.build_requests_queue = queue_factory.create(QueueNames.BUILD, block_time=None)
            self.build_output_queue = queue_factory.create(
                QueueNames.BUILD_OUTPUT,
                GroupNames.ORCHESTRATOR,
                block_time=None,
            )
            self.index_queue = queue_factory.create(QueueNames.INDEX, block_time=None)
            self.index_output_queue = queue_factory.create(
                QueueNames.INDEX_OUTPUT,
                GroupNames.ORCHESTRATOR,
                block_time=None,
            )
            self.harness_map = HarnessWeights(self.redis)
            self.build_map = BuildMap(self.redis)
            self.task_registry = TaskRegistry(self.redis)
            self.status_checker = StatusChecker(self.competition_api_cycle_time)
            self.submissions = Submissions(
                redis=self.redis,
                competition_api=CompetitionAPI(api_client, self.task_registry),
                task_registry=self.task_registry,
                tasks_storage_dir=self.tasks_storage_dir,
                patch_submission_retry_limit=self.patch_submission_retry_limit,
                patch_requests_per_vulnerability=self.patch_requests_per_vulnerability,
                concurrent_patch_requests_per_task=self.concurrent_patch_requests_per_task,
            )
            self.patches_queue = queue_factory.create(QueueNames.PATCHES, GroupNames.ORCHESTRATOR, block_time=None)
            self.traced_vulnerabilities_queue = queue_factory.create(
                QueueNames.TRACED_VULNERABILITIES,
                GroupNames.ORCHESTRATOR,
                block_time=None,
            )

    def select_preferred(self, available_options: list[str], preferred_order: list[str]) -> str:
        """Select from preferred options if available, otherwise random choice.

        Args:
            available_options: List of available options to choose from
            preferred_order: List of preferred options in priority order

        Returns:
            Selected option string

        """
        for preferred in preferred_order:
            if preferred in available_options:
                return preferred
        return random.choice(available_options)

    def process_ready_task(self, task: Task) -> list[BuildRequest]:
        """Parse a task that has been downloaded and is ready to be built"""
        logger.info(f"Processing ready task {task.task_id}")

        challenge_task = ChallengeTask(self.tasks_storage_dir / task.task_id)
        logger.info(f"Processing task {task.task_id} / {task.focus}")

        project_yaml = ProjectYaml(challenge_task, task.project_name)

        engine = self.select_preferred(project_yaml.fuzzing_engines, ["libfuzzer", "afl"])
        sanitizers = project_yaml.sanitizers
        logger.info(f"Selected engine={engine}, sanitizers={sanitizers} for task {task.task_id}")

        build_types = [
            (BuildType.COVERAGE, "coverage", True),
        ]

        for san in sanitizers:
            build_types.append((BuildType.FUZZER, san, True))
            if len(challenge_task.get_diffs()) > 0:
                build_types.append((BuildType.TRACER_NO_DIFF, san, False))

        build_requests = [
            BuildRequest(
                engine=engine,
                task_dir=str(challenge_task.task_dir),
                task_id=task.task_id,
                build_type=build_type,
                sanitizer=san,
                apply_diff=apply_diff,
            )
            for build_type, san, apply_diff in build_types
        ]

        return build_requests

    def process_build_output(self, build_output: BuildOutput) -> list[WeightedHarness]:
        """Process a build output"""
        logger.info(
            f"[{build_output.task_id}] Processing build output for type "
            f"{BuildType.Name(build_output.build_type)} | {build_output.engine} | "
            f"{build_output.sanitizer} | {build_output.task_dir} | {build_output.apply_diff}",
        )

        if build_output.build_type != BuildType.FUZZER:
            return []

        # TODO(Ian): what to do if a task dir doesnt need a python path?
        tsk = ChallengeTask(read_only_task_dir=build_output.task_dir, python_path="python")

        build_dir = tsk.get_build_dir()
        targets = get_fuzz_targets(build_dir)
        logger.debug(f"Found {len(targets)} targets: {targets}")

        return [
            WeightedHarness(
                weight=1.0,
                harness_name=Path(tgt).name,
                package_name=tsk.task_meta.project_name,
                task_id=build_output.task_id,
            )
            for tgt in targets
        ]

    def serve_ready_task(self) -> bool:
        """Handle a ready task"""
        assert self.ready_queue is not None
        assert self.index_queue is not None
        assert self.build_requests_queue is not None
        task_ready_item: RQItem[TaskReady] | None = self.ready_queue.pop()

        if task_ready_item is not None:
            task_ready: TaskReady = task_ready_item.deserialized

            # Check if the task should be stopped (cancelled or expired)
            if self.should_stop_processing(task_ready.task):
                logger.info(
                    f"Skipping ready task processing for task {task_ready.task.task_id} as it is cancelled or expired",
                )
                self.ready_queue.ack_item(task_ready_item.item_id)
                return True

            try:
                # Create and push index request
                challenge_task = ChallengeTask(self.tasks_storage_dir / task_ready.task.task_id)
                index_request = IndexRequest(
                    task_id=task_ready.task.task_id,
                    task_dir=str(challenge_task.task_dir),
                    package_name=task_ready.task.project_name,
                )
                self.index_queue.push(index_request)
                logger.info(f"Pushed index request for task {task_ready.task.task_id} to index queue")

                # Process build requests
                for build_req in self.process_ready_task(task_ready.task):
                    self.build_requests_queue.push(build_req)
                    logger.info(
                        f"[{task_ready.task.task_id}] Pushed build request of type "
                        f"{BuildType.Name(build_req.build_type)} | {build_req.sanitizer} | "
                        f"{build_req.engine} | {build_req.apply_diff}",
                    )
                self.ready_queue.ack_item(task_ready_item.item_id)
                return True
            except Exception as e:
                logger.exception(f"Failed to process task {task_ready.task.task_id}: {e}")
                return False

        return False

    def _process_patched_build_output(self, build_output: BuildOutput) -> bool:
        """Process the BuildOutput for a patched build"""
        logger.info(f"Processing patched build output for task {build_output.task_id}")
        if not self.submissions.record_patched_build(build_output):
            logger.error(f"Failed to record patched build output for task {build_output.task_id}")
            return False

        return True

    def _process_regular_build_output(self, build_output: BuildOutput) -> bool:
        """Process the BuildOutput for a regular build (for fuzzing, coverage, etc.)"""
        assert self.harness_map is not None
        try:
            targets = self.process_build_output(build_output)
            for target in targets:
                self.harness_map.push_harness(target)
            logger.info(
                f"Pushed {len(targets)} targets to fuzzer map for {build_output.task_id} | "
                f"{build_output.engine} | {build_output.sanitizer} | {build_output.task_dir}",
            )
            return True
        except Exception as e:
            logger.error(
                f"Failed to process build output for {build_output.task_id} | {build_output.engine} | "
                f"{build_output.sanitizer} | {build_output.task_dir}: {e}",
            )
            return False

    def serve_build_output(self) -> bool:
        """Handle a build output"""
        assert self.build_output_queue is not None
        assert self.build_map is not None
        build_output_item = self.build_output_queue.pop()
        if build_output_item is None:
            return False

        build_output = build_output_item.deserialized

        # Check if the task should be stopped (cancelled or expired)
        if self.should_stop_processing(build_output.task_id):
            logger.info(
                f"Skipping build output processing for task {build_output.task_id} as it is cancelled or expired",
            )
            self.build_output_queue.ack_item(build_output_item.item_id)
            return True

        self.build_map.add_build(build_output)
        if build_output.build_type == BuildType.PATCH:
            res = self._process_patched_build_output(build_output)
        else:
            res = self._process_regular_build_output(build_output)

        if res:
            logger.info(
                f"Acked build output {build_output.task_id} | {build_output.engine} | "
                f"{build_output.sanitizer} | {build_output.task_dir} | {build_output.internal_patch_id}",
            )
            self.build_output_queue.ack_item(build_output_item.item_id)
            return True

        return False

    def serve_index_output(self) -> bool:
        """Handle an index output message"""
        assert self.index_output_queue is not None
        index_output_item = self.index_output_queue.pop()
        if index_output_item is not None:
            try:
                logger.info(f"Received index output for task {index_output_item.deserialized.task_id}")
                self.index_output_queue.ack_item(index_output_item.item_id)
                return True
            except Exception as e:
                logger.error(f"Failed to process index output: {e}")
                return False
        return False

    def update_expired_task_weights(self) -> bool:
        """Update weights for expired or cancelled tasks.

        Checks each harness using should_stop_processing to determine if its task is:
        1. In the cached cancelled task IDs, or
        2. Has expired according to its deadline

        If either condition is true, sets the harness weight to -1.0.
        This ensures that expired or cancelled tasks won't be selected for fuzzing.

        Returns:
            bool: True if any weights were updated, False otherwise

        """
        if not self.task_registry or not self.harness_map:
            return False

        # Get all harnesses and check if they should be updated
        harnesses = self.harness_map.list_harnesses()
        any_updated = False

        for harness in harnesses:
            # Skip harnesses that already have zero weight
            if harness.weight <= 0:
                continue

            # Check if task should be stopped using the same function as other components
            if self.should_stop_processing(harness.task_id):
                # Create a new harness with negative weight
                zero_weight_harness = WeightedHarness(
                    weight=-1.0,
                    harness_name=harness.harness_name,
                    package_name=harness.package_name,
                    task_id=harness.task_id,
                )

                # Update the harness in the map
                self.harness_map.push_harness(zero_weight_harness)

                logger.info(
                    f"Updated weight to -1.0 for cancelled/expired task {harness.task_id}, "
                    f"harness {harness.harness_name}",
                )
                any_updated = True

        return any_updated

    def competition_api_interactions(self) -> bool:
        """Process vulnerabilities and patches, and check submission statuses.

        This method:
        1. Processes any new vulnerabilities from the traced_vulnerabilities_queue,
           submitting them to the competition API
        2. Processes any new patches from the patches_queue, recording them for
           later submission once the associated vulnerability is validated
        3. Periodically checks status of submitted vulnerabilities and patches via
           the status_checker, which rate limits API calls
        4. Submits patches for vulnerabilities that have passed validation

        Returns:
            bool: True if any items were processed from the queues, False otherwise

        """
        assert self.traced_vulnerabilities_queue is not None
        assert self.patches_queue is not None
        assert self.submissions is not None
        assert self.status_checker is not None
        collected_item = False
        vuln_item: RQItem[TracedCrash] | None = self.traced_vulnerabilities_queue.pop()
        if vuln_item is not None:
            crash: TracedCrash = vuln_item.deserialized
            logger.info(f"Recording vulnerability for task {crash.crash.target.task_id}")
            if self.submissions.submit_vulnerability(crash):
                self.traced_vulnerabilities_queue.ack_item(vuln_item.item_id)
                collected_item = True

        patch_item: RQItem[Patch] | None = self.patches_queue.pop()
        if patch_item is not None:
            patch: Patch = patch_item.deserialized
            logger.info(f"Appending patch for task {patch.task_id}")
            if self.submissions.record_patch(patch):
                self.patches_queue.ack_item(patch_item.item_id)
                collected_item = True

        def do_check() -> bool:
            self.submissions.process_cycle()
            return True

        self.status_checker.check_statuses(do_check)

        return collected_item

    def serve_item(self) -> bool:
        assert self.cancellation is not None
        # Run all scheduler components and track if any did work
        # Order is important: process_cancellations should be run first,
        # followed by update_cached_cancelled_ids
        components = [
            self.cancellation.process_cancellations,
            self.update_cached_cancelled_ids,
            self.serve_ready_task,
            self.serve_build_output,
            self.serve_index_output,
            self.update_expired_task_weights,
            self.competition_api_interactions,
        ]

        # Execute each component and collect results
        # This avoids short-circuiting in any() to ensure all components are executed
        results = [component() for component in components]
        return any(results)

    def serve(self) -> None:
        """Main orchestrator loop that drives task progress forward.

        This is the central scheduling loop that coordinates all components of the orchestrator.
        On each iteration, each subcomponent gets a chance to run and make progress:

        1. Ready tasks are processed and converted to build requests
        2. Cancellation service checks for timed out or cancelled tasks
        3. Process crashes and vulnerabilities from queues
        4. Process patches and bundles from queues
        5. Check status of submitted PoVs and patches, create bundles when possible
        """
        if self.redis is None:
            raise ValueError("Redis is not initialized")

        logger.info("Starting scheduler service")
        serve_loop(self.serve_item, self.sleep_time)
