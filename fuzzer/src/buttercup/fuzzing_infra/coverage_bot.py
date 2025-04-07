import logging
import os
from buttercup.common.logger import setup_package_logger
from buttercup.common.default_task_loop import TaskLoop
from buttercup.common.datastructures.msg_pb2 import BuildType, WeightedHarness, FunctionCoverage
from buttercup.common.maps import CoverageMap
from typing import List
from redis import Redis
from buttercup.common.datastructures.msg_pb2 import BuildOutput
from buttercup.common.corpus import Corpus
from buttercup.fuzzing_infra.coverage_runner import CoverageRunner, CoveredFunction
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

    def required_builds(self) -> List[BuildType]:
        return [BuildType.COVERAGE]

    def run_task(self, task: WeightedHarness, builds: dict[BuildType, BuildOutput]):
        coverage_builds = builds[BuildType.COVERAGE]
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
            func_coverage = runner.run(task.harness_name, corpus.path, local_tsk.project_name)
            if func_coverage is None:
                logger.error(
                    f"No function coverage found for {task.harness_name} | {corpus.path} | {local_tsk.project_name}"
                )
                return

            logger.info(
                f"Coverage for {task.harness_name} | {corpus.path} | {local_tsk.project_name} | processed {len(func_coverage)} functions"
            )
            self._submit_function_coverage(func_coverage, task.harness_name, task.package_name, task.task_id)

    @staticmethod
    def _should_update_function_coverage(coverage_map: CoverageMap, function_coverage: FunctionCoverage) -> bool:
        """Update function coverage if it's nonzero and exceeds previous coverage"""
        if not (function_coverage.total_lines > 0 and function_coverage.covered_lines > 0):
            return False

        function_paths_list = list(function_coverage.function_paths)
        old_function_coverage = coverage_map.get_function_coverage(function_coverage.function_name, function_paths_list)
        if old_function_coverage is None:
            return True
        return function_coverage.covered_lines > old_function_coverage.covered_lines

    def _submit_function_coverage(
        self, func_coverage: list[CoveredFunction], harness_name: str, package_name: str, task_id: str
    ):
        """
        Store function coverage in Redis.

        Args:
            func_coverage: List of dictionaries containing function coverage metrics
            harness_name: Name of the harness
            package_name: Name of the package
            task_id: Task ID
        """
        coverage_map = CoverageMap(self.redis, harness_name, package_name, task_id)

        updated_functions = 0
        for function in func_coverage:
            function_coverage = FunctionCoverage()
            function_paths_set = set(function.function_paths)
            function_paths = list(function_paths_set)
            function_paths.sort()

            function_coverage.function_name = function.names
            function_coverage.total_lines = function.total_lines
            function_coverage.covered_lines = function.covered_lines
            function_coverage.function_paths.extend(function_paths)

            if CoverageBot._should_update_function_coverage(coverage_map, function_coverage):
                coverage_map.set_function_coverage(function_coverage)
                updated_functions += 1
        logger.info(f"Updated coverage for {updated_functions} functions in Redis")


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
