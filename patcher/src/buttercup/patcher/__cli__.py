from buttercup.patcher.config import Settings, ServeCommand, ProcessCommand
from buttercup.patcher.patcher import Patcher
from pydantic_settings import get_subcommand
from buttercup.common.logger import setup_logging
import logging
from redis import Redis
from buttercup.patcher.utils import PatchInput
from pathlib import Path


def main():
    settings = Settings()
    command = get_subcommand(settings)
    setup_logging(__name__, settings.log_level)
    logger = logging.getLogger(__name__)

    logger.info("Starting patcher")
    if isinstance(command, ServeCommand):
        logger.info("Serving...")
        redis = Redis.from_url(command.redis_url, decode_responses=False)
        patcher = Patcher(
            settings.task_storage_dir,
            redis,
            sleep_time=command.sleep_time,
            mock_mode=settings.mock_mode,
        )
        patcher.serve()
    elif isinstance(command, ProcessCommand):
        logger.info("Processing task")
        patch_input = PatchInput(
            challenge_task_dir=command.challenge_task_dir,
            task_id=command.task_id,
            vulnerability_id=command.vulnerability_id,
            project_name=command.project_name,
            harness_name=command.harness_name,
            engine=command.engine,
            sanitizer=command.sanitizer,
            pov=Path(command.crash_input_path).read_bytes(),
            stacktrace=Path(command.stacktrace_path).read_text(),
        )
        patcher = Patcher(
            task_storage_dir=settings.task_storage_dir,
            mock_mode=settings.mock_mode,
        )
        patch = patcher.process_vulnerability(patch_input)
        if patch is not None:
            print(patch)


if __name__ == "__main__":
    main()
