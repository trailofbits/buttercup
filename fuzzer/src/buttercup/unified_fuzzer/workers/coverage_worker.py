"""Coverage worker for the unified fuzzer."""

import logging
import os
import queue
import random
import shutil
from contextlib import contextmanager
from functools import lru_cache
from typing import List

import buttercup.common.node_local as node_local
from buttercup.common.challenge_task import ChallengeTask
from buttercup.common.corpus import Corpus
from buttercup.common.datastructures.aliases import BuildType as BuildTypeHint
from buttercup.common.datastructures.msg_pb2 import BuildOutput, BuildType, FunctionCoverage, WeightedHarness
from buttercup.common.maps import BuildMap, CoverageMap, HarnessWeights
from buttercup.common.telemetry import CRSActionCategory, set_crs_attributes
from buttercup.fuzzing_infra.coverage_runner import CoverageRunner, CoveredFunction
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode
from redis import Redis

from .base_worker import QueueWorker

logger = logging.getLogger(__name__)


@lru_cache(maxsize=10)
def get_processed_coverage(corpus_path: str) -> set[str]:
    """Get the set of processed coverage files in the corpus."""
    return set()


class CoverageWorker(QueueWorker):
    """Worker that handles coverage analysis."""
    
    def __init__(
        self,
        redis: Redis,
        input_queue: queue.Queue,
        harness_weights: HarnessWeights,
        build_map: BuildMap,
        config: dict
    ):
        super().__init__("coverage", input_queue, config)
        self.redis = redis
        self.harness_weights = harness_weights
        self.build_map = build_map
        
        # Configuration
        self.wdir = config.get('wdir', '/tmp/coverage')
        self.python = config.get('python', 'python')
        self.allow_pull = config.get('allow_pull', True)
        self.base_image_url = config.get('base_image_url', 'local/oss-fuzz')
        self.llvm_cov_tool = config.get('llvm_cov_tool', 'llvm-cov')
        self.sample_size = config.get('sample_size', 0)
        
        logger.info(f"Coverage worker initialized with sample_size: {self.sample_size}")
        
        # Create working directory
        os.makedirs(self.wdir, exist_ok=True)
    
    def required_builds(self) -> List[BuildTypeHint]:
        """Get required build types."""
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
    
    def process_item(self, item: WeightedHarness) -> bool:
        """Process a coverage analysis request."""
        if not isinstance(item, WeightedHarness):
            logger.error("Invalid item received in coverage worker")
            return False
        
        # Get coverage builds
        coverage_builds = self.build_map.get_builds(item.task_id, BuildType.COVERAGE)
        if len(coverage_builds) <= 0:
            logger.error(f"No coverage build found for {item.task_id}")
            return True
        
        coverage_build = coverage_builds[0]
        logger.info(f"Coverage build: {coverage_build}")
        
        tsk = ChallengeTask(read_only_task_dir=coverage_build.task_dir)
        with tsk.get_rw_copy(work_dir=self.wdir) as local_tsk:
            corpus = Corpus(self.wdir, item.task_id, item.harness_name)
            corpus.sync_from_remote()
            
            # Use the sampled corpus for coverage analysis
            with self._sample_corpus(corpus) as (sampled_corpus_path, remaining_files):
                if len(remaining_files) == 0:
                    logger.info(
                        f"No files to process for {item.harness_name} | {corpus.path} | {local_tsk.project_name}"
                    )
                    return True
                
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
                            "crs.action.target.harness": item.harness_name,
                            "fuzz.corpus.size": corpus.local_corpus_size(),
                        },
                    )
                    func_coverage = runner.run(item.harness_name, sampled_corpus_path)
                    
                    if func_coverage is None:
                        logger.error(
                            f"No function coverage found for {item.harness_name} | {corpus.path} | {local_tsk.project_name}"
                        )
                        span.set_status(Status(StatusCode.ERROR))
                        return True
                    span.set_status(Status(StatusCode.OK))
            
            get_processed_coverage(corpus.path).update(remaining_files)
            logger.info(
                f"Coverage for {item.harness_name} | {corpus.path} | {local_tsk.project_name} | "
                f"processed {len(func_coverage)} functions"
            )
            self._submit_function_coverage(func_coverage, item.harness_name, item.package_name, item.task_id)
        
        return True
    
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
        """Store function coverage in Redis.
        
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
            
            if CoverageWorker._should_update_function_coverage(coverage_map, function_coverage):
                coverage_map.set_function_coverage(function_coverage)
                updated_functions += 1
        logger.info(f"Updated coverage for {updated_functions} functions in Redis")