import argparse
from buttercup.fuzzing_infra.runner import Runner, Conf, FuzzConfiguration
import time
import os
from buttercup.common.datastructures.msg_pb2 import WeightedHarness
from buttercup.common.maps import HarnessWeights, BuildMap, BUILD_TYPES
from buttercup.common.queues import QueueFactory
from buttercup.common.corpus import Corpus
import random
import tempfile
from buttercup.common.logger import setup_logging
from redis import Redis
logger = setup_logging(__name__)


def main():
    prsr = argparse.ArgumentParser("fuzz bot")
    prsr.add_argument("--timeout", required=True, type=int)
    prsr.add_argument("--timer", default=1000, type=int)
    prsr.add_argument("--redis_url", default="redis://127.0.0.1:6379")
    prsr.add_argument("--wdir", required=True)

    args = prsr.parse_args()

    os.makedirs(args.wdir, exist_ok=True)
    logger.info(f"Starting fuzzer (wdir: {args.wdir})")

    seconds_sleep = args.timer // 1000
    q = HarnessWeights(Redis.from_url(args.redis_url))
    builds = BuildMap(Redis.from_url(args.redis_url))
    while True:
        weighted_items: list[WeightedHarness] = q.list_harnesses()
        logger.info(f"Received {len(weighted_items)} weighted targets")

        if len(weighted_items) > 0:
            with tempfile.TemporaryDirectory(dir=args.wdir) as td:
                print(type(weighted_items[0]))
                chc = random.choices(
                    [it for it in weighted_items],
                    weights=[it.weight for it in weighted_items],
                    k=1,
                )[0]
                logger.info(f"Running coverage collection for {chc.harness_name} | {chc.package_name} | {chc.task_id}")

        logger.info(f"Sleeping for {seconds_sleep} seconds")
        time.sleep(seconds_sleep)


if __name__ == "__main__":
    main()
