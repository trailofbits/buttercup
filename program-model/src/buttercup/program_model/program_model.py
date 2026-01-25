import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode
from redis import Redis

from buttercup.common import node_local
from buttercup.common.challenge_task import ChallengeTask
from buttercup.common.datastructures.msg_pb2 import IndexOutput, IndexRequest
from buttercup.common.queues import (
    GroupNames,
    QueueFactory,
    QueueNames,
    ReliableQueue,
)
from buttercup.common.task_registry import TaskRegistry
from buttercup.common.telemetry import CRSActionCategory, set_crs_attributes
from buttercup.common.utils import serve_loop
from buttercup.program_model.codequery import CodeQueryPersistent

logger = logging.getLogger(__name__)


@dataclass
class ProgramModel:
    sleep_time: float = 1.0
    redis: Redis | None = None
    task_queue: ReliableQueue | None = field(init=False, default=None)
    output_queue: ReliableQueue | None = field(init=False, default=None)
    registry: TaskRegistry | None = field(init=False, default=None)
    wdir: Path | None = None
    python: str | None = None
    allow_pull: bool = True

    def __post_init__(self) -> None:
        """Post-initialization setup."""
        if self.wdir is not None:
            self.wdir = Path(self.wdir).resolve()

        if self.redis is not None:
            logger.debug("Using Redis for task queues")
            queue_factory = QueueFactory(self.redis)
            self.task_queue = queue_factory.create(QueueNames.INDEX, GroupNames.INDEX)
            self.output_queue = queue_factory.create(QueueNames.INDEX_OUTPUT)
            self.registry = TaskRegistry(self.redis)

    def __enter__(self):
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.cleanup()

    def cleanup(self) -> None:
        """Cleanup resources used by the program model"""

    def process_task_codequery(self, args: IndexRequest) -> bool:
        """Process a single task for indexing a program"""
        try:
            logger.info(f"Processing task {args.package_name}/{args.task_id}/{args.task_dir} with codequery")
            challenge = ChallengeTask(
                read_only_task_dir=args.task_dir,
                python_path=self.python or "python3",
            )
            with challenge.get_rw_copy(work_dir=self.wdir) as local_challenge:
                # Apply the diff if it exists
                logger.debug(f"Applying diff for {args.task_id}")

                if self.wdir is None:
                    raise ValueError("Work directory is not initialized")

                # log telemetry
                tracer = trace.get_tracer(__name__)
                with tracer.start_as_current_span("index_task_with_codequery") as span:
                    set_crs_attributes(
                        span,
                        crs_action_category=CRSActionCategory.PROGRAM_ANALYSIS,
                        crs_action_name="index_task_with_codequery",
                        task_metadata=dict(challenge.task_meta.metadata),
                    )
                    # No need to pass tasks_storage because the IndexRequest
                    # already uses the original task
                    cqp = CodeQueryPersistent(local_challenge, work_dir=self.wdir)
                    logger.info(
                        f"Successfully processed task {args.package_name}/{args.task_id}/{args.task_dir} with codequery",  # noqa: E501
                    )
                    span.set_status(Status(StatusCode.OK))
                # Push it to the remote storage
                node_local.dir_to_remote_archive(cqp.challenge.task_dir)
            return True
        except Exception as e:
            logger.exception(f"Failed to process task {args.task_id}: {e}")
            return False

    def process_task(self, args: IndexRequest) -> bool:
        """Process a single task for indexing a program"""
        logger.info(f"Processing task {args.package_name}/{args.task_id}/{args.task_dir}")
        return self.process_task_codequery(args)

    def serve_item(self) -> bool:
        if self.task_queue is None:
            raise ValueError("Task queue is not initialized")
        rq_item = self.task_queue.pop()
        if rq_item is None:
            return False

        task_index: IndexRequest = rq_item.deserialized

        # Check if task should be processed or skipped
        if self.registry is not None and self.registry.should_stop_processing(task_index.task_id):
            logger.debug(f"Task {task_index.task_id} is cancelled or expired, skipping")
            self.task_queue.ack_item(rq_item.item_id)
            return True

        success = self.process_task(task_index)

        if success:
            if self.output_queue is None:
                raise ValueError("Output queue is not initialized")
            self.output_queue.push(
                IndexOutput(
                    build_type=task_index.build_type,
                    package_name=task_index.package_name,
                    sanitizer=task_index.sanitizer,
                    task_dir=task_index.task_dir,
                    task_id=task_index.task_id,
                ),
            )
            self.task_queue.ack_item(rq_item.item_id)
            logger.info(
                f"Successfully processed task {task_index.package_name}/{task_index.task_id}/{task_index.task_dir}",
            )
        else:
            logger.error(f"Failed to process task {task_index.task_id}")

        return True

    def serve(self) -> None:
        """Main loop to process tasks from queue"""
        if self.task_queue is None:
            raise ValueError("Task queue is not initialized")

        if self.output_queue is None:
            raise ValueError("Output queue is not initialized")

        logger.debug("Starting indexing service")
        serve_loop(self.serve_item, self.sleep_time)
