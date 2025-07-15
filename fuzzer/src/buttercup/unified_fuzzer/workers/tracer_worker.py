"""Tracer worker for the unified fuzzer."""

import logging
import os
import queue
from pathlib import Path

import buttercup.common.node_local as node_local
from buttercup.common import stack_parsing
from buttercup.common.datastructures.msg_pb2 import Crash, TracedCrash
from buttercup.common.queues import ReliableQueue
from buttercup.common.task_registry import TaskRegistry
from buttercup.fuzzing_infra.tracer_runner import TracerRunner
from redis import Redis

from ..queue_adapter import RedisQueueItem
from .base_worker import QueueWorker

logger = logging.getLogger(__name__)


class TracerWorker(QueueWorker):
    """Worker that handles crash tracing."""
    
    def __init__(
        self,
        redis: Redis,
        input_queue: queue.Queue,
        output_queue: ReliableQueue,
        registry: TaskRegistry,
        config: dict
    ):
        super().__init__("tracer", input_queue, config)
        self.redis = redis
        self.output_queue = output_queue
        self.registry = registry
        
        # Configuration
        self.wdir = config.get('wdir', '/tmp/tracer')
        self.python = config.get('python', 'python')
        self.max_tries = config.get('max_tries', 3)
        
        # Create working directory
        os.makedirs(self.wdir, exist_ok=True)
    
    def process_item(self, item) -> bool:
        """Process a crash for tracing."""
        # Handle both internal queue items (Crash) and Redis queue items (RedisQueueItem)
        if isinstance(item, RedisQueueItem):
            # This is from Redis
            crash = item.deserialized
            redis_item = item
        elif isinstance(item, Crash):
            # This is a direct Crash message from internal queue
            crash = item
            redis_item = None
        else:
            logger.error("Invalid item received in tracer worker")
            return False
        
        logger.info(f"Received tracer request for {crash.target.task_id}")
        
        # Check if task should be processed
        if self.registry.should_stop_processing(crash.target.task_id):
            logger.info(f"Task {crash.target.task_id} is cancelled or expired, skipping")
            if redis_item:
                redis_item.ack()
            return True
        
        # Check max tries if from Redis
        if redis_item:
            if redis_item.times_delivered() > self.max_tries:
                logger.warning(f"Reached max tries for {crash.target.task_id}")
                redis_item.ack()
                return True
        
        # Run tracer
        runner = TracerRunner(crash.target.task_id, self.wdir, self.redis)
        
        # Ensure the crash input is locally available
        logger.info(f"Making locally available: {crash.crash_input_path}")
        local_path = node_local.make_locally_available(Path(crash.crash_input_path))
        
        tinfo = runner.run(
            crash.harness_name,
            local_path,
            crash.target.sanitizer,
        )
        
        if tinfo is None:
            logger.warning(f"No tracer info found for {crash.target.task_id}")
            if redis_item:
                redis_item.ack()
            return True
        
        if tinfo.is_valid:
            logger.info(f"Valid tracer info found for {crash.target.task_id}")
            prsed = stack_parsing.parse_stacktrace(tinfo.stacktrace)
            output = prsed.crash_stacktrace
            ntrace = output if output is not None and len(output) > 0 else tinfo.stacktrace
            
            # Create traced crash
            traced_crash = TracedCrash(
                crash=crash,
                tracer_stacktrace=ntrace,
            )
            
            # Push to Redis output queue
            self.output_queue.push(traced_crash)
        
        logger.info(f"Acknowledging tracer request for {crash.target.task_id}")
        if redis_item:
            redis_item.ack()
        
        return True