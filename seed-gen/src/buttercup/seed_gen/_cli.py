"""The `seed-gen` entrypoint."""

import argparse
import logging
import os
from pathlib import Path

from redis import Redis

from buttercup.common.logger import setup_package_logger
from buttercup.seed_gen.seed_gen_bot import SeedGenBot
from buttercup.seed_gen.tasks import Task, do_seed_explore, do_seed_init, do_vuln_discovery

logger = logging.getLogger(__name__)


def command_server(args: argparse.Namespace) -> None:
    """Seed-gen worker server"""
    os.makedirs(args.wdir, exist_ok=True)
    redis = Redis.from_url(args.redis_url)
    seed_gen_bot = SeedGenBot(redis, args.sleep, args.wdir)
    seed_gen_bot.run()


def command_task(args: argparse.Namespace) -> None:
    """Run single task"""
    task_name = args.task_name
    out_dir = args.out_dir
    out_dir.mkdir(parents=True)
    if task_name == Task.SEED_INIT:
        challenge = "libpng"
        do_seed_init(challenge, out_dir)
    elif task_name == Task.SEED_EXPLORE:
        do_seed_explore()
    elif task_name == Task.VULN_DISCOVERY:
        do_vuln_discovery()


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
    parser_task = subparsers.add_parser("task", help="Do a task")
    parser_task.add_argument(
        "task_name", choices=Task, help="Task name", metavar=", ".join(task.value for task in Task)
    )
    parser_task.add_argument("--out-dir", required=True, type=Path, help="Output directory")
    args = parser.parse_args()
    setup_package_logger(__name__, os.getenv("LOG_LEVEL", "INFO").upper())
    if args.command == "server":
        command_server(args)
    elif args.command == "task":
        command_task(args)
