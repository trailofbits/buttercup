import argparse
from buttercup.fuzzing_infra.runner import Runner, Conf, FuzzConfiguration
import time
import os
from buttercup.common.datastructures.msg_pb2 import WeightedHarness, Crash
from buttercup.common.maps import HarnessWeights, BuildMap, BUILD_TYPES
from buttercup.common.queues import QueueFactory, QueueNames, GroupNames
from buttercup.common import utils
from buttercup.common.corpus import Corpus, CrashDir
from buttercup.fuzzing_infra.stack_parsing import CrashSet
import random
import tempfile
from buttercup.common.logger import setup_logging
from redis import Redis
from clusterfuzz.fuzz import engine

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
    q = HarnessWeights(Redis.from_url(args.redis_url))
    builds = BuildMap(Redis.from_url(args.redis_url))
    output_q = QueueFactory(Redis.from_url(args.redis_url)).create(QueueNames.CRASH, GroupNames.ORCHESTRATOR)
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
                logger.info(f"Running fuzzer for {chc.harness_name} | {chc.package_name} | {chc.task_id}")

                build = builds.get_build(chc.task_id, BUILD_TYPES.FUZZER)

                logger.info(f"Build dir: {build.output_ossfuzz_path}")

                if build is None:
                    logger.error(f"No fuzzer build found for {chc.task_id}")
                    continue

                build_dir = os.path.join(build.output_ossfuzz_path, "build/out/", build.package_name)
                corp = Corpus(args.wdir, chc.task_id, chc.harness_name)

                copied_build_dir = os.path.join(td, os.path.basename(build_dir))
                copied_corp_dir = os.path.join(copied_build_dir, corp.basename())
                utils.copyanything(build_dir, copied_build_dir)
                utils.copyanything(corp.path, copied_corp_dir)

                fuzz_conf = FuzzConfiguration(
                    copied_corp_dir,
                    os.path.join(copied_build_dir, chc.harness_name),
                    build.engine,
                    build.sanitizer,
                )
                logger.info(f"Starting fuzzer {build.engine} | {build.sanitizer} | {chc.harness_name}")
                result = runner.run_fuzzer(fuzz_conf)
                crash_set = CrashSet(Redis.from_url(args.redis_url))
                crash_dir = CrashDir(args.wdir, chc.task_id, chc.harness_name)
                for crash_ in result.crashes:
                    crash: engine.Crash = crash_
                    dst = crash_dir.copy_file(crash.input_path)
                    logger.info(f"Found crash {dst}")
                    if crash_set.add(
                        chc.package_name,
                        chc.harness_name,
                        chc.task_id,
                        crash.stacktrace,
                    ):
                        logger.info(f"Crash {crash.stacktrace} already in set")
                        continue
                    crash = Crash(
                        target=build,
                        harness_name=chc.harness_name,
                        crash_input_path=dst,
                        stacktrace=crash.stacktrace,
                    )
                    output_q.push(crash)

                corp.copy_corpus(copied_corp_dir)

                logger.info(f"Fuzzer finished for {build.engine} | {build.sanitizer} | {chc.harness_name}")

        logger.info(f"Sleeping for {seconds_sleep} seconds")
        time.sleep(seconds_sleep)


if __name__ == "__main__":
    main()
