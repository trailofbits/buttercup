"""Build worker for the unified fuzzer."""

import logging
import queue
import tempfile
from pathlib import Path
from typing import Optional

import buttercup.common.node_local as node_local
from buttercup.common.challenge_task import ChallengeTask, ChallengeTaskError
from buttercup.common.datastructures.msg_pb2 import BuildOutput, BuildRequest, BuildType
from buttercup.common.queues import ReliableQueue
from buttercup.common.task_registry import TaskRegistry
from buttercup.common.telemetry import CRSActionCategory, set_crs_attributes
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode
from redis import Redis

from ..queue_adapter import RedisQueueItem
from .base_worker import QueueWorker

logger = logging.getLogger(__name__)


class BuildWorker(QueueWorker):
    """Worker that handles build requests."""
    
    def __init__(
        self,
        redis: Redis,
        input_queue: queue.Queue,
        output_queue: queue.Queue,
        redis_output_queue: ReliableQueue,
        registry: TaskRegistry,
        config: dict
    ):
        super().__init__("build", input_queue, config)
        self.redis = redis
        self.output_queue = output_queue
        self.redis_output_queue = redis_output_queue
        self.registry = registry
        
        # Configuration
        self.allow_caching = config.get('allow_caching', False)
        self.allow_pull = config.get('allow_pull', True)
        self.python = config.get('python', 'python')
        self.wdir = config.get('wdir', '/tmp/builder')
        self.max_tries = config.get('max_tries', 3)
    
    def _apply_challenge_diff(self, task: ChallengeTask, msg: BuildRequest) -> bool:
        """Apply challenge diff if needed."""
        if msg.apply_diff and task.is_delta_mode():
            logger.info(
                f"Applying diff for {msg.task_id} | {msg.engine} | {msg.sanitizer} | "
                f"{BuildType.Name(msg.build_type)} | diff {msg.apply_diff}"
            )
            try:
                res = task.apply_patch_diff()
                if not res:
                    logger.warning(
                        f"No diffs for {msg.task_id} | {msg.engine} | {msg.sanitizer} | "
                        f"{BuildType.Name(msg.build_type)} | diff {msg.apply_diff}"
                    )
                    return False
            except ChallengeTaskError:
                logger.exception(
                    "Failed to apply diff for %s | %s | %s | %s | diff %s",
                    msg.task_id,
                    msg.engine,
                    msg.sanitizer,
                    BuildType.Name(msg.build_type),
                    msg.apply_diff,
                )
                return False
        return True
    
    def _apply_patch(self, task: ChallengeTask, msg: BuildRequest) -> bool:
        """Apply patch if provided."""
        if msg.patch and msg.internal_patch_id:
            with tempfile.NamedTemporaryFile(mode="w+") as patch_file:
                patch_file.write(msg.patch)
                patch_file.flush()
                logger.debug("Patch written to %s", patch_file.name)
                
                logger.info(
                    f"Applying patch for {msg.task_id} | {msg.engine} | {msg.sanitizer} | "
                    f"{BuildType.Name(msg.build_type)} | diff {msg.apply_diff}"
                )
                try:
                    res = task.apply_patch_diff(Path(patch_file.name))
                    if not res:
                        logger.info(
                            f"Failed to apply patch for {msg.task_id} | {msg.engine} | "
                            f"{msg.sanitizer} | {BuildType.Name(msg.build_type)} | diff {msg.apply_diff}"
                        )
                        return False
                except ChallengeTaskError:
                    logger.exception(
                        "Failed to apply patch for %s | %s | %s | %s | diff %s",
                        msg.task_id,
                        msg.engine,
                        msg.sanitizer,
                        BuildType.Name(msg.build_type),
                        msg.apply_diff,
                    )
                    return False
        return True
    
    def process_item(self, item) -> bool:
        """Process a build request."""
        # Item should be a RedisQueueItem wrapper
        if not isinstance(item, RedisQueueItem):
            logger.error("Invalid item received in build worker")
            return False
        
        msg = item.deserialized
        logger.info(
            f"Received build request for {msg.task_id} | {msg.engine} | {msg.sanitizer} | "
            f"{BuildType.Name(msg.build_type)} | diff {msg.apply_diff}"
        )
        
        # Check if task should not be processed (expired or cancelled)
        if self.registry.should_stop_processing(msg.task_id):
            logger.info(f"Skipping expired or cancelled task {msg.task_id}")
            item.ack()
            return True
        
        task_dir = Path(msg.task_dir)
        if self.allow_caching:
            origin_task = ChallengeTask(
                task_dir,
                python_path=self.python,
                local_task_dir=task_dir,
            )
        else:
            origin_task = ChallengeTask(
                task_dir,
                python_path=self.python,
            )
        
        with origin_task.get_rw_copy(work_dir=self.wdir) as task:
            if not self._apply_challenge_diff(task, msg):
                # Check max tries
                if item.times_delivered() > self.max_tries:
                    logger.error(
                        f"Max tries reached for {msg.task_id} | {msg.engine} | {msg.sanitizer} | "
                        f"{BuildType.Name(msg.build_type)} | diff {msg.apply_diff}"
                    )
                    item.ack()
                return True
            
            if not self._apply_patch(task, msg):
                # Check max tries
                if item.times_delivered() > self.max_tries:
                    logger.error(
                        f"Max tries reached for {msg.task_id} | {msg.engine} | {msg.sanitizer} | "
                        f"{BuildType.Name(msg.build_type)} | diff {msg.apply_diff} | patch {msg.internal_patch_id}"
                    )
                    item.ack()
                return True
            
            # Build with telemetry
            tracer = trace.get_tracer(__name__)
            with tracer.start_as_current_span("build_fuzzers_with_cache") as span:
                set_crs_attributes(
                    span,
                    crs_action_category=CRSActionCategory.BUILDING,
                    crs_action_name="build_fuzzers_with_cache",
                    task_metadata=dict(origin_task.task_meta.metadata),
                )
                res = task.build_fuzzers_with_cache(
                    engine=msg.engine, 
                    sanitizer=msg.sanitizer, 
                    pull_latest_base_image=self.allow_pull
                )
                
                if not res.success:
                    logger.error(
                        f"Could not build fuzzer {msg.task_id} | {msg.engine} | {msg.sanitizer} | "
                        f"{BuildType.Name(msg.build_type)} | diff {msg.apply_diff}"
                    )
                    span.set_status(Status(StatusCode.ERROR))
                    return True
                
                span.set_status(Status(StatusCode.OK))
            
            task.commit()
            logger.info(
                f"Pushing build output for {msg.task_id} | {msg.engine} | {msg.sanitizer} | "
                f"{BuildType.Name(msg.build_type)} | diff {msg.apply_diff}"
            )
            node_local.dir_to_remote_archive(task.task_dir)
            
            # Create build output
            build_output = BuildOutput(
                engine=msg.engine,
                sanitizer=msg.sanitizer,
                task_dir=str(task.task_dir),
                task_id=msg.task_id,
                build_type=msg.build_type,
                apply_diff=msg.apply_diff,
                internal_patch_id=msg.internal_patch_id,
            )
            
            # Push to both internal queue and Redis
            self.output_queue.put(build_output)
            self.redis_output_queue.push(build_output)
            
            logger.info(
                f"Acked build request for {msg.task_id} | {msg.engine} | {msg.sanitizer} | "
                f"{BuildType.Name(msg.build_type)} | diff {msg.apply_diff}"
            )
            
            # Ack the Redis queue item
            item.ack()
            
            return True