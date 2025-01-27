from buttercup.orchestrator.cancellation.cancellation import Cancellation
from buttercup.common.logger import setup_logging
from pydantic_settings import BaseSettings
from redis import Redis


class CancellationSettings(BaseSettings):
    """Settings for the cancellation service."""

    log_level: str = "INFO"
    redis_url: str = "redis://localhost:6379"
    sleep_time: float = 0.1


def main():
    settings = CancellationSettings()
    setup_logging(__name__, settings.log_level)

    redis = Redis.from_url(settings.redis_url, decode_responses=False)
    cancellation = Cancellation(sleep_time=settings.sleep_time, redis=redis)
    cancellation.run()


if __name__ == "__main__":
    main()
