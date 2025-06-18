import buttercup.patcher.cli_load_dotenv  # noqa: F401
from buttercup.patcher.config import Settings, ServeCommand, ProcessCommand, ProcessMsgCommand
from buttercup.patcher.patcher import Patcher
from pydantic_settings import get_subcommand
from buttercup.common.datastructures.msg_pb2 import ConfirmedVulnerability
from google.protobuf.text_format import Parse
from buttercup.common.logger import setup_package_logger
import logging
from redis import Redis
from buttercup.patcher.utils import PatchInput, PatchInputPoV
from pathlib import Path
from buttercup.common.queues import QueueFactory, QueueNames, GroupNames
from buttercup.common.telemetry import init_telemetry

logger = logging.getLogger(__name__)


def main() -> None:
    settings = Settings()
    command = get_subcommand(settings)
    setup_package_logger("patcher", __name__, settings.log_level, settings.log_max_line_length)

    logger.info("Starting patcher")
    logger.debug("Settings: %s", settings)
    init_telemetry("patcher")
    if isinstance(command, ServeCommand):
        logger.info("Serving...")  # type: ignore[unreachable]
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
        logger.info("Processing task")  # type: ignore[unreachable]
        patch_input = PatchInput(
            task_id=command.task_id,
            internal_patch_id=command.internal_patch_id,
            povs=[
                PatchInputPoV(
                    challenge_task_dir=command.challenge_task_dir,
                    harness_name=command.harness_name,
                    engine=command.engine,
                    sanitizer=command.sanitizer,
                    pov=Path(command.crash_input_path).read_bytes(),
                    sanitizer_output=Path(command.stacktrace_path).read_bytes(),
                )
            ],
        )
        patcher = Patcher(
            task_storage_dir=settings.task_storage_dir,
            scratch_dir=settings.scratch_dir,
            dev_mode=settings.dev_mode,
        )
        patch = patcher.process_patch_input(patch_input)
        if patch is not None:
            print(patch)
    elif isinstance(command, ProcessMsgCommand):
        logger.info("Processing message")  # type: ignore[unreachable]
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
