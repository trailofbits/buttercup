import logging
import os
import random
import tempfile
from pathlib import Path

from redis import Redis

from buttercup.common import stack_parsing
from buttercup.common.challenge_task import ChallengeTask, ChallengeTaskError
from buttercup.common.corpus import Corpus, CrashDir
from buttercup.common.datastructures.aliases import BuildType as BuildTypeHint
from buttercup.common.datastructures.msg_pb2 import BuildOutput, BuildType, Crash, WeightedHarness
from buttercup.common.default_task_loop import TaskLoop
from buttercup.common.queues import QueueFactory, QueueNames
from buttercup.common.reproduce_multiple import ReproduceMultiple
from buttercup.common.sarif_store import SARIFStore
from buttercup.common.stack_parsing import CrashSet
from buttercup.program_model.codequery import CodeQueryPersistent
from buttercup.seed_gen.function_selector import FunctionSelector
from buttercup.seed_gen.seed_explore import SeedExploreTask
from buttercup.seed_gen.seed_init import SeedInitTask
from buttercup.seed_gen.task import TaskName
from buttercup.seed_gen.task_counter import TaskCounter
from buttercup.seed_gen.vuln_discovery_delta import VulnDiscoveryDeltaTask
from buttercup.seed_gen.vuln_discovery_full import VulnDiscoveryFullTask

logger = logging.getLogger(__name__)


class SeedGenBot(TaskLoop):
    TASK_SEED_INIT_PROB = 0.1
    TASK_VULN_DISCOVERY_PROB = 0.3
    TASK_SEED_EXPLORE_PROB = 0.6
    MIN_SEED_INIT_RUNS = 3

    def __init__(
        self,
        redis: Redis,
        timer_seconds: int,
        wdir: str,
        crash_dir_count_limit: int | None = None,
        corpus_root: str | None = None,
    ):
        self.wdir = wdir
        self.corpus_root = corpus_root
        self.redis = redis
        self.crash_set = CrashSet(redis)
        self.crash_queue = QueueFactory(redis).create(QueueNames.CRASH)
        self.task_counter = TaskCounter(redis)
        self.crash_dir_count_limit = crash_dir_count_limit
        super().__init__(redis, timer_seconds)

    def required_builds(self) -> list[BuildTypeHint]:
        return [BuildType.FUZZER]

    def sample_task(self, task: WeightedHarness) -> str:
        """Sample a task to run, prioritizing SEED_INIT if it hasn't been run enough times.

        Args:
            task: The WeightedHarness task to sample for

        Returns:
            The selected task name
        """
        # Check if SEED_INIT has been run enough times
        seed_init_count = self.task_counter.get_count(
            task.harness_name, task.package_name, task.task_id, TaskName.SEED_INIT.value
        )

        if seed_init_count < self.MIN_SEED_INIT_RUNS:
            logger.info(
                f"SEED_INIT has only been run {seed_init_count} times, forcing SEED_INIT task"
            )
            return TaskName.SEED_INIT.value

        # If SEED_INIT has been run enough times, use normal probability distribution
        task_distribution = [
            (TaskName.SEED_INIT.value, self.TASK_SEED_INIT_PROB),
            (TaskName.VULN_DISCOVERY.value, self.TASK_VULN_DISCOVERY_PROB),
            (TaskName.SEED_EXPLORE.value, self.TASK_SEED_EXPLORE_PROB),
        ]
        tasks, weights = zip(*task_distribution)
        return random.choices(tasks, weights=weights, k=1)[0]

    def submit_valid_povs(
        self,
        task: WeightedHarness,
        builds: dict[BuildTypeHint, BuildOutput],
        out_dir: Path,
        temp_dir: Path,
    ):
        fbuilds = builds[BuildType.FUZZER]
        reproduce_multiple = ReproduceMultiple(temp_dir, fbuilds)

        crash_dir = CrashDir(
            self.wdir, task.task_id, task.harness_name, count_limit=self.crash_dir_count_limit
        )

        with reproduce_multiple.open() as mult:
            for pov in out_dir.iterdir():
                try:
                    pov_output = mult.get_first_crash(pov, task.harness_name)
                    if pov_output is not None:
                        build, result = pov_output
                        logger.info(f"Valid PoV found: {pov}")
                        stacktrace = result.stacktrace()
                        ctoken = stack_parsing.get_crash_data(stacktrace)
                        dst = crash_dir.copy_file(pov, ctoken)
                        if self.crash_set.add(
                            task.package_name,
                            task.harness_name,
                            task.task_id,
                            stacktrace,
                        ):
                            logger.info(f"PoV with crash {stacktrace} already in crash set")
                            continue
                        logger.info("Submitting PoV to crash queue")

                        crash = Crash(
                            target=build,
                            harness_name=task.harness_name,
                            crash_input_path=dst,
                            stacktrace=stacktrace,
                        )
                        self.crash_queue.push(crash)

                        logger.debug("PoV stdout: %s", result.command_result.output)
                        logger.debug("PoV stderr: %s", result.command_result.error)
                except ChallengeTaskError as exc:
                    logger.error(f"Error reproducing PoV {pov}: {exc}")

    def run_task(self, task: WeightedHarness, builds: dict[BuildTypeHint, list[BuildOutput]]):
        with tempfile.TemporaryDirectory(dir=self.wdir, prefix="seedgen-") as temp_dir_str:
            logger.info(
                f"Running seed-gen for {task.harness_name} | {task.package_name} | {task.task_id}"
            )
            temp_dir = Path(temp_dir_str)
            logger.debug(f"Temp dir: {temp_dir}")
            out_dir = temp_dir / "seedgen-out"
            out_dir.mkdir()

            build_dir = Path(builds[BuildType.FUZZER][0].task_dir)
            challenge_task = ChallengeTask(read_only_task_dir=build_dir)
            logger.info("Initializing codequery")
            codequery = CodeQueryPersistent(challenge_task, work_dir=Path(self.wdir))

            corp = Corpus(self.wdir, task.task_id, task.harness_name)

            override_task = os.getenv("BUTTERCUP_SEED_GEN_TEST_TASK")
            if override_task:
                logger.info("Only testing task: %s", override_task)
            task_choice = override_task if override_task else self.sample_task(task)

            logger.info(f"Running seed-gen task: {task_choice}")

            # Increment the counter for this task run
            self.task_counter.increment(
                task.harness_name, task.package_name, task.task_id, task_choice
            )

            if task_choice == TaskName.SEED_INIT.value:
                seed_init = SeedInitTask(
                    task.package_name, task.harness_name, challenge_task, codequery
                )
                seed_init.do_task(out_dir)
            elif task_choice == TaskName.VULN_DISCOVERY.value:
                sarif_store = SARIFStore(self.redis)
                sarifs = sarif_store.get_by_task_id(challenge_task.task_meta.task_id)
                if challenge_task.is_delta_mode():
                    vuln_discovery = VulnDiscoveryDeltaTask(
                        task.package_name,
                        task.harness_name,
                        challenge_task,
                        codequery,
                        sarifs,
                    )
                    vuln_discovery.do_task(out_dir)
                else:
                    vuln_discovery = VulnDiscoveryFullTask(
                        task.package_name,
                        task.harness_name,
                        challenge_task,
                        codequery,
                        sarifs,
                    )
                    vuln_discovery.do_task(out_dir)
                self.submit_valid_povs(task, builds, out_dir, temp_dir)
            elif task_choice == TaskName.SEED_EXPLORE.value:
                seed_explore = SeedExploreTask(
                    task.package_name, task.harness_name, challenge_task, codequery
                )

                function_selector = FunctionSelector(self.redis)
                selected_function = function_selector.sample_function(task)

                if selected_function is None:
                    logger.error("No function selected from coverage data, canceling seed-explore")
                    return

                function_name = selected_function.function_name
                function_paths = [Path(path_str) for path_str in selected_function.function_paths]

                seed_explore.do_task(function_name, function_paths, out_dir)
            else:
                raise ValueError(f"Unexpected task: {task_choice}")

            num_files = sum(1 for _ in out_dir.iterdir())
            logger.info("Copying %d files to corpus %s", num_files, corp.corpus_dir)
            corp.copy_corpus(out_dir)
            logger.info(
                f"Seed-gen finished for {task.harness_name} | {task.package_name} | {task.task_id}"
            )
