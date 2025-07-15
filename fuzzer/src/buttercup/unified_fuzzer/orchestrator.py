"""Main orchestrator for the unified fuzzer service."""

import logging
import queue
import threading
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from buttercup.common.datastructures.msg_pb2 import (
    BuildOutput,
    BuildRequest,
    BuildType,
    Crash,
    TracedCrash,
    WeightedHarness,
)
from buttercup.common.logger import setup_package_logger
from buttercup.common.maps import BuildMap, HarnessWeights
from buttercup.common.queues import GroupNames, QueueFactory, QueueNames
from buttercup.common.task_registry import TaskRegistry
from buttercup.common.telemetry import init_telemetry
from buttercup.common.utils import setup_periodic_zombie_reaper
from redis import Redis

from .harness_manager import HarnessManager
from .queue_adapter import RedisQueueItem
from .workers.build_worker import BuildWorker
from .workers.coverage_worker import CoverageWorker
from .workers.fuzzer_worker import FuzzerWorker
from .workers.tracer_worker import TracerWorker

logger = logging.getLogger(__name__)


@dataclass
class UnifiedFuzzerOrchestrator:
    """Main orchestrator that manages all fuzzing workers."""
    
    redis: Redis
    config: dict
    
    # Internal queues for communication between workers
    build_queue: queue.Queue = field(default_factory=queue.Queue)
    fuzzer_queue: queue.Queue = field(default_factory=queue.Queue)
    coverage_queue: queue.Queue = field(default_factory=queue.Queue)
    tracer_queue: queue.Queue = field(default_factory=queue.Queue)
    
    # Workers
    build_worker: Optional[BuildWorker] = None
    fuzzer_workers: List[FuzzerWorker] = field(default_factory=list)
    coverage_worker: Optional[CoverageWorker] = None
    tracer_worker: Optional[TracerWorker] = None
    
    # Threads
    threads: List[threading.Thread] = field(default_factory=list)
    
    # Redis interfaces for external communication
    _redis_queues: dict = field(default_factory=dict)
    _registry: Optional[TaskRegistry] = None
    _harness_weights: Optional[HarnessWeights] = None
    _build_map: Optional[BuildMap] = None
    _harness_manager: Optional[HarnessManager] = None
    
    def __post_init__(self):
        """Initialize Redis connections and shared resources."""
        queue_factory = QueueFactory(self.redis)
        
        # Input queues from Redis (external communication)
        self._redis_queues = {
            'build_requests': queue_factory.create(QueueNames.BUILD, GroupNames.BUILDER_BOT),
            'build_outputs': queue_factory.create(QueueNames.BUILD_OUTPUT),
            'crashes': queue_factory.create(QueueNames.CRASH),
            'traced_vulnerabilities': queue_factory.create(QueueNames.TRACED_VULNERABILITIES),
        }
        
        # Shared resources
        self._registry = TaskRegistry(self.redis)
        self._harness_weights = HarnessWeights(self.redis)
        self._build_map = BuildMap(self.redis)
        self._harness_manager = HarnessManager(self.redis)
        
        # Initialize workers
        self._initialize_workers()
    
    def _initialize_workers(self):
        """Initialize all worker instances."""
        # Build worker
        self.build_worker = BuildWorker(
            redis=self.redis,
            input_queue=self.build_queue,
            output_queue=self.fuzzer_queue,
            redis_output_queue=self._redis_queues['build_outputs'],
            registry=self._registry,
            config=self.config['builder']
        )
        
        # Fuzzer workers (can have multiple)
        num_fuzzer_workers = self.config.get('num_fuzzer_workers', 2)
        for i in range(num_fuzzer_workers):
            fuzzer_worker = FuzzerWorker(
                redis=self.redis,
                input_queue=self.fuzzer_queue,
                crash_output_queue=self.tracer_queue,
                coverage_queue=self.coverage_queue,
                redis_crash_queue=self._redis_queues['crashes'],
                harness_weights=self._harness_weights,
                build_map=self._build_map,
                config=self.config['fuzzer'],
                worker_id=i
            )
            self.fuzzer_workers.append(fuzzer_worker)
        
        # Coverage worker
        self.coverage_worker = CoverageWorker(
            redis=self.redis,
            input_queue=self.coverage_queue,
            harness_weights=self._harness_weights,
            build_map=self._build_map,
            config=self.config['coverage']
        )
        
        # Tracer worker
        self.tracer_worker = TracerWorker(
            redis=self.redis,
            input_queue=self.tracer_queue,
            output_queue=self._redis_queues['traced_vulnerabilities'],
            registry=self._registry,
            config=self.config['tracer']
        )
    
    def _redis_to_internal_router(self):
        """Route messages from Redis queues to internal queues."""
        while not self._stop_event.is_set():
            try:
                # Check for build requests
                rqit = self._redis_queues['build_requests'].pop()
                if rqit:
                    logger.debug("Routing build request to internal queue")
                    # Wrap the Redis queue item
                    wrapped_item = RedisQueueItem(
                        item=rqit,
                        source_queue=self._redis_queues['build_requests']
                    )
                    self.build_queue.put(wrapped_item)
                
                # Sleep briefly to avoid busy waiting
                time.sleep(0.1)
                
            except Exception:
                logger.exception("Error in Redis to internal router")
                time.sleep(1)
    
    def _process_build_outputs(self):
        """Process build outputs and update harness weights."""
        while not self._stop_event.is_set():
            try:
                # Check fuzzer queue for build outputs
                if not self.fuzzer_queue.empty():
                    try:
                        item = self.fuzzer_queue.get_nowait()
                        if isinstance(item, BuildOutput):
                            # Use harness manager to process build output
                            added_harnesses = self._harness_manager.process_build_output(item)
                            
                            if added_harnesses:
                                logger.info(
                                    f"Build output processed for task {item.task_id}, "
                                    f"added {len(added_harnesses)} harnesses"
                                )
                    except queue.Empty:
                        pass
                
                time.sleep(0.5)
                
            except Exception:
                logger.exception("Error processing build outputs")
                time.sleep(1)
    
    def start(self):
        """Start all workers and routing threads."""
        logger.info("Starting unified fuzzer orchestrator")
        
        # Create stop event for graceful shutdown
        self._stop_event = threading.Event()
        
        # Start router thread
        router_thread = threading.Thread(
            target=self._redis_to_internal_router,
            name="redis-router"
        )
        router_thread.start()
        self.threads.append(router_thread)
        
        # Start build output processor
        processor_thread = threading.Thread(
            target=self._process_build_outputs,
            name="build-processor"
        )
        processor_thread.start()
        self.threads.append(processor_thread)
        
        # Start workers
        logger.info("Starting build worker")
        build_thread = threading.Thread(
            target=self.build_worker.run,
            name="build-worker"
        )
        build_thread.start()
        self.threads.append(build_thread)
        
        # Start fuzzer workers
        for i, fuzzer_worker in enumerate(self.fuzzer_workers):
            logger.info(f"Starting fuzzer worker {i}")
            fuzzer_thread = threading.Thread(
                target=fuzzer_worker.run,
                name=f"fuzzer-worker-{i}"
            )
            fuzzer_thread.start()
            self.threads.append(fuzzer_thread)
        
        # Start coverage worker
        logger.info("Starting coverage worker")
        coverage_thread = threading.Thread(
            target=self.coverage_worker.run,
            name="coverage-worker"
        )
        coverage_thread.start()
        self.threads.append(coverage_thread)
        
        # Start tracer worker  
        logger.info("Starting tracer worker")
        tracer_thread = threading.Thread(
            target=self.tracer_worker.run,
            name="tracer-worker"
        )
        tracer_thread.start()
        self.threads.append(tracer_thread)
        
        logger.info("All workers started successfully")
    
    def stop(self):
        """Stop all workers gracefully."""
        logger.info("Stopping unified fuzzer orchestrator")
        self._stop_event.set()
        
        # Stop all workers
        if self.build_worker:
            self.build_worker.stop()
        for fuzzer_worker in self.fuzzer_workers:
            fuzzer_worker.stop()
        if self.coverage_worker:
            self.coverage_worker.stop()
        if self.tracer_worker:
            self.tracer_worker.stop()
        
        # Wait for threads to finish
        for thread in self.threads:
            thread.join(timeout=5)
        
        logger.info("Unified fuzzer orchestrator stopped")
    
    def run(self):
        """Main run loop."""
        try:
            self.start()
            
            # Keep running until interrupted
            while True:
                time.sleep(1)
                
        except KeyboardInterrupt:
            logger.info("Received interrupt signal")
        finally:
            self.stop()


def main():
    """Main entry point for the unified fuzzer."""
    from .config import UnifiedFuzzerConfig
    
    # Load configuration
    config = UnifiedFuzzerConfig()
    
    # Setup logging
    setup_package_logger(
        "unified-fuzzer",
        __name__,
        config.log_level,
        config.log_max_line_length
    )
    
    # Initialize telemetry
    init_telemetry("unified-fuzzer")
    
    # Setup zombie reaper
    setup_periodic_zombie_reaper()
    
    # Connect to Redis
    redis = Redis.from_url(config.redis_url)
    
    # Create and run orchestrator
    orchestrator = UnifiedFuzzerOrchestrator(
        redis=redis,
        config=config.to_dict()
    )
    
    logger.info("Starting unified fuzzer service")
    orchestrator.run()


if __name__ == "__main__":
    main()