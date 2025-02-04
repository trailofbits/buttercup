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

    raise NotImplementedError


if __name__ == "__main__":
    main()
