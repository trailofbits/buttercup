import logging
import os
import random
import tempfile
from pathlib import Path

from redis import Redis

from buttercup.common.challenge_task import ChallengeTask
from buttercup.common.corpus import Corpus, CrashDir
from buttercup.common.datastructures.aliases import BuildType as BuildTypeHint
from buttercup.common.datastructures.msg_pb2 import BuildOutput, BuildType, WeightedHarness
from buttercup.common.default_task_loop import TaskLoop
from buttercup.common.project_yaml import ProjectYaml
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
from buttercup.seed_gen.vuln_base_task import CrashSubmit
from buttercup.seed_gen.vuln_discovery_delta import VulnDiscoveryDeltaTask
from buttercup.seed_gen.vuln_discovery_full import VulnDiscoveryFullTask

logger = logging.getLogger(__name__)


class SeedGenBot(TaskLoop):
    TASK_SEED_INIT_PROB_FULL = 0.05
    TASK_VULN_DISCOVERY_PROB_FULL = 0.35
    TASK_SEED_EXPLORE_PROB_FULL = 0.60

    TASK_SEED_INIT_PROB_DELTA = 0.05
    TASK_VULN_DISCOVERY_PROB_DELTA = 0.45
    TASK_SEED_EXPLORE_PROB_DELTA = 0.50

    MIN_SEED_INIT_RUNS = 3
    MIN_VULN_DISCOVERY_RUNS = 1

    def __init__(
        self,
        redis: Redis,
        timer_seconds: int,
        wdir: str,
        max_corpus_seed_size: int,
        max_pov_size: int,
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
        self.max_corpus_seed_size = max_corpus_seed_size
        self.max_pov_size = max_pov_size
        super().__init__(redis, timer_seconds)

    def required_builds(self) -> list[BuildTypeHint]:
        return [BuildType.FUZZER]

    def sample_task(self, task: WeightedHarness, is_delta: bool) -> str:
        """Sample a task to run

        Prioritizes seed-init and vuln-discovery if they haven't been run enough times.

        Args:
            task: The WeightedHarness task to sample for
            is_delta: Whether the challenge is in delta mode

        Returns:
            The selected task name
        """
        # Check if seed-init has been run enough times
        seed_init_count = self.task_counter.get_count(
            task.harness_name, task.package_name, task.task_id, TaskName.SEED_INIT.value
        )

        if seed_init_count < self.MIN_SEED_INIT_RUNS:
            logger.info(f"seed-init has only been run {seed_init_count} times, forcing task")
            return TaskName.SEED_INIT.value

        # Check if vuln-discovery has been run enough times
        vuln_discovery_count = self.task_counter.get_count(
            task.harness_name, task.package_name, task.task_id, TaskName.VULN_DISCOVERY.value
        )

        if vuln_discovery_count < self.MIN_VULN_DISCOVERY_RUNS:
            logger.info(
                f"vuln-discovery has only been run {vuln_discovery_count} times, forcing task"
            )
            return TaskName.VULN_DISCOVERY.value

        # If SEED_INIT has been run enough times, use normal probability distribution
        if is_delta:
            task_distribution = [
                (TaskName.SEED_INIT.value, self.TASK_SEED_INIT_PROB_DELTA),
                (TaskName.VULN_DISCOVERY.value, self.TASK_VULN_DISCOVERY_PROB_DELTA),
                (TaskName.SEED_EXPLORE.value, self.TASK_SEED_EXPLORE_PROB_DELTA),
            ]
        else:
            task_distribution = [
                (TaskName.SEED_INIT.value, self.TASK_SEED_INIT_PROB_FULL),
                (TaskName.VULN_DISCOVERY.value, self.TASK_VULN_DISCOVERY_PROB_FULL),
                (TaskName.SEED_EXPLORE.value, self.TASK_SEED_EXPLORE_PROB_FULL),
            ]

        tasks, weights = zip(*task_distribution)
        return random.choices(tasks, weights=weights, k=1)[0]

    def run_task(self, task: WeightedHarness, builds: dict[BuildTypeHint, list[BuildOutput]]):
        build_dir = Path(builds[BuildType.FUZZER][0].task_dir)
        ro_challenge_task = ChallengeTask(read_only_task_dir=build_dir)
        project_yaml = ProjectYaml(ro_challenge_task, task.package_name)
        task_id = ro_challenge_task.task_meta.task_id

        with (
            tempfile.TemporaryDirectory(dir=self.wdir / task_id, prefix="seedgen-") as temp_dir_str,
            ro_challenge_task.get_rw_copy(work_dir=temp_dir_str) as challenge_task,
        ):
            logger.info(
                f"Running seed-gen for {task.harness_name} | {task.package_name} | {task.task_id}"
            )
            temp_dir = Path(temp_dir_str)
            logger.debug(f"Temp dir: {temp_dir}")
            out_dir = temp_dir / "seedgen-out"
            out_dir.mkdir()
            current_dir = temp_dir / "seedgen-current"
            current_dir.mkdir()

            logger.info("Initializing codequery")
            try:
                codequery = CodeQueryPersistent(challenge_task, work_dir=Path(self.wdir))
            except Exception as e:
                logger.exception(f"Failed to initialize codequery: {e}.")
                return

            corp = Corpus(
                self.wdir,
                task.task_id,
                task.harness_name,
                copy_corpus_max_size=self.max_corpus_seed_size,
            )
            override_task = os.getenv("BUTTERCUP_SEED_GEN_TEST_TASK")
            if override_task:
                logger.info("Only testing task: %s", override_task)
            is_delta = challenge_task.is_delta_mode()
            task_choice = override_task if override_task else self.sample_task(task, is_delta)

            logger.info(f"Running seed-gen task: {task_choice}")

            # Increment the counter for this task run
            self.task_counter.increment(
                task.harness_name, task.package_name, task.task_id, task_choice
            )

            if task_choice == TaskName.SEED_INIT.value:
                seed_init = SeedInitTask(
                    task.package_name,
                    task.harness_name,
                    challenge_task,
                    codequery,
                    project_yaml,
                    self.redis,
                )
                seed_init.do_task(out_dir)
            elif task_choice == TaskName.VULN_DISCOVERY.value:
                sarif_store = SARIFStore(self.redis)
                sarifs = sarif_store.get_by_task_id(challenge_task.task_meta.task_id)
                fbuilds = builds[BuildType.FUZZER]
                reproduce_multiple = ReproduceMultiple(temp_dir, fbuilds)
                crash_submit = CrashSubmit(
                    crash_queue=self.crash_queue,
                    crash_set=self.crash_set,
                    crash_dir=CrashDir(
                        self.wdir,
                        task.task_id,
                        task.harness_name,
                        count_limit=self.crash_dir_count_limit,
                    ),
                    max_pov_size=self.max_pov_size,
                )
                with reproduce_multiple.open() as mult:
                    if is_delta:
                        vuln_discovery = VulnDiscoveryDeltaTask(
                            task.package_name,
                            task.harness_name,
                            challenge_task,
                            codequery,
                            project_yaml,
                            self.redis,
                            mult,
                            sarifs,
                            crash_submit=crash_submit,
                        )
                    else:
                        vuln_discovery = VulnDiscoveryFullTask(
                            task.package_name,
                            task.harness_name,
                            challenge_task,
                            codequery,
                            project_yaml,
                            self.redis,
                            mult,
                            sarifs,
                            crash_submit=crash_submit,
                        )
                    vuln_discovery.do_task(out_dir, current_dir)
            elif task_choice == TaskName.SEED_EXPLORE.value:
                seed_explore = SeedExploreTask(
                    task.package_name,
                    task.harness_name,
                    challenge_task,
                    codequery,
                    project_yaml,
                    self.redis,
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

            copied_files = corp.copy_corpus(out_dir)
            logger.info("Copied %d files to corpus %s", len(copied_files), corp.corpus_dir)
            logger.info(
                f"Seed-gen finished for {task.harness_name} | {task.package_name} | {task.task_id}"
            )
