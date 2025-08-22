import requests
import requests.adapters
from pydantic_settings import get_subcommand
from redis import Redis
from requests_file import FileAdapter

from buttercup.common.datastructures.msg_pb2 import SourceDetail, Task
from buttercup.common.logger import setup_package_logger
from buttercup.orchestrator.downloader.config import (
    DownloaderProcessCommand,
    DownloaderServeCommand,
    DownloaderSettings,
    TaskType,
)
from buttercup.orchestrator.downloader.downloader import Downloader
from buttercup.orchestrator.utils import response_stream_to_file


def prepare_task(command: DownloaderProcessCommand, session: requests.Session) -> Task:
    task = Task()
    task.message_id = command.message_id
    task.message_time = command.message_time
    task.task_id = command.task_id
    task.project_name = command.project_name
    task.focus = command.focus
    task.cancelled = False
    task.task_type = (
        Task.TaskType.TASK_TYPE_FULL if command.task_type == TaskType.FULL else Task.TaskType.TASK_TYPE_DELTA
    )
    for repo_url in command.repo_url:
        source_detail = SourceDetail()
        source_detail.source_type = SourceDetail.SourceType.SOURCE_TYPE_REPO
        source_detail.url = repo_url
        source_detail.sha256 = response_stream_to_file(session, repo_url)
        task.sources.append(source_detail)
    for fuzz_tooling_url in command.fuzz_tooling_url:
        source_detail = SourceDetail()
        source_detail.source_type = SourceDetail.SourceType.SOURCE_TYPE_FUZZ_TOOLING
        source_detail.url = fuzz_tooling_url
        source_detail.sha256 = response_stream_to_file(session, fuzz_tooling_url)
        task.sources.append(source_detail)
    for diff_url in command.diff_url:
        source_detail = SourceDetail()
        source_detail.source_type = SourceDetail.SourceType.SOURCE_TYPE_DIFF
        source_detail.url = diff_url
        source_detail.sha256 = response_stream_to_file(session, diff_url)
        task.sources.append(source_detail)

    return task


def main() -> None:
    settings = DownloaderSettings()
    setup_package_logger("task-downloader", __name__, settings.log_level, settings.log_max_line_length)
    command = get_subcommand(settings)
    if isinstance(command, DownloaderServeCommand):
        redis = Redis.from_url(command.redis_url, decode_responses=False)  # type: ignore[unreachable]
        with Downloader(settings.download_dir, command.sleep_time, redis) as downloader:
            downloader.serve()
    elif isinstance(command, DownloaderProcessCommand):
        # Allow to use file:// URLs in the downloader
        session = requests.Session()  # type: ignore[unreachable]
        session.mount("file://", FileAdapter())

        task = prepare_task(command, session)
        with Downloader(settings.download_dir) as downloader:
            downloader.session = session
            downloader.process_task(task)


if __name__ == "__main__":
    main()
