import logging

from pydantic_settings import get_subcommand
from redis import Redis

from buttercup.common.datastructures.msg_pb2 import IndexRequest
from buttercup.common.logger import setup_package_logger
from buttercup.common.telemetry import init_telemetry
from buttercup.program_model.program_model import ProgramModel
from buttercup.program_model.settings import (
    ProcessCommand,
    ServeCommand,
    Settings,
)

logger = logging.getLogger(__name__)


def prepare_task(command: ProcessCommand) -> IndexRequest:
    """Prepares task for indexing."""
    return IndexRequest(
        task_dir=command.task_dir,
        task_id=command.task_id,
    )


def main() -> None:
    settings = Settings()  # type: ignore[call-arg]
    command = get_subcommand(settings)
    setup_package_logger("program-model", __name__, settings.log_level, settings.log_max_line_length)
    if isinstance(command, ServeCommand):
        init_telemetry("program-model")
        redis = Redis.from_url(command.redis_url, decode_responses=False)
        with ProgramModel(
            sleep_time=command.sleep_time,
            redis=redis,
            wdir=settings.scratch_dir,
            python=command.python,
            allow_pull=command.allow_pull,
        ) as program_model:
            program_model.serve()
    elif isinstance(command, ProcessCommand):
        task = prepare_task(command)
        with ProgramModel(
            wdir=settings.scratch_dir,
            python=command.python,
            allow_pull=command.allow_pull,
        ) as program_model:
            program_model.process_task(task)


if __name__ == "__main__":
    main()
