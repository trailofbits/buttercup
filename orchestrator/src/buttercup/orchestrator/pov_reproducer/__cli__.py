import logging

from buttercup.common.logger import setup_package_logger
from redis import Redis

from buttercup.orchestrator.pov_reproducer.config import Settings
from buttercup.orchestrator.pov_reproducer.pov_reproducer import POVReproducer

logger = logging.getLogger(__name__)


def main() -> None:
    settings = Settings()  # type: ignore[missing-argument]
    setup_package_logger("pov-reproducer", __name__, settings.log_level)
    logger.info(f"Starting POV Reproducer with settings: {settings}")

    redis = Redis.from_url(settings.redis_url, decode_responses=False)
    service = POVReproducer(redis, settings.sleep_time, settings.max_retries)
    service.serve()


if __name__ == "__main__":
    main()
