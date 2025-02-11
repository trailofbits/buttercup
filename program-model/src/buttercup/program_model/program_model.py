import logging
from dataclasses import dataclass, field
from buttercup.common.queues import RQItem, BuildConfiguration, QueueFactory, ReliableQueue, QueueNames, GroupNames
from buttercup.common.datastructures.msg_pb2 import IndexRequest
from buttercup.program_model.indexer.oss_fuzz_indexer import ProgramIndex
from buttercup.program_model.indexer.entries_into_graphml import GraphStorage
from pathlib import Path
from redis import Redis
import shutil
import time
import uuid
import os

logger = logging.getLogger(__name__)

@dataclass
class ProgramModel:
    sleep_time: float = 0.1
    redis: Redis | None = None
    task_queue: ReliableQueue | None = field(init=False, default=None)
    ready_queue: ReliableQueue | None = field(init=False, default=None)

    def __post_init__(self):
        if self.redis is not None:
            logger.debug("Using Redis for task queues")
            queue_factory = QueueFactory(self.redis)
            self.task_queue = queue_factory.create(QueueNames.INDEX, GroupNames.INDEX)
            self.ready_queue = queue_factory.create(QueueNames.READY_TASKS)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.cleanup()

    def cleanup(self):
        """Cleanup resources used by the program model"""
        pass

    def process_task(self, args: IndexRequest) -> bool:
        """Process a single task by downloading all its sources"""
        logger.info(f"Processing task {args}")

        # TODO- Create read write copy of challenge
        tsk = ChallengeTask(
            read_only_task_dir=build.task_dir, project_name=build.package_name, python_path=self.python
        )
        # Get path info from tsk

        # Index the program
        indexer = ProgramIndex()
        indexer_input = ProgramIndexInput(
            oss_fuzz_dir=args.oss_fuzz_dir,
            package_name=args.package_name,
            kythe_dir=args.kythe_dir,
            work_dir=args.work_dir,
        )
        res = indexer.get(indexer_input)
        if res is None:
            logger.error(f"Failed to index program {args.package_name}")
            return False
        else:
            logger.info(f"Successfully indexed program {args.package_name}")

#       # Store the program into a graph database
#       grapher = GraphStorage()
#       grapher_input = GraphStorageInput(
#           indexer=indexer,
#           url=args.url,
#           package_name=args.package_name,
#           wdir=args.wdir,
#       )
#       res = grapher.get(grapher_input)
#       if res is None:
#           logger.error(f"Failed to store program {args.package_name} in graph database")
#           return False
#       else:
#           logger.info(f"Successfully stored program {args.package_name} in graph database")

        return True


    def serve(self):
        """Main loop to process tasks from queue"""
        if self.task_queue is None:
            raise ValueError("Task queue is not initialized")

        if self.ready_queue is None:
            raise ValueError("Ready queue is not initialized")

        logger.info("Starting downloader service")

        while True:
            rq_item: Optional[RQItem] = self.task_queue.pop()

            if rq_item is not None:
                task_index: IndexRequest = rq_item.deserialized
                success = self.process_task(task_index)

                if success:
                    self.ready_queue.push(TaskReady(task=task_index))
                    self.task_queue.ack_item(rq_item.item_id)
                    logger.info(f"Successfully processed task {task_index.task_id}")
                else:
                    logger.error(f"Failed to process task {task_index.task_id}")

            logger.info(f"Sleeping for {self.sleep_time} seconds")
            time.sleep(self.sleep_time)
