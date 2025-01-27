import argparse
import distutils.dir_util
from buttercup.fuzzing_infra.runner import Runner, Conf, FuzzConfiguration
import time
import os
from buttercup.common.datastructures.fuzzer_msg_pb2 import WeightedTarget
from buttercup.common.maps import FuzzerMap
from buttercup.common.constants import CORPUS_DIR_NAME
from buttercup.common import utils
import random
import tempfile
import distutils
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

    runner = Runner(Conf(args.timeout))
    seconds_sleep = args.timer // 1000
    q = FuzzerMap(Redis.from_url(args.redis_url))
    while True:
        weighted_items: list[WeightedTarget] = q.list_targets()
        logger.info(f"Received {len(weighted_items)} weighted targets")

        if len(weighted_items) > 0:
            with tempfile.TemporaryDirectory(dir=args.wdir) as td:
                print(type(weighted_items[0]))
                chc = random.choices(
                    [it for it in weighted_items],
                    weights=[it.weight for it in weighted_items],
                    k=1,
                )[0]
                logger.info(f"Running fuzzer for {chc.target.engine} | {chc.target.sanitizer} | {chc.harness_path}")

                build_dir = os.path.dirname(chc.harness_path)
                corpdir = os.path.join(build_dir, CORPUS_DIR_NAME)
                os.makedirs(corpdir, exist_ok=True)
                utils.copyanything(build_dir, os.path.join(td, os.path.basename(build_dir)))
                copied_build_dir = os.path.join(td, os.path.basename(build_dir))
                copied_corp_dir = os.path.join(copied_build_dir, CORPUS_DIR_NAME)
                tgtbuild = chc.target
                fuzz_conf = FuzzConfiguration(
                    copied_corp_dir,
                    os.path.join(copied_build_dir, os.path.basename(chc.harness_path)),
                    tgtbuild.engine,
                    tgtbuild.sanitizer,
                )
                logger.info(f"Starting fuzzer {chc.target.engine} | {chc.target.sanitizer} | {chc.harness_path}")
                runner.run_fuzzer(fuzz_conf)
                distutils.dir_util.copy_tree(copied_corp_dir, corpdir)
                logger.info(f"Fuzzer finished for {chc.target.engine} | {chc.target.sanitizer} | {chc.harness_path}")

        logger.info(f"Sleeping for {seconds_sleep} seconds")
        time.sleep(seconds_sleep)


if __name__ == "__main__":
    main()
