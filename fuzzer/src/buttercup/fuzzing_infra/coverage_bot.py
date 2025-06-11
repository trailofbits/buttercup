from functools import lru_cache
import logging
import os
import random
from buttercup.common.logger import setup_package_logger
from buttercup.common.default_task_loop import TaskLoop
from buttercup.common.datastructures.msg_pb2 import BuildType, WeightedHarness, FunctionCoverage
from buttercup.common.datastructures.aliases import BuildType as BuildTypeHint
from buttercup.common.maps import CoverageMap
from typing import List
from redis import Redis
from buttercup.common.datastructures.msg_pb2 import BuildOutput
from buttercup.common.corpus import Corpus
from buttercup.fuzzing_infra.coverage_runner import CoverageRunner, CoveredFunction
from buttercup.fuzzing_infra.settings import CoverageBotSettings
from buttercup.common.challenge_task import ChallengeTask
from buttercup.common.utils import setup_periodic_zombie_reaper
import shutil
import buttercup.common.node_local as node_local
from contextlib import contextmanager
from buttercup.common.telemetry import init_telemetry
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode
from buttercup.common.telemetry import set_crs_attributes, CRSActionCategory

logger = logging.getLogger(__name__)


@lru_cache(maxsize=10)
def get_processed_coverage(corpus_path: str) -> set[str]:
    """
    Get the set of processed coverage files in the corpus.
    """
    return set()


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
        sample_size: int,
    ):
        self.wdir = wdir
        self.python = python
        self.allow_pull = allow_pull
        self.base_image_url = base_image_url
        self.llvm_cov_tool = llvm_cov_tool
        self.sample_size = sample_size
        logger.info(f"Coverage bot initialized with sample_size: {sample_size}")
        super().__init__(redis, timer_seconds)

    def required_builds(self) -> List[BuildTypeHint]:
        return [BuildType.COVERAGE]

    @contextmanager
    def _sample_corpus(self, corpus: Corpus):
        """Sample the corpus to the given size and return a temporary directory
        with symlinks to the sampled input files.

        Args:
            corpus: The corpus to sample

        Returns:
            A context manager yielding a temporary directory containing symlinks
            to the sampled corpus files, or the original corpus path if sample_size is 0.
        """
        # Get list of input files from corpus
        input_files = os.listdir(corpus.path)

        already_processed = get_processed_coverage(corpus.path)
        logger.info(f"Already processed: {len(already_processed)}")
        input_files = [f for f in input_files if f not in already_processed]

        # If sample_size is 0, use the entire corpus directly without sampling
        if self.sample_size == 0:
            logger.info(
                f"Using entire non-processed corpus ({len(input_files)} files) in {corpus.path} (sample_size=0)"
            )
            yield (corpus.path, input_files)
            return

        # If there are fewer files than sample_size, use all of them
        if len(input_files) <= self.sample_size:
            sampled_inputs = input_files
        else:
            sampled_inputs = random.sample(input_files, self.sample_size)

        # Create a temporary directory in node_local scratch space
        failed = set()
        with node_local.scratch_dir() as tmp_dir:
            # Create symlinks to sampled input files
            for input_file in sampled_inputs:
                src_path = os.path.join(corpus.path, input_file)
                dst_path = os.path.join(tmp_dir.path, input_file)
                try:
                    # If the file is not the sha256 hash of the content, it will be renamed to the hash
                    # by another process. This can cause problems with the copying of the file. If there
                    # is some other error, that's very unexpected and we should fail.
                    shutil.copy2(src_path, dst_path)
                except FileNotFoundError as e:
                    logger.debug(f"Failed to copy {src_path} to {dst_path}: {e}.")
                    failed.add(input_file)
            remaining_files = [f for f in sampled_inputs if f not in failed]
            logger.info(f"Created temporary corpus with {len(remaining_files)} files in {tmp_dir.path}")

            yield (tmp_dir.path, remaining_files)

    def run_task(self, task: WeightedHarness, builds: dict[BuildTypeHint, BuildOutput]):
        coverage_builds = builds[BuildType.COVERAGE]
        if len(coverage_builds) <= 0:
            logger.error(f"No coverage build found for {task.task_id}")
            return

        coverage_build = coverage_builds[0]

        logger.info(f"Coverage build: {coverage_build}")

        tsk = ChallengeTask(read_only_task_dir=coverage_build.task_dir)
        with tsk.get_rw_copy(work_dir=self.wdir) as local_tsk:
            corpus = Corpus(self.wdir, task.task_id, task.harness_name)
            corpus.sync_from_remote()

            # Use the sampled corpus for coverage analysis
            with self._sample_corpus(corpus) as (sampled_corpus_path, remaining_files):
                if len(remaining_files) == 0:
                    logger.info(
                        f"No files to process for {task.harness_name} | {corpus.path} | {local_tsk.project_name}"
                    )
                    return

                runner = CoverageRunner(
                    local_tsk,
                    self.llvm_cov_tool,
                )

                # log telemetry
                tracer = trace.get_tracer(__name__)
                with tracer.start_as_current_span("coverage_analysis") as span:
                    set_crs_attributes(
                        span,
                        crs_action_category=CRSActionCategory.DYNAMIC_ANALYSIS,
                        crs_action_name="coverage_analysis",
                        task_metadata=dict(tsk.task_meta.metadata),
                        extra_attributes={
                            "crs.action.target.harness": task.harness_name,
                            "fuzz.corpus.size": corpus.local_corpus_size(),
                        },
                    )
                    func_coverage = runner.run(task.harness_name, sampled_corpus_path)

                    if func_coverage is None:
                        logger.error(
                            f"No function coverage found for {task.harness_name} | {corpus.path} | {local_tsk.project_name}"
                        )
                        span.set_status(Status(StatusCode.ERROR))
                        return
                    span.set_status(Status(StatusCode.OK))

            get_processed_coverage(corpus.path).update(remaining_files)
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

    setup_package_logger("coverage-bot", __name__, args.log_level, args.log_max_line_length)
    init_telemetry("coverage-bot")

    setup_periodic_zombie_reaper()

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
        args.sample_size,
    )
    fuzzer.run()


if __name__ == "__main__":
    main()
