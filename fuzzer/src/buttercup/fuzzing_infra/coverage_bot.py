import logging
import os
from buttercup.common.logger import setup_package_logger
from buttercup.common.default_task_loop import TaskLoop
from buttercup.common.datastructures.msg_pb2 import WeightedHarness, FunctionCoverage
from buttercup.common.maps import BUILD_TYPES, CoverageMap
from typing import List, Any
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
            coverage_data = runner.run(task.harness_name, corpus.path, local_tsk.project_name)
            logger.info(
                f"Coverage for {task.harness_name} | {local_tsk.project_name} | {task.task_id} | {corpus.path} | {coverage_build.task_dir}"
            )
            func_coverage = CoverageBot._process_function_coverage(coverage_data)
            logger.info(
                f"Coverage for {task.harness_name} | {corpus.path} | {local_tsk.project_name} | processed {len(func_coverage)} functions"
            )
            self._submit_function_coverage(func_coverage, task.harness_name, task.package_name, task.task_id)

    @staticmethod
    def _process_function_coverage(coverage_data: dict[str, Any]) -> list[dict[str, Any]]:
        """
        Process the LLVM coverage data to extract function-level line coverage.

        Returns a dictionary mapping function names to their line coverage metrics.

        Reference for coverage data format:
            https://github.com/llvm/llvm-project/blob/main/llvm/tools/llvm-cov/CoverageExporterJson.cpp
        """
        function_coverage = []

        if "data" not in coverage_data:
            logger.error("Invalid coverage data format: 'data' field missing")
            return function_coverage

        for export_obj in coverage_data["data"]:
            if "functions" not in export_obj:
                continue

            for function in export_obj["functions"]:
                if "name" not in function or "regions" not in function:
                    continue

                name = function["name"]
                regions = function["regions"]

                covered_lines = set()
                total_lines = set()

                for region in regions:
                    # Region format: [lineStart, colStart, lineEnd, colEnd, executionCount, ...]
                    if len(region) < 5:
                        continue

                    line_start = region[0]
                    line_end = region[2]
                    execution_count = region[4]

                    for line in range(line_start, line_end + 1):
                        total_lines.add(line)

                        if execution_count > 0:
                            covered_lines.add(line)

                total_line_count = len(total_lines)
                covered_line_count = len(covered_lines)

                function_coverage.append(
                    {
                        "function_name": name,
                        "total_lines": total_line_count,
                        "covered_lines": covered_line_count,
                        "filenames": function.get("filenames", []),
                    }
                )

        return function_coverage

    @staticmethod
    def _should_update_function_coverage(coverage_map: CoverageMap, function_coverage: FunctionCoverage) -> bool:
        """Update function coverage if it's nonzero and exceeds previous coverage"""
        if not (function_coverage.total_lines > 0 and function_coverage.covered_lines > 0):
            return False

        old_function_coverage = coverage_map.get_function_coverage(
            function_coverage.function_name, function_coverage.function_paths
        )
        if old_function_coverage is None:
            return True
        return function_coverage.covered_lines > old_function_coverage.covered_lines

    def _submit_function_coverage(
        self, func_coverage: list[dict[str, Any]], harness_name: str, package_name: str, task_id: str
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
            function_paths_set = set(function.get("filenames", []))
            function_paths = list(function_paths_set)
            function_paths.sort()

            function_coverage.function_name = function["function_name"]
            function_coverage.total_lines = function["total_lines"]
            function_coverage.covered_lines = function["covered_lines"]
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
