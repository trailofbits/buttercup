from buttercup.fuzzing_infra.runner import Runner, Conf, FuzzConfiguration
import os
from buttercup.common.datastructures.msg_pb2 import BuildType, WeightedHarness, Crash
from buttercup.common.datastructures.aliases import BuildType as BuildTypeHint
from buttercup.common.queues import QueueFactory, QueueNames
from buttercup.common.corpus import Corpus, CrashDir
from buttercup.common import stack_parsing
from buttercup.common.stack_parsing import CrashSet
import tempfile
from buttercup.common.logger import setup_package_logger
from redis import Redis
from clusterfuzz.fuzz import engine
from buttercup.common.default_task_loop import TaskLoop
from typing import List
import random
from buttercup.common.datastructures.msg_pb2 import BuildOutput
import logging
from buttercup.common.challenge_task import ChallengeTask
from buttercup.fuzzing_infra.settings import FuzzerBotSettings
from buttercup.common.telemetry import init_telemetry, log_crs_action_ok, CRSActionCategory
from opentelemetry import trace

logger = logging.getLogger(__name__)


class FuzzerBot(TaskLoop):
    def __init__(
        self,
        redis: Redis,
        timer_seconds: int,
        timeout_seconds: int,
        wdir: str,
        python: str,
        crs_scratch_dir: str,
        crash_dir_count_limit: int | None,
    ):
        self.wdir = wdir
        self.runner = Runner(Conf(timeout_seconds))
        self.output_q = QueueFactory(redis).create(QueueNames.CRASH)
        self.python = python
        self.crs_scratch_dir = crs_scratch_dir
        self.crash_dir_count_limit = crash_dir_count_limit
        super().__init__(redis, timer_seconds)

    def required_builds(self) -> List[BuildTypeHint]:
        return [BuildType.FUZZER]

    def run_task(self, task: WeightedHarness, builds: dict[BuildTypeHint, BuildOutput]):
        with tempfile.TemporaryDirectory(dir=self.wdir) as td:
            logger.info(f"Running fuzzer for {task.harness_name} | {task.package_name} | {task.task_id}")

            build = random.choice(builds[BuildType.FUZZER])

            tsk = ChallengeTask(read_only_task_dir=build.task_dir, python_path=self.python)

            with tsk.get_rw_copy(work_dir=td) as local_tsk:
                logger.info(f"Build dir: {local_tsk.get_build_dir()}")

                corp = Corpus(self.crs_scratch_dir, task.task_id, task.harness_name)

                build_dir = local_tsk.get_build_dir()
                fuzz_conf = FuzzConfiguration(
                    corp.path,
                    str(build_dir / task.harness_name),
                    build.engine,
                    build.sanitizer,
                )
                logger.info(f"Starting fuzzer {build.engine} | {build.sanitizer} | {task.harness_name}")
                tracer = trace.get_tracer(__name__)
                log_crs_action_ok(
                    tracer,
                    CRSActionCategory.FUZZING,
                    "run_fuzzer",
                    tsk.task_meta.metadata,
                    {
                        "crs.action.target.harness": task.harness_name,
                        "crs.action.target.sanitizer": build.sanitizer,
                    },
                )
                result = self.runner.run_fuzzer(fuzz_conf)
                crash_set = CrashSet(self.redis)
                crash_dir = CrashDir(
                    self.crs_scratch_dir, task.task_id, task.harness_name, count_limit=self.crash_dir_count_limit
                )
                for crash_ in result.crashes:
                    crash: engine.Crash = crash_
                    cdata = stack_parsing.get_crash_data(crash.stacktrace)
                    dst = crash_dir.copy_file(crash.input_path, cdata)
                    if crash_set.add(
                        task.package_name,
                        task.harness_name,
                        task.task_id,
                        build.sanitizer,
                        crash.stacktrace,
                    ):
                        logger.info(
                            f"Crash {crash.input_path}|{crash.reproduce_args}|{crash.crash_time} already in set"
                        )
                        logger.debug(f"Crash stacktrace: {crash.stacktrace}")
                        continue

                    logger.info(f"Found unique crash {dst}")
                    crash = Crash(
                        target=build,
                        harness_name=task.harness_name,
                        crash_input_path=dst,
                        stacktrace=crash.stacktrace,
                        crash_token=cdata,
                    )
                    self.output_q.push(crash)

                logger.info(f"Fuzzer finished for {build.engine} | {build.sanitizer} | {task.harness_name}")


def main():
    args = FuzzerBotSettings()
    setup_package_logger("fuzzer-bot", __name__, args.log_level)
    init_telemetry("fuzzer")
    os.makedirs(args.wdir, exist_ok=True)
    logger.info(f"Starting fuzzer (wdir: {args.wdir} crs_scratch_dir: {args.crs_scratch_dir})")

    seconds_sleep = args.timer // 1000
    fuzzer = FuzzerBot(
        Redis.from_url(args.redis_url),
        seconds_sleep,
        args.timeout,
        args.wdir,
        args.python,
        args.crs_scratch_dir,
        crash_dir_count_limit=(args.crash_dir_count_limit if args.crash_dir_count_limit > 0 else None),
    )
    fuzzer.run()


if __name__ == "__main__":
    main()
