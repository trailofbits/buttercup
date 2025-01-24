import logging
import requests
import tarfile
from dataclasses import dataclass, field
import uuid
import tempfile
from pathlib import Path
import time
from typing import Optional
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from buttercup.common.queues import RQItem, QueueFactory, ReliableQueue
from buttercup.common.datastructures.orchestrator_pb2 import Task, SourceDetail, TaskDownload
from buttercup.orchestrator.utils import response_stream_to_file
from redis import Redis
from buttercup.orchestrator.registry import TaskRegistry

logger = logging.getLogger(__name__)


@dataclass
class Downloader:
    download_dir: Path
    sleep_time: float = 0.1
    redis: Redis | None = None
    task_queue: ReliableQueue | None = field(init=False, default=None)
    registry: TaskRegistry | None = field(init=False, default=None)
    session: requests.Session = field(init=False, default=None)

    def __post_init__(self):
        if self.redis is not None:
            logger.debug("Using Redis for task queue and registry")
            queue_factory = QueueFactory(self.redis)
            self.task_queue = queue_factory.create_download_tasks_queue()
            self.registry = TaskRegistry(self.redis)

        # Create download directory if it doesn't exist
        self.download_dir.mkdir(parents=True, exist_ok=True)

        # Initialize session with retry strategy and connection pooling
        self.session = requests.Session()
        retry_strategy = Retry(
            total=3,  # number of retries
            backoff_factor=1,  # wait 1, 2, 4 seconds between retries
            status_forcelist=[500, 502, 503, 504],  # HTTP status codes to retry on
        )
        adapter = HTTPAdapter(
            pool_connections=100,  # number of connections to keep in pool
            pool_maxsize=100,  # maximum number of connections in pool
            max_retries=retry_strategy,
        )
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)

    def get_task_dir(self, task_id: str) -> Path:
        """Creates and returns the directory path for a task"""
        task_dir = self.download_dir / task_id
        return task_dir.absolute()

    def download_source(self, task_id: str, tmp_task_dir: Path, source: SourceDetail) -> Optional[Path]:
        """Downloads a source file and verifies its SHA256"""
        try:
            filepath = tmp_task_dir / str(uuid.uuid4())
            logger.info(f"[task {task_id}] Downloading source type {source.source_type} to {filepath}")

            # Download and compute hash simultaneously
            sha256_hash = response_stream_to_file(self.session, source.url, filepath)

            # Verify hash
            if sha256_hash != source.sha256:
                logger.error(f"[task {task_id}] SHA256 mismatch for {source.url}")
                return None

            logger.info(f"[task {task_id}] Successfully downloaded source type {source.source_type} to {filepath}")
            return filepath
        except Exception as e:
            logger.error(f"Failed to download {source.url}: {str(e)}")
            return None

    def extract_source(self, task_id: str, tmp_task_dir: Path, source_file: Path) -> Optional[Path]:
        """Uncompress a source file and returns the name of the main directory it contains"""
        try:
            logger.info(f"[task {task_id}] Extracting {source_file}")
            tmp_task_dir.mkdir(parents=True, exist_ok=True)

            def is_within_directory(directory: Path, target: Path) -> bool:
                try:
                    target.relative_to(directory)
                    return True
                except ValueError:
                    return False

            def safe_extract(tar, path: Path) -> None:
                for member in tar.getmembers():
                    member_path = path / member.name
                    if not is_within_directory(path, member_path):
                        raise Exception("Attempted path traversal in tar file")

            with tarfile.open(source_file) as tar:
                # First verify all paths are safe
                safe_extract(tar, tmp_task_dir)

                # Get the name of the main directory
                main_dir = tar.getmembers()[0].name

                # Extract all members directly into tmp_task_dir
                for member in tar.getmembers():
                    tar.extract(member, path=tmp_task_dir)

            logger.info(f"[task {task_id}] Successfully extracted {source_file}")
            # Remove the tar file after successful extraction
            source_file.unlink()
            logger.info(f"[task {task_id}] Removed tar file {source_file}")
            return main_dir
        except Exception as e:
            logger.error(f"[task {task_id}] Failed to extract {source_file}: {str(e)}")
            return None

    def process_task(self, task: Task) -> bool:
        """Process a single task by downloading all its sources"""
        logger.info(f"Processing task {task.task_id} (message_id={task.message_id})")

        success = True
        with tempfile.TemporaryDirectory(dir=self.download_dir) as tmp_task_dir:
            tmp_task_dir = Path(tmp_task_dir)
            logger.info(f"[task {task.task_id}] Using temporary directory {tmp_task_dir}")

            for source in task.sources:
                # Create temporary directory for download
                with tempfile.TemporaryDirectory() as temp_dir:
                    temp_path = Path(temp_dir)
                    result = self.download_source(task.task_id, temp_path, source)
                    if result is None:
                        success = False
                        break

                    extracted_dir = self.extract_source(task.task_id, tmp_task_dir, result)
                    if not extracted_dir:
                        success = False
                        break

                    source.path = extracted_dir

            if success:
                # Once everything is downloaded and uncompressed in the
                # temporary directory, rename the directory to the task id
                # (atomically)
                final_task_dir = self.get_task_dir(task.task_id)
                try:
                    tmp_task_dir.rename(final_task_dir)
                    logger.info(f"[task {task.task_id}] Successfully moved task directory to final location")
                except Exception as e:
                    logger.warning(
                        f"Failed to rename {tmp_task_dir} to {final_task_dir}, something else has already downloaded the task: {str(e)}"
                    )
                    logger.warning("Ignore the error and continue as if the task was successfully processed")
                    success = True

        return success

    def serve(self):
        """Main loop to process tasks from queue"""
        if self.task_queue is None:
            raise ValueError("Task queue is not initialized")

        logger.info("Starting downloader service")

        while True:
            rq_item: Optional[RQItem] = self.task_queue.pop()

            if rq_item is not None:
                task_download: TaskDownload = rq_item.deserialized
                success = self.process_task(task_download.task)

                if success:
                    self.registry.set(task_download.task)
                    self.task_queue.ack_item(rq_item.item_id)
                    logger.info(f"Successfully processed task {task_download.task.task_id}")
                else:
                    logger.error(f"Failed to process task {task_download.task.task_id}")

            time.sleep(self.sleep_time)

    def cleanup(self):
        """Cleanup resources used by the downloader"""
        if self.session:
            self.session.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.cleanup()
