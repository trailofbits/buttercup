import os
import random
import tempfile
from pathlib import Path

from redis import Redis

from buttercup.common.corpus import Corpus
from buttercup.common.datastructures.msg_pb2 import BuildOutput, WeightedHarness
from buttercup.common.default_task_loop import TaskLoop
from buttercup.common.logger import setup_logging
from buttercup.common.maps import BUILD_TYPES
from buttercup.seed_gen.tasks import Task, do_seed_init, do_vuln_discovery

logger = setup_logging(__name__, os.getenv("LOG_LEVEL", "INFO").upper())


class SeedGenBot(TaskLoop):
    def __init__(self, redis: Redis, timer_seconds: int, wdir: str):
        self.wdir = wdir
        super().__init__(redis, timer_seconds)

    def required_builds(self) -> list[BUILD_TYPES]:
        return []

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
            task_choice = random.choices([Task.SEED_INIT, Task.VULN_DISCOVERY], k=1)[0]
            logger.info(f"Running seed-gen task: {task_choice.value}")
            if task_choice == Task.SEED_INIT:
                do_seed_init(task.package_name, out_dir)
            elif task_choice == Task.VULN_DISCOVERY:
                do_vuln_discovery(task.package_name, out_dir)
            else:
                raise ValueError(f"Unexpected task: {task_choice}")

            num_files = sum(1 for _ in out_dir.iterdir())
            logger.info("Copying %d files to corpus %s", num_files, corp.corpus_dir)
            corp.copy_corpus(out_dir)
            logger.info(
                f"Seed-gen finished for {task.harness_name} | {task.package_name} | {task.task_id}"
            )
