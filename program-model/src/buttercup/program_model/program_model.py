import logging
import os
import stat
from dataclasses import dataclass, field
from buttercup.common.queues import (
    QueueFactory,
    ReliableQueue,
    QueueNames,
    GroupNames,
)
from buttercup.program_model.indexer import Indexer, IndexConf
from buttercup.program_model.kythe import KytheTool, KytheConf
from buttercup.program_model.graph import GraphStorage
from buttercup.program_model.codequery import CodeQueryPersistent
from buttercup.common.datastructures.msg_pb2 import IndexRequest, IndexOutput
from buttercup.common.challenge_task import ChallengeTask
from buttercup.common.utils import serve_loop
from pathlib import Path
from redis import Redis
import subprocess
import uuid
import tempfile

logger = logging.getLogger(__name__)


@dataclass
class ProgramModel:
    sleep_time: float = 1.0
    redis: Redis | None = None
    task_queue: ReliableQueue | None = field(init=False, default=None)
    output_queue: ReliableQueue | None = field(init=False, default=None)
    wdir: Path | None = None
    script_dir: Path | None = None
    kythe_dir: Path | None = None
    graphdb_url: str = "ws://graphdb:8182/gremlin"
    python: str | None = None
    allow_pull: bool = True
    base_image_url: str = "gcr.io/oss-fuzz"

    def __post_init__(self):
        """Post-initialization setup."""
        self.wdir = Path(self.wdir).resolve()
        self.script_dir = Path(self.script_dir).resolve()
        self.kythe_dir = Path(self.kythe_dir).resolve()

        if self.redis is not None:
            logger.debug("Using Redis for task queues")
            queue_factory = QueueFactory(self.redis)
            self.task_queue = queue_factory.create(QueueNames.INDEX, GroupNames.INDEX)
            self.output_queue = queue_factory.create(QueueNames.INDEX_OUTPUT)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.cleanup()

    def cleanup(self):
        """Cleanup resources used by the program model"""
        pass

    def process_task_kythe(self, args: IndexRequest) -> bool:
        """Process a single task for indexing a program"""
        # Convert path strings to Path objects
        logger.debug(f"Kythe dir: {self.kythe_dir}")
        logger.debug(f"Script dir: {self.script_dir}")
        logger.debug(f"Wdir: {self.wdir}")
        logger.debug(f"Python: {self.python}")
        logger.debug(f"Allow pull: {self.allow_pull}")
        logger.debug(f"Base image URL: {self.base_image_url}")

        with tempfile.TemporaryDirectory(dir=self.wdir) as td:
            logger.info(
                f"Running indexer for {args.package_name} | {args.task_dir} | {args.task_id}"
            )

            # Change permissions so that JanusGraph can read from the temporary directory
            current = os.stat(td).st_mode
            janus_user = stat.S_IRGRP | stat.S_IROTH | stat.S_IXGRP | stat.S_IXOTH
            os.chmod(td, current | janus_user)

            tsk = ChallengeTask(
                read_only_task_dir=args.task_dir,
                python_path=self.python,
            )

            with tsk.get_rw_copy(work_dir=td) as local_tsk:
                logger.debug(f"Local path: {local_tsk.local_task_dir}")

                # Apply the diff if it exists
                logger.info(f"Applying diff for {args.package_name} {args.task_id}")
                if not local_tsk.apply_patch_diff():
                    logger.info(f"No diffs for {args.package_name} {args.task_id}")

                # Index the task
                try:
                    indexer_conf = IndexConf(
                        scriptdir=self.script_dir,
                        python=self.python,
                        allow_pull=self.allow_pull,
                        base_image_url=self.base_image_url,
                        wdir=td,
                    )
                    indexer = Indexer(indexer_conf)
                    output_dir = indexer.index_target(local_tsk)
                except Exception as e:
                    logger.error(f"Failed to index task {args.task_id}: {e}")
                    return False
                if output_dir is None:
                    logger.error(f"Failed to index task {args.task_id}")
                    return False
                logger.info(f"Successfully indexed task {args.task_id}")

                # Merge index files
                try:
                    output_id = str(uuid.uuid4())
                    ktool = KytheTool(KytheConf(self.kythe_dir))
                    merged_kzip = Path(td) / f"kythe_output_merge_{output_id}.kzip"
                    ktool.merge_kythe_output(output_dir, merged_kzip)
                except Exception as e:
                    logger.error(f"Failed to merge index files for {args.task_id}: {e}")
                    return False

                # Convert the merged kzip file into a binary file
                bin_file = Path(td) / f"kythe_output_cxx_{output_id}.bin"
                try:
                    ktool.cxx_index(merged_kzip, bin_file)
                    logger.info(
                        f"Successfully indexed program {args.task_id} to binary: {bin_file}"
                    )
                except subprocess.CalledProcessError:
                    # TODO(Evan): For now, if this errors just keep going. After fixing kythe issues, add "return False" or just remove this exception entirely
                    logger.error(
                        f"Failed to index program {args.task_id} to binary: {bin_file}"
                    )
                except Exception as e:
                    logger.error(
                        f"Failed to index program {args.task_id} to binary {bin_file}: {e}"
                    )
                    return False

                # Store the program into a graphml file
                try:
                    graphml = Path(td) / f"kythe_output_graphml_{output_id}.xml"
                    with open(graphml, "w") as fw, open(bin_file, "rb") as fr:
                        gs = GraphStorage(task_id=args.task_id)
                        gs.process_stream(fr)
                        fw.write(gs.to_graphml())
                        logger.info(
                            f"Successfully stored program {args.task_id} in graphml file: {graphml}"
                        )
                except Exception as e:
                    logger.error(
                        f"Failed to store program {args.task_id} in graphml file {graphml}: {e}"
                    )
                    return False
                logger.debug("Loading graphml file into JanusGraph...")

                # TODO(Evan): This needs to wait until JanusGraph is ready. For some reason, even if the container is running and healthy, it's not ready to accept connections.

                # Load graphml file into JanusGraph
                from gremlin_python.process.anonymous_traversal import traversal
                from gremlin_python.driver.driver_remote_connection import (
                    DriverRemoteConnection,
                )

                try:
                    g = traversal().withRemote(
                        DriverRemoteConnection(self.graphdb_url, "g")
                    )
                    g.io(str(graphml)).read().iterate()
                except Exception as e:
                    logger.error(
                        f"Failed to load graphml file {graphml} into JanusGraph: {e}"
                    )
                    return False
                logger.debug("Successfully loaded graphml file into JanusGraph")

        return True

    def process_task_codequery(self, args: IndexRequest) -> bool:
        """Process a single task for indexing a program"""
        try:
            challenge = ChallengeTask(
                read_only_task_dir=args.task_dir,
                python_path=self.python,
            )
            CodeQueryPersistent(challenge, work_dir=self.wdir)

            return True
        except Exception:
            return False

    def process_task(self, args: IndexRequest) -> bool:
        """Process a single task for indexing a program"""
        # TODO: Switch once we have kythe working well
        # self.process_task_kythe(args)
        return self.process_task_codequery(args)

    def serve_item(self) -> bool:
        rq_item = self.task_queue.pop()
        if rq_item is None:
            return False

        task_index: IndexRequest = rq_item.deserialized
        success = self.process_task(task_index)

        if success:
            self.output_queue.push(
                IndexOutput(
                    build_type=task_index.build_type,
                    package_name=task_index.package_name,
                    sanitizer=task_index.sanitizer,
                    task_dir=task_index.task_dir,
                    task_id=task_index.task_id,
                )
            )
            self.task_queue.ack_item(rq_item.item_id)
            logger.info(f"Successfully processed task {task_index.task_id}")
        else:
            logger.error(f"Failed to process task {task_index.task_id}")

        return True

    def serve(self):
        """Main loop to process tasks from queue"""
        if self.task_queue is None:
            raise ValueError("Task queue is not initialized")

        if self.output_queue is None:
            raise ValueError("Output queue is not initialized")

        logger.info("Starting indexing service")
        serve_loop(self.serve_item, self.sleep_time)
