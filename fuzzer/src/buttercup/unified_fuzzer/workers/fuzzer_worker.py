"""Fuzzer worker for the unified fuzzer."""

import logging
import queue
import random
from pathlib import Path
from typing import List, Optional

from buttercup.common import stack_parsing
from buttercup.common.challenge_task import ChallengeTask
from buttercup.common.corpus import Corpus, CrashDir
from buttercup.common.datastructures.aliases import BuildType as BuildTypeHint
from buttercup.common.datastructures.msg_pb2 import BuildOutput, BuildType, Crash, WeightedHarness
from buttercup.common.maps import BuildMap, HarnessWeights
from buttercup.common.node_local import scratch_dir
from buttercup.common.queues import ReliableQueue
from buttercup.common.stack_parsing import CrashSet
from buttercup.common.telemetry import CRSActionCategory, set_crs_attributes
from buttercup.fuzzing_infra.runner import Conf, FuzzConfiguration, Runner
from clusterfuzz.fuzz import engine
from opentelemetry import trace
from opentelemetry.trace.status import Status, StatusCode
from redis import Redis

from .base_worker import BaseWorker

logger = logging.getLogger(__name__)


class FuzzerWorker(BaseWorker):
    """Worker that handles fuzzing tasks."""
    
    def __init__(
        self,
        redis: Redis,
        input_queue: queue.Queue,
        crash_output_queue: queue.Queue,
        coverage_queue: queue.Queue,
        redis_crash_queue: ReliableQueue,
        harness_weights: HarnessWeights,
        build_map: BuildMap,
        config: dict,
        worker_id: int
    ):
        super().__init__(f"fuzzer-{worker_id}", config)
        self.redis = redis
        self.input_queue = input_queue
        self.crash_output_queue = crash_output_queue
        self.coverage_queue = coverage_queue
        self.redis_crash_queue = redis_crash_queue
        self.harness_weights = harness_weights
        self.build_map = build_map
        self.worker_id = worker_id
        
        # Configuration
        self.timeout_seconds = config.get('timeout', 1000)
        self.python = config.get('python', 'python')
        self.crs_scratch_dir = config.get('crs_scratch_dir', '/crs_scratch')
        self.crash_dir_count_limit = config.get('crash_dir_count_limit', 0)
        if self.crash_dir_count_limit <= 0:
            self.crash_dir_count_limit = None
        self.max_pov_size = config.get('max_pov_size', 2 * 1024 * 1024)
        
        # Initialize runner
        self.runner = Runner(Conf(self.timeout_seconds))
    
    def required_builds(self) -> List[BuildTypeHint]:
        """Get required build types."""
        return [BuildType.FUZZER]
    
    def work_iteration(self) -> bool:
        """Perform one fuzzing iteration."""
        # Check for new builds in the input queue
        try:
            build_output = self.input_queue.get_nowait()
            if isinstance(build_output, BuildOutput):
                # Process new build output
                self._process_build_output(build_output)
                return True
        except queue.Empty:
            pass
        
        # Select a weighted harness to fuzz
        weighted_items: list[WeightedHarness] = [
            wh for wh in self.harness_weights.list_harnesses() if wh.weight > 0
        ]
        if len(weighted_items) <= 0:
            return False
        
        # Select harness based on weights
        chc = random.choices(
            weighted_items,
            weights=[it.weight for it in weighted_items],
            k=1,
        )[0]
        
        logger.info(f"Running fuzzer for {chc.harness_name} | {chc.package_name} | {chc.task_id}")
        
        # Get builds
        builds = {
            reqbuild: self.build_map.get_builds(chc.task_id, reqbuild) 
            for reqbuild in self.required_builds()
        }
        
        # Check if all builds are available
        has_all_builds = True
        for k, build in builds.items():
            if len(build) <= 0:
                logger.warning(f"Build {k} for {chc.task_id} not found")
                has_all_builds = False
        
        if has_all_builds:
            self._run_fuzzing_task(chc, builds)
            
            # Also trigger coverage analysis for this harness
            self.coverage_queue.put(chc)
            return True
        
        return False
    
    def _process_build_output(self, build_output: BuildOutput):
        """Process a new build output."""
        # Update build map
        self.build_map.add_build(build_output)
        
        # If it's a fuzzer build, get targets and update harness weights
        if build_output.build_type == BuildType.FUZZER:
            # In the original code, this would use get_fuzz_targets
            # For now, we'll assume the harness info is available
            logger.info(f"New fuzzer build available for task {build_output.task_id}")
    
    def _run_fuzzing_task(self, task: WeightedHarness, builds: dict[BuildTypeHint, BuildOutput]):
        """Run the actual fuzzing task."""
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
                        self.crs_scratch_dir, 
                        task.task_id, 
                        task.harness_name, 
                        count_limit=self.crash_dir_count_limit
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
                        crash_msg = Crash(
                            target=build,
                            harness_name=task.harness_name,
                            crash_input_path=dst,
                            stacktrace=crash.stacktrace,
                            crash_token=cdata,
                        )
                        
                        # Send to both internal queue and Redis
                        self.crash_output_queue.put(crash_msg)
                        self.redis_crash_queue.push(crash_msg)
                    
                    span.set_status(Status(StatusCode.OK))
                    logger.info(f"Fuzzer finished for {build.engine} | {build.sanitizer} | {task.harness_name}")
    
    def process_item(self, item) -> bool:
        """Not used - work_iteration handles the logic."""
        return True