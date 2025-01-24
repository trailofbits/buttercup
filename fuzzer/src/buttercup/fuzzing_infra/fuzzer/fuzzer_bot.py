import distutils.dir_util
from buttercup.fuzzing_infra.runner import Runner, Conf, FuzzConfiguration
import time
import os
from buttercup.common.datastructures.fuzzer_msg_pb2 import WeightedTarget
from buttercup.common.queues import (
    NormalQueue,
    SerializationDeserializationQueue,
    QueueNames,
)
from buttercup.common.constants import CORPUS_DIR_NAME
from buttercup.common import utils
from redis import Redis
import random
import tempfile
import distutils
import logging
from buttercup.fuzzing_infra.fuzzer.config import Settings
from buttercup.common.logger import setup_logging

def main():
    settings = Settings()
    logger = setup_logging(__name__, settings.log_level)

    os.makedirs(settings.wdir, exist_ok=True)
    logger.info(f"Starting fuzzer (wdir: {settings.wdir})")

    runner = Runner(Conf(settings.timeout))
    seconds_sleep = settings.timer // 1000
    conn = Redis.from_url(settings.redis_url)
    q = SerializationDeserializationQueue(NormalQueue(QueueNames.TARGET_LIST, conn), WeightedTarget)
    while True:
        weighted_items: list[WeightedTarget] = list(iter(q))
        logger.info(f"Received {len(weighted_items)} weighted targets")

        if len(weighted_items) > 0:
            # td = tempfile.mkdtemp()
            # if True:
            with tempfile.TemporaryDirectory(prefix=str(settings.wdir)) as td:
                print(type(weighted_items[0]))
                chc = random.choices(
                    [it for it in weighted_items],
                    weights=[it.weight for it in weighted_items],
                    k=1,
                )[0]
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
                logger.info(f"Running fuzzer for {tgtbuild.engine} {tgtbuild.sanitizer}")
                runner.run_fuzzer(fuzz_conf)
                distutils.dir_util.copy_tree(copied_corp_dir, corpdir)
                logger.info(f"Fuzzer finished for {tgtbuild.engine} {tgtbuild.sanitizer}")

        logger.info(f"Sleeping for {seconds_sleep} seconds")
        time.sleep(seconds_sleep)


if __name__ == "__main__":
    main()
