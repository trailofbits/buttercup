import logging
import os
import random
import tempfile
from pathlib import Path

from redis import Redis

from buttercup.common.challenge_task import ChallengeTask, ChallengeTaskError, ReproduceResult
from buttercup.common.corpus import Corpus, CrashDir
from buttercup.common.datastructures.msg_pb2 import BuildOutput, Crash, WeightedHarness
from buttercup.common.default_task_loop import TaskLoop
from buttercup.common.maps import BUILD_TYPES
from buttercup.common.queues import QueueFactory, QueueNames
from buttercup.common.stack_parsing import CrashSet
from buttercup.seed_gen.tasks import Task, do_seed_init, do_vuln_discovery

logger = logging.getLogger(__name__)


class SeedGenBot(TaskLoop):
    def __init__(self, redis: Redis, timer_seconds: int, wdir: str, python: str):
        self.wdir = wdir
        self.python = python
        self.crash_set = CrashSet(redis)
        self.crash_queue = QueueFactory(redis).create(QueueNames.CRASH)
        super().__init__(redis, timer_seconds)

    def required_builds(self) -> list[BUILD_TYPES]:
        return [BUILD_TYPES.FUZZER]

    def submit_valid_povs(
        self,
        task: WeightedHarness,
        builds: dict[BUILD_TYPES, BuildOutput],
        out_dir: Path,
        temp_dir: Path,
    ):
        build = builds[BUILD_TYPES.FUZZER]
        chall_task = ChallengeTask(
            read_only_task_dir=build.task_dir,
            project_name=build.package_name,
            python_path=self.python,
        )
        crash_dir = CrashDir(self.wdir, task.task_id, task.harness_name)
        with chall_task.get_rw_copy(work_dir=temp_dir) as rw_task:
            for pov in out_dir.iterdir():
                try:
                    pov_output: ReproduceResult = rw_task.reproduce_pov(task.harness_name, pov)
                    if pov_output.did_crash():
                        logger.info(f"Valid PoV found: {pov}")
                        stacktrace = pov_output.stacktrace()
                        if stacktrace is None:
                            logger.error("Stacktrace is empty for PoV, skipping.")
                            continue
                        if self.crash_set.add(
                            task.package_name,
                            task.harness_name,
                            task.task_id,
                            stacktrace,
                        ):
                            logger.info(f"PoV with crash {stacktrace} already in crash set")
                            continue
                        logger.info("Submitting PoV to crash queue")
                        dst = crash_dir.copy_file(pov)
                        crash = Crash(
                            target=build,
                            harness_name=task.harness_name,
                            crash_input_path=dst,
                            stacktrace=stacktrace,
                        )
                        self.crash_queue.push(crash)
                    else:
                        logger.info(f"Not valid PoV: {pov}")
                    logger.debug("PoV stdout: %s", pov_output.command_result.output)
                    logger.debug("PoV stderr: %s", pov_output.command_result.error)
                except ChallengeTaskError as exc:
                    logger.error(f"Error reproducing PoV {pov}: {exc}")

    def run_task(self, task: WeightedHarness, builds: dict[BUILD_TYPES, BuildOutput]):
        with tempfile.TemporaryDirectory(dir=self.wdir, prefix="seedgen-") as temp_dir_str:
            logger.info(
                f"Running seed-gen for {task.harness_name} | {task.package_name} | {task.task_id}"
            )
            temp_dir = Path(temp_dir_str)
            logger.debug(f"Temp dir: {temp_dir}")
            out_dir = temp_dir / "seedgen-out"
            out_dir.mkdir()

            corp = Corpus(self.wdir, task.task_id, task.harness_name)
            choices = [Task.SEED_INIT, Task.VULN_DISCOVERY]
            if os.getenv("BUTTERCUP_TEST_VULN_DISCOVERY"):
                logger.info("Only testing vuln discovery")
                choices = [Task.VULN_DISCOVERY]
            task_choice = random.choices(choices, k=1)[0]
            logger.info(f"Running seed-gen task: {task_choice.value}")
            if task_choice == Task.SEED_INIT:
                do_seed_init(task.package_name, out_dir)
            elif task_choice == Task.VULN_DISCOVERY:
                do_vuln_discovery(task.package_name, out_dir)
                self.submit_valid_povs(task, builds, out_dir, temp_dir)
            else:
                raise ValueError(f"Unexpected task: {task_choice}")

            num_files = sum(1 for _ in out_dir.iterdir())
            logger.info("Copying %d files to corpus %s", num_files, corp.corpus_dir)
            corp.copy_corpus(out_dir)
            logger.info(
                f"Seed-gen finished for {task.harness_name} | {task.package_name} | {task.task_id}"
            )
