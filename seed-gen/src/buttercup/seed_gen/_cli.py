"""The `seed-gen` entrypoint."""

import argparse
import os
import random
import tempfile
import time
from pathlib import Path

from redis import Redis

from buttercup.common.corpus import Corpus
from buttercup.common.datastructures.msg_pb2 import WeightedTarget
from buttercup.common.logger import setup_logging
from buttercup.common.maps import FuzzerMap
from buttercup.seed_gen.tasks import Task, do_seed_explore, do_seed_init, do_vuln_discovery

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
            chc = random.choices(
                [it for it in weighted_items],
                weights=[it.weight for it in weighted_items],
                k=1,
            )[0]

            output_ossfuzz_path = Path(chc.target.output_ossfuzz_path)
            harness_path = Path(chc.harness_path)
            source_path = Path(chc.target.source_path)  # noqa: F841
            package_name = chc.target.package_name

            logger.info(
                "Starting run on challenge %s at path %s",
                package_name,
                output_ossfuzz_path,
            )

            corp = Corpus(harness_path)
            challenge = package_name
            with tempfile.TemporaryDirectory(dir=args.wdir) as out_dir_str:
                out_dir = Path(out_dir_str)
                do_seed_init(challenge, out_dir)
                logger.info("Copying corpus to %s", out_dir)
                num_files = sum(1 for _ in out_dir.iterdir())
                logger.info("Copying %d files to corpus %s", num_files, corp.corpus_dir)
                corp.copy_corpus(out_dir)

        logger.info("Sleeping for %s seconds", args.sleep)
        time.sleep(args.sleep)


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
