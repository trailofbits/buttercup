"""The `seed-gen` entrypoint."""

import argparse
import os
import random
import tempfile
import time
from pathlib import Path

from redis import Redis

from buttercup.common import utils
from buttercup.common.datastructures.msg_pb2 import WeightedTarget
from buttercup.common.logger import setup_logging
from buttercup.common.maps import FuzzerMap
from buttercup.seed_gen.tasks import Task, do_seed_init, do_seed_explore, do_vuln_discovery

logger = setup_logging(__name__, os.getenv("LOG_LEVEL", "INFO").upper())


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
    parser_server.add_argument(
        "--local_crs_scratch",
        required=False,
        type=Path,
        help="Local path to the /crs_scratch volume directory (for running seed-gen locally)",
    )
    parser_task = subparsers.add_parser("task", help="Do a task")
    parser_task.add_argument(
        "task_name", choices=Task, help="Task name", metavar=", ".join(task.value for task in Task)
    )
    parser_task.add_argument("--out-dir", required=True, type=Path, help="Output directory")
    args = parser.parse_args()
    if args.command == "server":
        command_server(args)
    elif args.command == "task":
        command_task(args)


def command_server(args: argparse.Namespace) -> None:
    """Seed-gen worker server"""
    os.makedirs(args.wdir, exist_ok=True)
    q = FuzzerMap(Redis.from_url(args.redis_url))
    while True:
        # TODO: use different weights than fuzzer
        weighted_items: list[WeightedTarget] = q.list_targets()
        logger.info(f"Received {len(weighted_items)} weighted targets")

        if len(weighted_items) > 0:
            with tempfile.TemporaryDirectory(dir=args.wdir) as td:
                chc = random.choices(
                    [it for it in weighted_items],
                    weights=[it.weight for it in weighted_items],
                    k=1,
                )[0]
                logger.info(
                    "Starting run on challenge %s at path %s",
                    chc.target.package_name,
                    chc.target.output_ossfuzz_path,
                )
                target_dir = Path(chc.target.output_ossfuzz_path)
                if args.local_crs_scratch:
                    target_dir = args.local_crs_scratch / target_dir.relative_to("/crs_scratch")
                    logger.info("Using local dir in local crs_scratch: %s", target_dir)
                dest_dir = Path(td) / target_dir.name
                utils.copyanything(target_dir, dest_dir)
                logger.info("Copied target to %s", dest_dir)
        logger.info("Sleeping for %s seconds", args.sleep)
        time.sleep(args.sleep)


def command_task(args: argparse.Namespace) -> None:
    """Run single task"""
    task_name = args.task_name
    out_dir = args.out_dir
    out_dir.mkdir(parents=True)
    seeds = []
    if task_name == Task.SEED_INIT:
        seeds = do_seed_init()
    elif task_name == Task.SEED_EXPLORE:
        seeds = do_seed_explore()
    elif task_name == Task.VULN_DISCOVERY:
        seeds = do_vuln_discovery()
    for i, seed in enumerate(seeds):
        with open(out_dir / f"seed-{i}.bin", "wb") as f:
            f.write(seed)
