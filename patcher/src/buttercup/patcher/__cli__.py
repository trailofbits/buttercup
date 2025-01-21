from buttercup.patcher.config import Settings, ServeCommand, ProcessCommand
from buttercup.patcher.patcher import Patcher
from pydantic_settings import get_subcommand
from buttercup.common.logger import setup_logging
from buttercup.common.datastructures.orchestrator_pb2 import TaskVulnerability
import logging
from redis import Redis


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
        task_vulnerability = TaskVulnerability(
            task_id=command.task_id,
            vulnerability_id=command.vulnerability_id,
            package_name=command.package_name,
            sanitizer=command.sanitizer,
            harness_path=command.harness_path,
            data_file=command.data_file,
            architecture=command.architecture,
        )
        patcher = Patcher(
            task_storage_dir=settings.task_storage_dir,
            mock_mode=settings.mock_mode,
        )
        patch = patcher.process_vulnerability(task_vulnerability)
        print(patch.patch)


if __name__ == "__main__":
    main()
