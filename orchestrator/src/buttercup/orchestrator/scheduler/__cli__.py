from buttercup.orchestrator.scheduler.config import Settings, ServeCommand, ProcessCommand
from buttercup.orchestrator.scheduler.scheduler import Scheduler
from buttercup.orchestrator.logger import setup_logging
from pydantic_settings import get_subcommand
from redis import Redis


def main():
    settings = Settings()
    setup_logging(__name__, settings.log_level)
    command = get_subcommand(settings)
    if isinstance(command, ServeCommand):
        redis = Redis.from_url(command.redis_url, decode_responses=False)
        scheduler = Scheduler(command.download_dir, command.sleep_time, redis, mock_mode=command.mock_mode)
        scheduler.serve()
    elif isinstance(command, ProcessCommand):
        pass


if __name__ == "__main__":
    main()
