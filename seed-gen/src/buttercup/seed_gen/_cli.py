"""The `seed-gen` entrypoint."""

import os

from redis import Redis

from buttercup.common.logger import setup_package_logger
from buttercup.common.telemetry import init_telemetry
from buttercup.seed_gen.config import Settings
from buttercup.seed_gen.seed_gen_bot import SeedGenBot


def command_server(settings: Settings) -> None:
    """Seed-gen worker server"""
    os.makedirs(settings.server.wdir, exist_ok=True)
    if settings.server.corpus_root:
        os.makedirs(settings.server.corpus_root, exist_ok=True)
    init_telemetry("seed-gen")
    redis = Redis.from_url(settings.server.redis_url)
    seed_gen_bot = SeedGenBot(
        redis,
        settings.server.sleep_time,
        settings.server.wdir,
        corpus_root=settings.server.corpus_root,
        crash_dir_count_limit=settings.server.crash_dir_count_limit,
    )
    seed_gen_bot.run()


def main() -> None:
    settings = Settings()
    setup_package_logger("seed-gen", __name__, settings.log_level.upper())
    command_server(settings)
