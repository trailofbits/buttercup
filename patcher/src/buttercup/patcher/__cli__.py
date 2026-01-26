import logging
from pathlib import Path

from buttercup.common.datastructures.msg_pb2 import ConfirmedVulnerability
from buttercup.common.logger import setup_package_logger
from buttercup.common.queues import GroupNames, QueueFactory, QueueNames
from buttercup.common.telemetry import init_telemetry
from google.protobuf.text_format import Parse
from pydantic_settings import get_subcommand
from redis import Redis

import buttercup.patcher.cli_load_dotenv  # noqa: F401
from buttercup.patcher.config import ProcessCommand, ProcessMsgCommand, ServeCommand, Settings
from buttercup.patcher.patcher import Patcher
from buttercup.patcher.utils import PatchInput, PatchInputPoV

logger = logging.getLogger(__name__)


def main() -> None:
    settings = Settings()  # type: ignore[missing-argument]
    command = get_subcommand(settings)
    setup_package_logger("patcher", __name__, settings.log_level, settings.log_max_line_length)

    logger.info("Starting patcher")
    logger.debug("Settings: %s", settings)
    init_telemetry("patcher")
    if isinstance(command, ServeCommand):
        logger.info("Serving...")
        redis = Redis.from_url(command.redis_url, decode_responses=False)
        patcher = Patcher(
            task_storage_dir=settings.task_storage_dir,
            scratch_dir=settings.scratch_dir,
            redis=redis,
            sleep_time=command.sleep_time,
            dev_mode=settings.dev_mode,
        )
        patcher.serve()
    elif isinstance(command, ProcessCommand):
        logger.info("Processing task")
        patch_input = PatchInput(
            task_id=command.task_id,
            internal_patch_id=command.internal_patch_id,
            povs=[
                PatchInputPoV(
                    challenge_task_dir=command.challenge_task_dir,
                    harness_name=command.harness_name,
                    engine=command.engine,
                    sanitizer=command.sanitizer,
                    pov=Path(command.crash_input_path),
                    pov_token=f"token-{Path(command.crash_input_path).name}",
                    sanitizer_output=Path(command.stacktrace_path).read_text(),
                ),
            ],
        )
        patcher = Patcher(
            task_storage_dir=settings.task_storage_dir,
            scratch_dir=settings.scratch_dir,
            dev_mode=settings.dev_mode,
            find_tests=command.find_tests,
        )
        patch = patcher.process_patch_input(patch_input)
        if patch is not None:
            print(patch)
    elif isinstance(command, ProcessMsgCommand):
        logger.info("Processing message")
        redis = Redis.from_url(command.redis_url, decode_responses=False)
        patcher = Patcher(
            task_storage_dir=settings.task_storage_dir,
            scratch_dir=settings.scratch_dir,
            redis=redis,
            dev_mode=settings.dev_mode,
        )
        queue = QueueFactory(redis).create(QueueNames.CONFIRMED_VULNERABILITIES, GroupNames.PATCHER)
        msg = Parse(command.msg_path.read_text(), ConfirmedVulnerability())
        queue.push(msg)
        patcher.process_item(queue.pop())


if __name__ == "__main__":
    main()
