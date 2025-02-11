from buttercup.program_model.program_model import ProgramModel
from buttercup.program_model.config import (
    ProgramModelSettings,
    ProgramModelServeCommand,
    ProgramModelProcessCommand,
    TaskType,
)
from buttercup.common.logger import setup_logging
from pydantic_settings import get_subcommand
from buttercup.common.datastructures.msg_pb2 import IndexRequest
from redis import Redis
import requests.adapters
import requests


def prepare_task(command: ProgramModelProcessCommand) -> IndexRequest:
    task = IndexRequest()
    task.package_name = command.package_name
    task.ossfuzz = command.ossfuzz
    task.source_path = command.source_path
    task.task_id = command.task_id
    task.build_type = command.build_type

    return task


def main():
    settings = ProgramModelSettings()
    setup_logging(__name__, settings.log_level)
    command = get_subcommand(settings)
    if isinstance(command, ProgramModelServeCommand):
        redis = Redis.from_url(command.redis_url, decode_responses=False)
        with ProgramModel(command.sleep_time, redis) as program_model:
            program_model.serve()
    elif isinstance(command, ProgramModelProcessCommand):
        task = prepare_task(command)
        with ProgramModel() as program_model:
            program_model.process_task(task)


if __name__ == "__main__":
    main()
