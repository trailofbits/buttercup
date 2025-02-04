import argparse
from buttercup.fuzzing_infra.runner import Runner, Conf, FuzzConfiguration
import time
import os
from buttercup.common.datastructures.msg_pb2 import WeightedHarness, Crash
from buttercup.common.maps import HarnessWeights, BuildMap, BUILD_TYPES
from buttercup.common.queues import QueueFactory, QueueNames, GroupNames
from buttercup.common import utils
from buttercup.common.corpus import Corpus, CrashDir
from buttercup.fuzzing_infra.stack_parsing import CrashSet
import random
import tempfile
from buttercup.common.logger import setup_logging
from redis import Redis
from clusterfuzz.fuzz import engine
from buttercup.common.default_task_loop import TaskLoop
from typing import List
from buttercup.common.datastructures.msg_pb2 import BuildOutput

logger = setup_logging(__name__)



class FuzzerBot(TaskLoop):
    def __init__(self, redis: Redis, timer_seconds: int, timeout_seconds: int, wdir: str):
        self.wdir = wdir
        self.runner = Runner(Conf(timeout_seconds))
        self.output_q = QueueFactory(redis).create(QueueNames.CRASH, GroupNames.ORCHESTRATOR)

        super().__init__(redis, timer_seconds)

    def required_builds(self) -> List[BUILD_TYPES]:
        return [BUILD_TYPES.FUZZER]

    def run_task(self, task: WeightedHarness, builds: dict[BUILD_TYPES, BuildOutput]):
        with tempfile.TemporaryDirectory(dir=self.wdir) as td:
            logger.info(f"Running fuzzer for {task.harness_name} | {task.package_name} | {task.task_id}")

            build = builds[BUILD_TYPES.FUZZER]
            logger.info(f"Build dir: {build.output_ossfuzz_path}")

            build_dir = os.path.join(build.output_ossfuzz_path, "build/out/", build.package_name)
            corp = Corpus(self.wdir, task.task_id, task.harness_name)

            copied_build_dir = os.path.join(td, os.path.basename(build_dir))
            copied_corp_dir = os.path.join(copied_build_dir, corp.basename())
            utils.copyanything(build_dir, copied_build_dir)
            utils.copyanything(corp.path, copied_corp_dir)

            fuzz_conf = FuzzConfiguration(
                copied_corp_dir,
                os.path.join(copied_build_dir, task.harness_name),
                build.engine,
                build.sanitizer,
            )
            logger.info(f"Starting fuzzer {build.engine} | {build.sanitizer} | {task.harness_name}")
            result = self.runner.run_fuzzer(fuzz_conf)
            crash_set = CrashSet(self.redis)
            crash_dir = CrashDir(self.wdir, task.task_id, task.harness_name)
            for crash_ in result.crashes:
                crash: engine.Crash = crash_
                dst = crash_dir.copy_file(crash.input_path)
                logger.info(f"Found crash {dst}")
                if crash_set.add(
                    task.package_name,
                    task.harness_name,
                    task.task_id,
                    crash.stacktrace,
                ):
                    logger.info(f"Crash {crash.stacktrace} already in set")
                    continue
                crash = Crash(
                    target=build,
                    harness_name=task.harness_name,
                    crash_input_path=dst,
                    stacktrace=crash.stacktrace,
                )
                self.output_q.push(crash)

            corp.copy_corpus(copied_corp_dir)
            logger.info(f"Fuzzer finished for {build.engine} | {build.sanitizer} | {task.harness_name}")


def main():
    prsr = argparse.ArgumentParser("fuzz bot")
    prsr.add_argument("--timeout", required=True, type=int)
    prsr.add_argument("--timer", default=1000, type=int)
    prsr.add_argument("--redis_url", default="redis://127.0.0.1:6379")
    prsr.add_argument("--wdir", required=True)

    args = prsr.parse_args()

    os.makedirs(args.wdir, exist_ok=True)
    logger.info(f"Starting fuzzer (wdir: {args.wdir})")

    
    seconds_sleep = args.timer // 1000
    fuzzer = FuzzerBot(Redis.from_url(args.redis_url), seconds_sleep, args.timeout, args.wdir)
    fuzzer.run()
 

if __name__ == "__main__":
    main()
