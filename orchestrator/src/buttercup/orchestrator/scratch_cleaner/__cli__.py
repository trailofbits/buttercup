from buttercup.orchestrator.scratch_cleaner.config import Settings
from buttercup.orchestrator.scratch_cleaner.scratch_cleaner import ScratchCleaner
from buttercup.common.logger import setup_package_logger
from redis import Redis
import logging

logger = logging.getLogger(__name__)


def main():
    settings = Settings()
    setup_package_logger("scratch-cleaner", __name__, settings.log_level)
    logger.info(f"Starting Scratch Cleaner with settings: {settings}")

    redis = Redis.from_url(settings.redis_url, decode_responses=False)
    service = ScratchCleaner(
        redis=redis,
        scratch_dir=settings.scratch_dir,
        sleep_time=settings.sleep_time,
        delete_old_tasks_scratch_delta_seconds=settings.delete_old_tasks_scratch_delta_seconds,
    )
    service.serve()


if __name__ == "__main__":
    main()
