from buttercup.orchestrator.scheduler.config import (
    Settings,
    ServeCommand,
    ProcessBuildOutputCommand,
    ProcessReadyTaskCommand,
)
from buttercup.orchestrator.scheduler.scheduler import Scheduler
from buttercup.common.logger import setup_package_logger
from pydantic_settings import get_subcommand
from redis import Redis
from buttercup.orchestrator.scheduler.scheduler import Task, BuildOutput


def _prepare_ready_task(command: ProcessReadyTaskCommand) -> Task:
    return Task(
        task_id=command.task_id,
        task_type=command.task_type,
        task_status=command.task_status,
    )


def _prepare_build_output(command: ProcessBuildOutputCommand) -> BuildOutput:
    return BuildOutput(
        package_name=command.package_name,
        engine=command.engine,
        sanitizer=command.sanitizer,
        output_ossfuzz_path=command.output_ossfuzz_path,
        source_path=command.source_path,
    )


def main():
    settings = Settings()
    setup_package_logger(__name__, settings.log_level)
    command = get_subcommand(settings)
    if isinstance(command, ServeCommand):
        redis = Redis.from_url(command.redis_url, decode_responses=False)
        scheduler = Scheduler(
            settings.tasks_storage_dir,
            settings.scratch_dir,
            redis,
            sleep_time=command.sleep_time,
            competition_api_url=command.competition_api_url,
        )
        scheduler.serve()
    elif isinstance(command, ProcessReadyTaskCommand):
        scheduler = Scheduler(settings.tasks_storage_dir, settings.scratch_dir)
        task = _prepare_ready_task(command)
        build_request = scheduler.process_ready_task(task)
        print(build_request)
    elif isinstance(command, ProcessBuildOutputCommand):
        scheduler = Scheduler(settings.tasks_storage_dir, settings.scratch_dir)
        build_output = _prepare_build_output(command)
        targets = scheduler.process_build_output(build_output)
        print(targets)


if __name__ == "__main__":
    main()
