import logging
from buttercup.program_model.program_model import ProgramModel
from buttercup.program_model.settings import (
    Settings,
    ServeCommand,
    ProcessCommand,
)
from buttercup.common.logger import setup_package_logger
from buttercup.common.telemetry import init_telemetry
from pydantic_settings import get_subcommand
from buttercup.common.datastructures.msg_pb2 import IndexRequest
from redis import Redis

logger = logging.getLogger(__name__)


def prepare_task(command: ProcessCommand) -> IndexRequest:
    """Prepares task for indexing."""

    return IndexRequest(
        task_dir=command.task_dir,
        task_id=command.task_id,
    )


def main() -> None:
    settings = Settings()
    command = get_subcommand(settings)
    setup_package_logger(
        "program-model", __name__, settings.log_level, settings.log_max_line_length
    )
    if isinstance(command, ServeCommand):
        init_telemetry("program-model")  # type: ignore[unreachable]
        redis = Redis.from_url(command.redis_url, decode_responses=False)
        with ProgramModel(
            sleep_time=command.sleep_time,
            redis=redis,
            wdir=settings.scratch_dir,
            script_dir=command.script_dir,
            kythe_dir=command.kythe_dir,
            python=command.python,
            allow_pull=command.allow_pull,
            base_image_url=command.base_image_url,
            graphdb_url=settings.graphdb_url,
            graphdb_enabled=settings.graphdb_enabled,
        ) as program_model:
            program_model.serve()
    elif isinstance(command, ProcessCommand):
        task = prepare_task(command)  # type: ignore[unreachable]
        with ProgramModel(
            wdir=settings.scratch_dir,
            script_dir=command.script_dir,
            kythe_dir=command.kythe_dir,
            python=command.python,
            allow_pull=command.allow_pull,
            base_image_url=command.base_image_url,
            graphdb_url=settings.graphdb_url,
            graphdb_enabled=settings.graphdb_enabled,
        ) as program_model:
            program_model.process_task(task)


if __name__ == "__main__":
    main()
