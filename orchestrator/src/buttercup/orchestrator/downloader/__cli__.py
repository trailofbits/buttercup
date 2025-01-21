from buttercup.orchestrator.downloader.downloader import Downloader
from buttercup.orchestrator.downloader.config import (
    DownloaderSettings,
    DownloaderServeCommand,
    DownloaderProcessCommand,
    TaskType,
)
from buttercup.orchestrator.logger import setup_logging
from pydantic_settings import get_subcommand
from buttercup.common.datastructures.orchestrator_pb2 import Task, SourceDetail
from redis import Redis
import requests.adapters
from requests_file import FileAdapter
import requests
import hashlib


def compute_url_sha256(session: requests.Session, url: str) -> str:
    response = session.get(url, stream=True)
    response.raise_for_status()
    sha256_hash = hashlib.sha256()
    for chunk in response.iter_content(chunk_size=8192):
        if chunk:
            sha256_hash.update(chunk)
    return sha256_hash.hexdigest()


def main():
    settings = DownloaderSettings()
    setup_logging(__name__, settings.log_level)
    command = get_subcommand(settings)
    if isinstance(command, DownloaderServeCommand):
        redis = Redis.from_url(command.redis_url, decode_responses=False)
        with Downloader(settings.download_dir, command.sleep_time, redis) as downloader:
            downloader.serve()
    elif isinstance(command, DownloaderProcessCommand):
        session = requests.Session()
        session.mount("file://", FileAdapter())

        task = Task()
        task.message_id = command.message_id
        task.message_time = command.message_time
        task.task_id = command.task_id
        task.task_type = (
            Task.TaskType.TASK_TYPE_FULL if command.task_type == TaskType.FULL else Task.TaskType.TASK_TYPE_DELTA
        )
        for repo_url in command.repo_url:
            source_detail = SourceDetail()
            source_detail.source_type = SourceDetail.SourceType.SOURCE_TYPE_REPO
            source_detail.url = repo_url
            source_detail.sha256 = compute_url_sha256(session, repo_url)
            task.sources.append(source_detail)
        for fuzz_tooling_url in command.fuzz_tooling_url:
            source_detail = SourceDetail()
            source_detail.source_type = SourceDetail.SourceType.SOURCE_TYPE_FUZZ_TOOLING
            source_detail.url = fuzz_tooling_url
            source_detail.sha256 = compute_url_sha256(session, fuzz_tooling_url)
            task.sources.append(source_detail)
        for diff_url in command.diff_url:
            source_detail = SourceDetail()
            source_detail.source_type = SourceDetail.SourceType.SOURCE_TYPE_DIFF
            source_detail.url = diff_url
            source_detail.sha256 = compute_url_sha256(session, diff_url)
            task.sources.append(source_detail)

        with Downloader(settings.download_dir) as downloader:
            # Allow to use file:// URLs in the downloader
            downloader.session = session
            downloader.process_task(task)


if __name__ == "__main__":
    main()
