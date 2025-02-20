import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from redis import Redis
from buttercup.common.queues import ReliableQueue, QueueFactory, RQItem, QueueNames, GroupNames
from buttercup.common.maps import HarnessWeights, BuildMap, BUILD_TYPES
from buttercup.common.challenge_task import ChallengeTask
from buttercup.common.datastructures.msg_pb2 import (
    TaskReady,
    Task,
    BuildRequest,
    BuildOutput,
    WeightedHarness,
)
from buttercup.common.project_yaml import ProjectYaml
from buttercup.common.task_meta import TaskMeta
from buttercup.orchestrator.scheduler.cancellation import Cancellation
from buttercup.orchestrator.scheduler.vulnerabilities import Vulnerabilities
from clusterfuzz.fuzz import get_fuzz_targets
from buttercup.orchestrator.scheduler.patches import Patches
from buttercup.orchestrator.api_client_factory import create_api_client
import random


logger = logging.getLogger(__name__)


@dataclass
class Scheduler:
    tasks_storage_dir: Path
    scratch_dir: Path
    redis: Redis | None = None
    sleep_time: float = 1.0
    competition_api_url: str = "http://competition-api:8080"
    ready_queue: ReliableQueue | None = field(init=False, default=None)
    build_requests_queue: ReliableQueue | None = field(init=False, default=None)
    build_output_queue: ReliableQueue | None = field(init=False, default=None)
    harness_map: HarnessWeights | None = field(init=False, default=None)
    build_map: BuildMap | None = field(init=False, default=None)
    cancellation: Cancellation | None = field(init=False, default=None)
    vulnerabilities: Vulnerabilities | None = field(init=False, default=None)
    patches: Patches = field(init=False)

    def __post_init__(self):
        if self.redis is not None:
            queue_factory = QueueFactory(self.redis)
            api_client = create_api_client(self.competition_api_url)
            # Input queues are non-blocking as we're already sleeping between iterations
            self.cancellation = Cancellation(redis=self.redis)
            self.vulnerabilities = Vulnerabilities(redis=self.redis, api_client=api_client)
            self.ready_queue = queue_factory.create(QueueNames.READY_TASKS, GroupNames.ORCHESTRATOR, block_time=None)
            self.build_requests_queue = queue_factory.create(QueueNames.BUILD, block_time=None)
            self.build_output_queue = queue_factory.create(
                QueueNames.BUILD_OUTPUT, GroupNames.ORCHESTRATOR, block_time=None
            )
            self.harness_map = HarnessWeights(self.redis)
            self.build_map = BuildMap(self.redis)
            self.patches = Patches(redis=self.redis, api_client=api_client)

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

        # Store the task meta in the tasks storage directory
        task_meta = TaskMeta(task.project_name, task.focus)
        task_meta.save(self.tasks_storage_dir / task.task_id)

        challenge_task = ChallengeTask(self.tasks_storage_dir / task.task_id)
        if challenge_task.get_source_path().is_dir():
            logger.info(f"Processing task {task.task_id} / {task.focus}")

            project_yaml = ProjectYaml(challenge_task, task.project_name)

            engine = self.select_preferred(project_yaml.fuzzing_engines, ["libfuzzer", "afl"])
            sanitizers = project_yaml.sanitizers
            logger.info(f"Selected engine={engine}, sanitizers={sanitizers} for task {task.task_id}")

            build_types = [
                (BUILD_TYPES.COVERAGE, "coverage", True),
            ]

            for san in sanitizers:
                build_types.append((BUILD_TYPES.FUZZER, san, True))
                if len(challenge_task.get_diffs()) > 0:
                    build_types.append((BUILD_TYPES.TRACER_NO_DIFF, san, False))

            build_requests = [
                BuildRequest(
                    package_name=task.project_name,
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
        logger.info(f"{challenge_task.get_source_path()} does not exist")

        raise RuntimeError(f"Couldn't handle task {task.task_id}")

    def process_build_output(self, build_output: BuildOutput) -> list[WeightedHarness]:
        """Process a build output"""
        logger.info(
            f"Processing build output for {build_output.package_name}|{build_output.engine}|{build_output.sanitizer}|{build_output.task_dir}"
        )

        if build_output.build_type != BUILD_TYPES.FUZZER.value:
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
                package_name=build_output.package_name,
                task_id=build_output.task_id,
            )
            for tgt in targets
        ]

    def serve_ready_task(self) -> bool:
        """Handle a ready task"""
        task_ready_item: RQItem[TaskReady] | None = self.ready_queue.pop()

        if task_ready_item is not None:
            task_ready: TaskReady = task_ready_item.deserialized
            try:
                for build_req in self.process_ready_task(task_ready.task):
                    self.build_requests_queue.push(build_req)
                    logger.info(
                        f"Pushed build request of type {build_req.build_type} for task {task_ready.task.task_id} to build requests queue"
                    )
                self.ready_queue.ack_item(task_ready_item.item_id)
                return True
            except Exception as e:
                logger.exception(f"Failed to process task {task_ready.task.task_id}: {e}")
                return False

        return False

    def serve_build_output(self) -> bool:
        """Handle a build output"""
        build_output_item: RQItem[BuildOutput] | None = self.build_output_queue.pop()
        if build_output_item is not None:
            build_output: BuildOutput = build_output_item.deserialized
            self.build_map.add_build(build_output)
            try:
                targets = self.process_build_output(build_output)
                for target in targets:
                    self.harness_map.push_harness(target)
                self.build_output_queue.ack_item(build_output_item.item_id)
                logger.info(
                    f"Pushed {len(targets)} targets to fuzzer map for {build_output.package_name} | {build_output.engine} | {build_output.sanitizer} | {build_output.task_dir}"
                )
                return True
            except Exception as e:
                logger.error(
                    f"Failed to process build output for {build_output.package_name} | {build_output.engine} | {build_output.sanitizer} | {build_output.task_dir}: {e}"
                )
                return False

        return False

    def serve(self):
        """Main orchestrator loop that drives task progress forward.

        This is the central scheduling loop that coordinates all components of the orchestrator.
        On each iteration, each subcomponent gets a chance to run and make progress:

        1. Ready tasks are processed and converted to build requests
        2. Cancellation service checks for timed out or cancelled tasks
        3. Process crashes and vulnerabilities from queues
        """
        if self.redis is None:
            raise ValueError("Redis is not initialized")

        logger.info("Starting scheduler service")

        did_work = False
        while True:
            if not did_work:
                # Sleep first to prevent busy waiting in case of exceptions in the loop
                logger.info(f"Sleeping for {self.sleep_time} seconds")
                time.sleep(self.sleep_time)

            # Reset work tracker
            did_work = False

            # Run all scheduler components and track if any did work
            components = [
                self.serve_ready_task,
                self.serve_build_output,
                self.cancellation.process_cancellations,
                self.vulnerabilities.process_traced_vulnerabilities,
                self.patches.process_patches,
            ]
            did_work = any(component() for component in components)
