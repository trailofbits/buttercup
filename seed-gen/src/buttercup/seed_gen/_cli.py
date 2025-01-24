"""The `seed-gen` entrypoint."""

import argparse
import logging
import os
import random
import tempfile
import time

from redis import Redis

from buttercup.common import utils
from buttercup.common.datastructures.fuzzer_msg_pb2 import WeightedTarget
from buttercup.common.queues import (
    NormalQueue,
    QueueNames,
    SerializationDeserializationQueue,
)
from buttercup.seed_gen.logger import logger_configurer

logger_configurer(os.getenv("LOG_LEVEL", "INFO").upper())
logger = logging.getLogger(__name__)


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
    args = parser.parse_args()
    if args.command == "server":
        command_server(args)


def command_server(args: argparse.Namespace) -> None:
    os.makedirs(args.wdir, exist_ok=True)
    conn = Redis.from_url(args.redis_url)
    q = SerializationDeserializationQueue(NormalQueue(QueueNames.TARGET_LIST, conn), WeightedTarget)
    while True:
        # TODO: use different weights than fuzzer
        weighted_items: list[WeightedTarget] = list(iter(q))

        if len(weighted_items) > 0:
            with tempfile.TemporaryDirectory(prefix=args.wdir) as td:
                chc = random.choices(
                    [it for it in weighted_items],
                    weights=[it.weight for it in weighted_items],
                    k=1,
                )[0]
                logger.info(
                    "Starting run on challenge %s harness %s",
                    chc.target.package_name,
                    chc.harness_path,
                )
                build_dir = os.path.dirname(chc.harness_path)
                utils.copyanything(build_dir, os.path.join(td, os.path.basename(build_dir)))
        time.sleep(args.sleep)
