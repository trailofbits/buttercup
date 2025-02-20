from buttercup.fuzzing_infra.runner import Runner, Conf, FuzzConfiguration
import os
from buttercup.common.datastructures.msg_pb2 import WeightedHarness, Crash
from buttercup.common.maps import BUILD_TYPES
from buttercup.common.queues import QueueFactory, QueueNames
from buttercup.common import utils
from buttercup.common.corpus import Corpus, CrashDir
from buttercup.common.stack_parsing import CrashSet
import tempfile
from buttercup.common.logger import setup_package_logger
from redis import Redis
from clusterfuzz.fuzz import engine
from buttercup.common.default_task_loop import TaskLoop
from typing import List
from buttercup.common.datastructures.msg_pb2 import BuildOutput
import logging
from buttercup.common.challenge_task import ChallengeTask
from buttercup.fuzzing_infra.settings import FuzzerBotSettings

logger = logging.getLogger(__name__)


class FuzzerBot(TaskLoop):
    def __init__(self, redis: Redis, timer_seconds: int, timeout_seconds: int, wdir: str, python: str):
        self.wdir = wdir
        self.runner = Runner(Conf(timeout_seconds))
        self.output_q = QueueFactory(redis).create(QueueNames.CRASH)
        self.python = python
        super().__init__(redis, timer_seconds)

    def required_builds(self) -> List[BUILD_TYPES]:
        return [BUILD_TYPES.FUZZER]

    def run_task(self, task: WeightedHarness, builds: dict[BUILD_TYPES, BuildOutput]):
        with tempfile.TemporaryDirectory(dir=self.wdir) as td:
            logger.info(f"Running fuzzer for {task.harness_name} | {task.package_name} | {task.task_id}")

            build = builds[BUILD_TYPES.FUZZER]

            tsk = ChallengeTask(read_only_task_dir=build.task_dir, python_path=self.python)

            with tsk.get_rw_copy(work_dir=td) as local_tsk:
                logger.info(f"Build dir: {local_tsk.get_build_dir()}")

                corp = Corpus(self.wdir, task.task_id, task.harness_name)

                copied_corp_dir = os.path.join(td, corp.basename())
                utils.copyanything(corp.path, copied_corp_dir)

                build_dir = local_tsk.get_build_dir()
                fuzz_conf = FuzzConfiguration(
                    copied_corp_dir,
                    str(build_dir / task.harness_name),
                    build.engine,
                    build.sanitizer,
                )
                logger.info(f"Starting fuzzer {build.engine} | {build.sanitizer} | {task.harness_name}")
                result = self.runner.run_fuzzer(fuzz_conf)
                crash_set = CrashSet(self.redis)
                crash_dir = CrashDir(self.wdir, task.task_id, task.harness_name)
                for crash_ in result.crashes:
                    crash: engine.Crash = crash_
                    if crash_set.add(
                        task.package_name,
                        task.harness_name,
                        task.task_id,
                        crash.stacktrace,
                    ):
                        logger.info(
                            f"Crash {crash.input_path}|{crash.reproduce_args}|{crash.crash_time} already in set"
                        )
                        logger.debug(f"Crash stacktrace: {crash.stacktrace}")
                        continue
                    dst = crash_dir.copy_file(crash.input_path)
                    logger.info(f"Found unique crash {dst}")
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
    args = FuzzerBotSettings()
    setup_package_logger(__name__, args.log_level)

    os.makedirs(args.wdir, exist_ok=True)
    logger.info(f"Starting fuzzer (wdir: {args.wdir})")

    seconds_sleep = args.timer // 1000
    fuzzer = FuzzerBot(Redis.from_url(args.redis_url), seconds_sleep, args.timeout, args.wdir, args.python)
    fuzzer.run()


if __name__ == "__main__":
    main()
