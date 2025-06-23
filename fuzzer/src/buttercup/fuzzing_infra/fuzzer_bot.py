from buttercup.fuzzing_infra.runner import Runner, Conf, FuzzConfiguration
from buttercup.common.datastructures.msg_pb2 import BuildType, WeightedHarness, Crash
from buttercup.common.datastructures.aliases import BuildType as BuildTypeHint
from buttercup.common.queues import QueueFactory, QueueNames
from buttercup.common.corpus import Corpus, CrashDir
from buttercup.common import stack_parsing
from buttercup.common.stack_parsing import CrashSet
from buttercup.common.logger import setup_package_logger
from buttercup.common.utils import setup_periodic_zombie_reaper
from redis import Redis
from clusterfuzz.fuzz import engine
from buttercup.common.default_task_loop import TaskLoop
from typing import List
import random
from buttercup.common.datastructures.msg_pb2 import BuildOutput
import logging
from buttercup.common.challenge_task import ChallengeTask
from buttercup.fuzzing_infra.settings import FuzzerBotSettings
from buttercup.common.telemetry import init_telemetry, CRSActionCategory, set_crs_attributes
from opentelemetry import trace
from opentelemetry.trace.status import Status, StatusCode
from buttercup.common.node_local import scratch_dir
from pathlib import Path

logger = logging.getLogger(__name__)


class FuzzerBot(TaskLoop):
    def __init__(
        self,
        redis: Redis,
        timer_seconds: int,
        timeout_seconds: int,
        python: str,
        crs_scratch_dir: str,
        crash_dir_count_limit: int | None,
        max_pov_size: int,
    ):
        self.runner = Runner(Conf(timeout_seconds))
        self.output_q = QueueFactory(redis).create(QueueNames.CRASH)
        self.python = python
        self.crs_scratch_dir = crs_scratch_dir
        self.crash_dir_count_limit = crash_dir_count_limit
        self.max_pov_size = max_pov_size
        super().__init__(redis, timer_seconds)

    def required_builds(self) -> List[BuildTypeHint]:
        return [BuildType.FUZZER]

    def run_task(self, task: WeightedHarness, builds: dict[BuildTypeHint, BuildOutput]):
        with scratch_dir() as td:
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
                with tracer.start_as_current_span("run_fuzzer") as span:
                    set_crs_attributes(
                        span,
                        crs_action_category=CRSActionCategory.FUZZING,
                        crs_action_name="run_fuzzer",
                        task_metadata=tsk.task_meta.metadata,
                        extra_attributes={
                            "crs.action.target.harness": task.harness_name,
                            "crs.action.target.sanitizer": build.sanitizer,
                            "crs.action.target.engine": build.engine,
                            "fuzz.corpus.size": corp.local_corpus_size(),
                        },
                    )
                    result = self.runner.run_fuzzer(fuzz_conf)

                    crash_set = CrashSet(self.redis)
                    crash_dir = CrashDir(
                        self.crs_scratch_dir, task.task_id, task.harness_name, count_limit=self.crash_dir_count_limit
                    )
                    for crash_ in result.crashes:
                        crash: engine.Crash = crash_

                        file_size = Path(crash.input_path).stat().st_size
                        if file_size > self.max_pov_size:
                            logger.warning(
                                "Discarding crash (%s bytes) that exceeds max PoV size (%s bytes) for %s",
                                file_size,
                                self.max_pov_size,
                                task.task_id,
                            )
                            continue

                        cdata = stack_parsing.get_crash_token(crash.stacktrace)
                        dst = crash_dir.copy_file(crash.input_path, cdata, build.sanitizer)
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

                    span.set_status(Status(StatusCode.OK))
                    logger.info(f"Fuzzer finished for {build.engine} | {build.sanitizer} | {task.harness_name}")


def main():
    args = FuzzerBotSettings()
    setup_package_logger("fuzzer-bot", __name__, args.log_level, args.log_max_line_length)
    init_telemetry("fuzzer")

    setup_periodic_zombie_reaper()

    logger.info(f"Starting fuzzer (crs_scratch_dir: {args.crs_scratch_dir})")

    seconds_sleep = args.timer // 1000
    fuzzer = FuzzerBot(
        Redis.from_url(args.redis_url),
        seconds_sleep,
        args.timeout,
        args.python,
        args.crs_scratch_dir,
        crash_dir_count_limit=(args.crash_dir_count_limit if args.crash_dir_count_limit > 0 else None),
        max_pov_size=args.max_pov_size,
    )
    fuzzer.run()


if __name__ == "__main__":
    main()
