import logging
import requests
import tarfile
from dataclasses import dataclass, field
import uuid
import tempfile
from pathlib import Path
from typing import Optional
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from buttercup.common.queues import QueueFactory, ReliableQueue, QueueNames, GroupNames
from buttercup.common.datastructures.msg_pb2 import Task, SourceDetail, TaskDownload, TaskReady
from buttercup.orchestrator.utils import response_stream_to_file
from buttercup.common.task_meta import TaskMeta
from redis import Redis
from buttercup.common.task_registry import TaskRegistry
from buttercup.common.utils import serve_loop
import buttercup.common.node_local as node_local

logger = logging.getLogger(__name__)


@dataclass
class Downloader:
    download_dir: Path
    sleep_time: float = 0.1
    redis: Redis | None = None
    task_queue: ReliableQueue | None = field(init=False, default=None)
    ready_queue: ReliableQueue | None = field(init=False, default=None)
    registry: TaskRegistry | None = field(init=False, default=None)
    session: requests.Session = field(init=False, default=None)

    def __post_init__(self):
        if self.redis is not None:
            logger.debug("Using Redis for task queue and registry")
            queue_factory = QueueFactory(self.redis)
            self.task_queue = queue_factory.create(QueueNames.DOWNLOAD_TASKS, GroupNames.ORCHESTRATOR)
            self.ready_queue = queue_factory.create(QueueNames.READY_TASKS)
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
        return self.download_dir / task_id

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

    def _get_source_type_dir(self, source_type: SourceDetail.SourceType) -> str:
        if source_type == SourceDetail.SourceType.SOURCE_TYPE_REPO:
            return "src"
        elif source_type == SourceDetail.SourceType.SOURCE_TYPE_FUZZ_TOOLING:
            return "fuzz-tooling"
        elif source_type == SourceDetail.SourceType.SOURCE_TYPE_DIFF:
            return "diff"
        else:
            raise ValueError(f"Unknown source type: {source_type}")

    def extract_source(self, task_id: str, tmp_task_dir: Path, source: SourceDetail, source_file: Path) -> bool:
        """Uncompress a source file and returns the name of the main directory it contains"""
        try:
            logger.info(f"[task {task_id}] Extracting {source.url}")
            destination = tmp_task_dir / self._get_source_type_dir(source.source_type)
            destination.mkdir(parents=True, exist_ok=True)

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
                safe_extract(tar, destination)

                # Extract all members directly into tmp_task_dir
                for member in tar.getmembers():
                    tar.extract(member, path=destination)

            logger.info(f"[task {task_id}] Successfully extracted {source_file}")
            return True
        except Exception as e:
            logger.error(f"[task {task_id}] Failed to extract {source_file}: {str(e)}")
            return False

    def _download_and_extract_sources(self, task_id: str, tmp_task_dir: Path, sources: list) -> bool:
        """Download and extract all sources for a task"""
        for source in sources:
            # Create temporary directory for download
            with tempfile.TemporaryDirectory() as temp_dir:
                temp_path = Path(temp_dir)
                result = self.download_source(task_id, temp_path, source)
                if result is None:
                    return False

                if not self.extract_source(task_id, tmp_task_dir, source, result):
                    return False

        return True

    def _move_to_final_location(self, task_id: str, tmp_task_dir: Path) -> bool:
        """Move the temporary task directory to its final location"""
        final_task_dir = self.get_task_dir(task_id)
        try:
            tmp_task_dir.rename(final_task_dir)
            logger.info(f"[task {task_id}] Successfully moved task directory to {final_task_dir}")
            return True
        except OSError as e:
            # NOTE: Ignore if directory already exists or is not empty - another
            # process got there first. We can't just skip the task, because we
            # need to change the Task while downloading/extracting it.
            if "Directory not empty" in str(e):
                logger.warning(
                    f"Directory {final_task_dir} already exists, another process downloaded the task first, ignore it..."
                )
                return True
            else:
                logger.exception(f"Failed to move task directory: {str(e)}")
                return False
        except Exception as e:
            # Re-raise any other errors
            logger.exception(f"Failed to move task directory: {str(e)}")
            return False

    def process_task(self, task: Task) -> bool:
        """Process a single task by downloading all its sources"""
        logger.info(f"Processing task {task.task_id} (message_id={task.message_id})")

        # Node local target directory for the task
        download_path = self.get_task_dir(task.task_id)

        if download_path.exists():
            logger.warning(f"Remote path already exists: {download_path}. Skipping download.")
            return True

        logger.info(f"Storing task {task.task_id} at {download_path}")

        # Create a local temporary directory for the download, rename to the proper name and upload
        # the dir as a .tgz file to the remote storage
        with node_local.scratch_dir() as temp_dir:
            if not self._do_download(temp_dir, task):
                return False

            renamed_dir = node_local.rename_atomically(temp_dir.path, download_path)
            if renamed_dir is not None:
                temp_dir.commit = True
                node_local.dir_to_remote_archive(download_path)

        return True

    def _do_download(self, tmp_task_dir: tempfile.TemporaryDirectory, task: Task) -> bool:
        tmp_task_dir = Path(tmp_task_dir)
        logger.info(f"[task {task.task_id}] Using temporary directory {tmp_task_dir}")

        # Download and extract all sources
        success = self._download_and_extract_sources(task.task_id, tmp_task_dir, task.sources)
        if not success:
            logger.error(f"Failed to download and extract sources for task {task.task_id}")
            return False

        # Store the task meta in the tasks storage directory
        task_meta = TaskMeta(task.project_name, task.focus, task.task_id, dict(task.metadata))
        task_meta.save(tmp_task_dir)
        return True

    def serve_item(self) -> bool:
        rq_item = self.task_queue.pop()

        if rq_item is None:
            return False

        task_download: TaskDownload = rq_item.deserialized
        success = self.process_task(task_download.task)

        if success:
            self.registry.set(task_download.task)
            self.ready_queue.push(TaskReady(task=task_download.task))
            self.task_queue.ack_item(rq_item.item_id)
            logger.info(f"Successfully processed task {task_download.task.task_id}")
        else:
            logger.error(f"Failed to process task {task_download.task.task_id}")

        return True

    def serve(self):
        """Main loop to process tasks from queue"""
        if self.task_queue is None:
            raise ValueError("Task queue is not initialized")

        if self.ready_queue is None:
            raise ValueError("Ready queue is not initialized")

        logger.info("Starting downloader service")
        serve_loop(self.serve_item, self.sleep_time)

    def cleanup(self):
        """Cleanup resources used by the downloader"""
        if self.session:
            self.session.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.cleanup()
