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
    SourceDetail,
    BuildRequest,
    BuildOutput,
    WeightedHarness,
)
from buttercup.orchestrator.scheduler.cancellation import Cancellation
from buttercup.orchestrator.scheduler.vulnerabilities import Vulnerabilities
from clusterfuzz.fuzz import get_fuzz_targets

logger = logging.getLogger(__name__)


@dataclass
class Scheduler:
    tasks_storage_dir: Path
    scratch_dir: Path
    redis: Redis | None = None
    sleep_time: float = 1.0
    mock_mode: bool = False
    competition_api_url: str = "http://competition-api:8080"
    ready_queue: ReliableQueue | None = field(init=False, default=None)
    build_requests_queue: ReliableQueue | None = field(init=False, default=None)
    build_output_queue: ReliableQueue | None = field(init=False, default=None)
    harness_map: HarnessWeights | None = field(init=False, default=None)
    build_map: BuildMap | None = field(init=False, default=None)
    cancellation: Cancellation | None = field(init=False, default=None)
    vulnerabilities: Vulnerabilities | None = field(init=False, default=None)

    def __post_init__(self):
        if self.redis is not None:
            queue_factory = QueueFactory(self.redis)
            # Input queues are non-blocking as we're already sleeping between iterations
            self.cancellation = Cancellation(redis=self.redis)
            self.vulnerabilities = Vulnerabilities(redis=self.redis, competition_api_url=self.competition_api_url)
            self.ready_queue = queue_factory.create(
                QueueNames.READY_TASKS, GroupNames.SCHEDULER_READY_TASKS, block_time=None
            )
            self.build_requests_queue = queue_factory.create(QueueNames.BUILD, block_time=None)
            self.build_output_queue = queue_factory.create(
                QueueNames.BUILD_OUTPUT, GroupNames.SCHEDULER_BUILD_OUTPUT, block_time=None
            )
            self.harness_map = HarnessWeights(self.redis)
            self.build_map = BuildMap(self.redis)

    def mock_process_ready_task(self, task: Task) -> BuildRequest:
        """Mock a ready task processing"""
        repo_source = next(
            (source for source in task.sources if source.source_type == SourceDetail.SourceType.SOURCE_TYPE_REPO), None
        )
        if repo_source is not None:
            challenge_task = ChallengeTask(self.tasks_storage_dir / task.task_id, "example-libpng")
            if challenge_task.get_source_path().is_dir():
                logger.info(f"Mocking task {task.task_id} / example-libpng")
                return [
                    BuildRequest(
                        package_name="libpng",
                        engine="libfuzzer",
                        sanitizer="address",
                        ossfuzz=f"/tasks_storage/{task.task_id}/fuzz-tooling/fuzz-tooling",
                        source_path=f"/tasks_storage/{task.task_id}/src/example-libpng",
                        task_id=task.task_id,
                        build_type=BUILD_TYPES.FUZZER,
                    ),
                    BuildRequest(
                        package_name="libpng",
                        engine="libfuzzer",
                        sanitizer="coverage",
                        ossfuzz=f"/tasks_storage/{task.task_id}/fuzz-tooling/fuzz-tooling",
                        source_path=f"/tasks_storage/{task.task_id}/src/example-libpng",
                        task_id=task.task_id,
                        build_type=BUILD_TYPES.COVERAGE,
                    ),
                ]
            logger.info(f"{challenge_task.get_source_path()} does not exist")

        raise RuntimeError(f"Couldn't handle task {task.task_id}")

    def process_ready_task(self, task: Task) -> list[BuildRequest]:
        """Parse a task that has been downloaded and is ready to be built"""
        logger.info(f"Processing ready task {task.task_id}")
        if self.mock_mode:
            logger.info(f"Mock mode enabled, checking if {task.task_id} can be mocked")
            return self.mock_process_ready_task(task)

        raise RuntimeError(f"Couldn't handle task {task.task_id}")

    def process_build_output(self, build_output: BuildOutput) -> list[WeightedHarness]:
        """Process a build output"""
        logger.info(
            f"Processing build output for {build_output.package_name}|{build_output.engine}|{build_output.sanitizer}|{build_output.output_ossfuzz_path}"
        )

        if build_output.build_type != BUILD_TYPES.FUZZER.value:
            return []

        build_dir = Path(build_output.output_ossfuzz_path) / "build" / "out" / build_output.package_name
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
                    logger.info(f"Pushed build request for task {task_ready.task.task_id} to build requests queue")
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
                    f"Pushed {len(targets)} targets to fuzzer map for {build_output.package_name} | {build_output.engine} | {build_output.sanitizer} | {build_output.source_path}"
                )
                return True
            except Exception as e:
                logger.error(
                    f"Failed to process build output for {build_output.package_name} | {build_output.engine} | {build_output.sanitizer} | {build_output.source_path}: {e}"
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
                self.vulnerabilities.process_crashes,
                self.vulnerabilities.process_unique_vulnerabilities,
            ]
            did_work = any(component() for component in components)
