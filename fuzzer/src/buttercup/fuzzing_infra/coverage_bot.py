import logging
import os
from buttercup.common.logger import setup_package_logger
from buttercup.common.default_task_loop import TaskLoop
from buttercup.common.datastructures.msg_pb2 import WeightedHarness
from buttercup.common.maps import BUILD_TYPES
from typing import List
from redis import Redis
from buttercup.common.datastructures.msg_pb2 import BuildOutput
from buttercup.common.corpus import Corpus
from buttercup.fuzzing_infra.coverage_runner import CoverageRunner
from buttercup.fuzzing_infra.settings import CoverageBotSettings
from buttercup.common.challenge_task import ChallengeTask

logger = logging.getLogger(__name__)


class CoverageBot(TaskLoop):
    def __init__(
        self,
        redis: Redis,
        timer_seconds: int,
        wdir: str,
        python: str,
        allow_pull: bool,
        base_image_url: str,
        llvm_cov_tool: str,
    ):
        self.wdir = wdir
        self.python = python
        self.allow_pull = allow_pull
        self.base_image_url = base_image_url
        self.llvm_cov_tool = llvm_cov_tool
        super().__init__(redis, timer_seconds)

    def required_builds(self) -> List[BUILD_TYPES]:
        return [BUILD_TYPES.COVERAGE]

    def run_task(self, task: WeightedHarness, builds: dict[BUILD_TYPES, BuildOutput]):
        coverage_builds = builds[BUILD_TYPES.COVERAGE]
        if len(coverage_builds) <= 0:
            logger.error(f"No coverage build found for {task.task_id}")
            return

        coverage_build = coverage_builds[0]

        logger.info(f"Coverage build: {coverage_build}")

        tsk = ChallengeTask(read_only_task_dir=coverage_build.task_dir)
        with tsk.get_rw_copy(work_dir=self.wdir) as local_tsk:
            corpus = Corpus(self.wdir, task.task_id, task.harness_name)
            runner = CoverageRunner(
                local_tsk,
                self.llvm_cov_tool,
            )
            runner.run(task.harness_name, corpus.path, coverage_build.package_name)
            logger.info(
                f"Coverage for {task.harness_name} | {coverage_build.package_name} | {task.task_id} | {corpus.path} | {coverage_build.task_dir}"
            )


def main():
    args = CoverageBotSettings()

    setup_package_logger(__name__, args.log_level)

    os.makedirs(args.wdir, exist_ok=True)
    logger.info(f"Starting coverage bot (wdir: {args.wdir})")

    seconds_sleep = args.timer // 1000
    fuzzer = CoverageBot(
        Redis.from_url(args.redis_url),
        seconds_sleep,
        args.wdir,
        args.python,
        args.allow_pull,
        args.base_image_url,
        args.llvm_cov_tool,
    )
    fuzzer.run()


if __name__ == "__main__":
    main()
