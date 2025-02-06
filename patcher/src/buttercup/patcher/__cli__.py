from buttercup.patcher.config import Settings, ServeCommand, ProcessCommand
from buttercup.patcher.patcher import Patcher
from pydantic_settings import get_subcommand
from buttercup.common.logger import setup_package_logger
from buttercup.common.datastructures.msg_pb2 import ConfirmedVulnerability, Crash, BuildOutput
import logging
from redis import Redis

logger = logging.getLogger(__name__)


def main():
    settings = Settings()
    command = get_subcommand(settings)
    setup_package_logger(__name__, settings.log_level)

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
        task_vulnerability = ConfirmedVulnerability(
            crash=Crash(
                target=BuildOutput(
                    package_name=command.package_name,
                    engine=command.engine,
                    sanitizer=command.sanitizer,
                    output_ossfuzz_path=command.oss_fuzz_path,
                    source_path=command.source_path,
                    task_id=command.task_id,
                    build_type=command.build_type,
                ),
                harness_name=command.harness_name,
                crash_input_path=command.crash_input_path,
            ),
            vuln_id=command.vulnerability_id,
        )
        patcher = Patcher(
            task_storage_dir=settings.task_storage_dir,
            mock_mode=settings.mock_mode,
        )
        patch = patcher.process_vulnerability(task_vulnerability)
        if patch is not None:
            print(patch.patch)


if __name__ == "__main__":
    main()
