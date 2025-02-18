import logging
from buttercup.program_model.program_model import ProgramModel
from buttercup.program_model.settings import (
    ProgramModelSettings,
    ProgramModelServeCommand,
    ProgramModelProcessCommand,
)
from buttercup.common.logger import setup_package_logger
from pydantic_settings import get_subcommand
from buttercup.common.datastructures.msg_pb2 import IndexRequest
from redis import Redis

logger = logging.getLogger(__name__)


def prepare_task(command: ProgramModelProcessCommand) -> IndexRequest:
    """Prepares task for indexing."""

    return IndexRequest(
        package_name=command.package_name,
        sanitizer=command.sanitizer,
        ossfuzz=command.ossfuzz,
        source_path=command.source_path,
        task_id=command.task_id,
        build_type=command.build_type,
    )


def main():
    settings = ProgramModelSettings()
    setup_package_logger(__name__, settings.log_level)
    command = get_subcommand(settings)
    if isinstance(command, ProgramModelServeCommand):
        redis = Redis.from_url(command.redis_url, decode_responses=False)
        with ProgramModel(
            sleep_time=command.sleep_time,
            redis=redis,
            wdir=command.wdir,
            script_dir=command.script_dir,
            kythe_dir=command.kythe_dir,
            python=command.python,
            allow_pull=command.allow_pull,
            base_image_url=command.base_image_url,
        ) as program_model:
            program_model.serve()
    elif isinstance(command, ProgramModelProcessCommand):
        task = prepare_task(command)
        with ProgramModel(
            wdir=command.wdir,
            script_dir=command.script_dir,
            kythe_dir=command.kythe_dir,
            python=command.python,
            allow_pull=command.allow_pull,
            base_image_url=command.base_image_url,
        ) as program_model:
            program_model.process_task(task)


if __name__ == "__main__":
    main()
