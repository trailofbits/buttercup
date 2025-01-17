import logging
import os
import requests
import tarfile
from pathlib import Path
import time
from typing import Optional
import hashlib

from buttercup.orchestrator.dependencies import get_task_queue, get_task_registry
from buttercup.common.queues import RQItem
from buttercup.common.datastructures.orchestrator_pb2 import Task, SourceDetail, TaskDownload

logger = logging.getLogger(__name__)


class Downloader:
    def __init__(self, download_dir: str, sleep_time: float = 1.0):
        self.download_dir = Path(download_dir)
        self.sleep_time = sleep_time
        self.task_queue = get_task_queue()
        self.task_registry = get_task_registry()

        # Create download directory if it doesn't exist
        self.download_dir.mkdir(parents=True, exist_ok=True)

    def get_source_type_dir(self, task_id: str, source_type: SourceDetail.SourceType) -> Path:
        """Creates and returns the directory path for a specific source type within a task"""
        source_type_name = SourceDetail.SourceType.Name(source_type).lower().replace("source_type_", "")
        dir_path = self.download_dir / str(task_id) / source_type_name
        dir_path.mkdir(parents=True, exist_ok=True)
        return dir_path.absolute()

    def download_source(self, task_id: str, source: SourceDetail) -> Optional[Path]:
        """Downloads a source file and verifies its SHA256"""
        try:
            response = requests.get(source.url, stream=True)
            response.raise_for_status()

            # Create directory structure and filename
            source_dir = self.get_source_type_dir(task_id, source.source_type)
            # Extract base filename before query parameters
            filename = source.url.split("/")[-1].split("?")[0]
            filepath = source_dir / filename
            logger.info(f"[task {task_id}] Downloading source type {source.source_type} to {filepath}")

            # Download and compute hash simultaneously
            sha256_hash = hashlib.sha256()

            with open(filepath, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        sha256_hash.update(chunk)
                        f.write(chunk)

            # Verify hash
            if sha256_hash.hexdigest() != source.sha256:
                logger.error(f"[task {task_id}] SHA256 mismatch for {source.url}")
                filepath.unlink()  # Delete file
                return None

            logger.info(f"[task {task_id}] Successfully downloaded source type {source.source_type} to {filepath}")
            return filepath

        except Exception as e:
            logger.error(f"Failed to download {source.url}: {str(e)}")
            return None

    def process_task(self, task: Task) -> bool:
        """Process a single task by downloading all its sources"""
        logger.info(f"Processing task {task.task_id}")

        success = True
        for source in task.sources:
            result = self.download_source(task.task_id, source)
            if result is None:
                success = False

            if result and (result.suffix.startswith(".tar") or result.name.endswith(".tar.gz")):
                try:
                    logger.info(f"[task {task.task_id}] Extracting {result}")
                    extract_path = result.parent

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

                    with tarfile.open(result) as tar:
                        # First verify all paths are safe
                        safe_extract(tar, extract_path)

                        # Get the first directory name in the tar
                        first_dir = next((m.name.split("/")[0] for m in tar.getmembers() if "/" in m.name), None)

                        if first_dir:
                            # Extract all members, modifying their paths to skip first directory
                            for member in tar.getmembers():
                                if member.name.startswith(first_dir + "/"):
                                    member.name = member.name[len(first_dir) + 1 :]
                                    if member.name:  # Only extract if there's a remaining path
                                        tar.extract(member, path=extract_path)
                        else:
                            # If no subdirectory found, extract normally but safely
                            for member in tar.getmembers():
                                tar.extract(member, path=extract_path)

                    logger.info(f"[task {task.task_id}] Successfully extracted {result}")
                    # Remove the tar file after successful extraction
                    result.unlink()
                    logger.info(f"[task {task.task_id}] Removed tar file {result}")
                except Exception as e:
                    logger.error(f"[task {task.task_id}] Failed to extract {result}: {str(e)}")
                    success = False

        return success

    def run(self):
        """Main loop to process tasks from queue"""
        logger.info("Starting downloader service")

        while True:
            rq_item: Optional[RQItem] = self.task_queue.pop()

            if rq_item is not None:
                task_download: TaskDownload = rq_item.deserialized
                task = self.task_registry.get_task(task_download.task_id)
                if task is None:
                    logger.warning(f"Task {task_download.task_id} not found in registry, skipping")
                    continue

                if task.task_status == Task.TaskStatus.TASK_STATUS_SUCCEEDED:
                    logger.info(f"Task {task_download.task_id} already succeeded, skipping")
                    self.task_queue.ack_item(rq_item)
                    continue

                task.task_status = Task.TaskStatus.TASK_STATUS_RUNNING
                self.task_registry.update_task(task_download.task_id, task)
                success = self.process_task(task)

                if success:
                    task.task_status = Task.TaskStatus.TASK_STATUS_SUCCEEDED
                    self.task_registry.update_task(task_download.task_id, task)
                    self.task_queue.ack_item(rq_item)
                    logger.info(f"Successfully processed task {task.task_id}")
                else:
                    logger.error(f"Failed to process task {task.task_id}")

            time.sleep(self.sleep_time)


def main():
    logging.basicConfig(level=logging.INFO)
    download_dir = os.environ.get("DOWNLOAD_DIR", "/tmp/task_downloads")
    sleep_time = float(os.environ.get("SLEEP_TIME", "1.0"))

    downloader = Downloader(download_dir, sleep_time)
    downloader.run()


if __name__ == "__main__":
    main()
