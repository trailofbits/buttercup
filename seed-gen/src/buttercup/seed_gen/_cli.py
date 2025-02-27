"""The `seed-gen` entrypoint."""

import argparse
import os
from pathlib import Path

from redis import Redis

from buttercup.common.logger import setup_package_logger
from buttercup.seed_gen.seed_gen_bot import SeedGenBot


def command_server(args: argparse.Namespace) -> None:
    """Seed-gen worker server"""
    os.makedirs(args.wdir, exist_ok=True)
    redis = Redis.from_url(args.redis_url)
    seed_gen_bot = SeedGenBot(redis, args.sleep, args.wdir, args.python)
    seed_gen_bot.run()


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")
    parser_server = subparsers.add_parser("server", help="Run seed-gen server")
    parser_server.add_argument(
        "--redis_url", required=False, help="Redis URL", default="redis://127.0.0.1:6379"
    )
    parser_server.add_argument("--wdir", required=True, help="Working directory")
    parser_server.add_argument(
        "--sleep", required=False, default=1, type=int, help="Sleep between runs (seconds)"
    )
    parser_server.add_argument("--python", required=True, type=Path, help="Python path")
    args = parser.parse_args()
    setup_package_logger(__name__, os.getenv("LOG_LEVEL", "INFO").upper())
    if args.command == "server":
        command_server(args)
