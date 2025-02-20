from buttercup.patcher.config import Settings, ServeCommand, ProcessCommand
from buttercup.patcher.patcher import Patcher
from pydantic_settings import get_subcommand
from buttercup.common.logger import setup_package_logger
import logging
from redis import Redis
from buttercup.patcher.utils import PatchInput
from pathlib import Path

logger = logging.getLogger(__name__)


def main():
    settings = Settings()
    command = get_subcommand(settings)
    setup_package_logger(__name__, settings.log_level)

    logger.info("Starting patcher")
    logger.debug("Settings: %s", settings)
    if isinstance(command, ServeCommand):
        logger.info("Serving...")
        redis = Redis.from_url(command.redis_url, decode_responses=False)
        patcher = Patcher(
            task_storage_dir=settings.task_storage_dir,
            scratch_dir=settings.scratch_dir,
            redis=redis,
            sleep_time=command.sleep_time,
            mock_mode=settings.mock_mode,
            dev_mode=settings.dev_mode,
        )
        patcher.serve()
    elif isinstance(command, ProcessCommand):
        logger.info("Processing task")
        patch_input = PatchInput(
            challenge_task_dir=command.challenge_task_dir,
            task_id=command.task_id,
            vulnerability_id=command.vulnerability_id,
            harness_name=command.harness_name,
            engine=command.engine,
            sanitizer=command.sanitizer,
            pov=Path(command.crash_input_path).read_bytes(),
            sanitizer_output=Path(command.stacktrace_path).read_bytes(),
        )
        patcher = Patcher(
            task_storage_dir=settings.task_storage_dir,
            scratch_dir=settings.scratch_dir,
            mock_mode=settings.mock_mode,
            dev_mode=settings.dev_mode,
        )
        patch = patcher.process_vulnerability(patch_input)
        if patch is not None:
            print(patch)


if __name__ == "__main__":
    main()
