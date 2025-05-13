from buttercup.common.queues import (
    ReliableQueue,
    RQItem,
    QueueFactory,
    QueueNames,
    GroupNames,
)
from buttercup.common.maps import HarnessWeights, BuildMap

import argparse
from redis import Redis
from buttercup.common.datastructures.msg_pb2 import BuildType, BuildOutput, WeightedHarness
import time
from buttercup.common.clusterfuzz_utils import get_fuzz_targets
import os
from buttercup.common.logger import setup_package_logger

logger = setup_package_logger("fuzzer-orchestrator", __name__)
DEFAULT_WEIGHT = 1.0


def loop(output_queue: ReliableQueue, target_list: HarnessWeights, build_map: BuildMap, sleep_time_seconds: int):
    while True:
        time.sleep(sleep_time_seconds)
        output: RQItem = output_queue.pop()
        if output is not None:
            deser_output: BuildOutput = output.deserialized
            build_dir = os.path.join(
                deser_output.output_ossfuzz_path,
                "build",
                "out",
                deser_output.package_name,
            )
            logger.info(f"Received build of package: {build_dir}")
            print(f"Received build of package: {build_dir}")
            targets = get_fuzz_targets(build_dir)
            build_map.add_build(deser_output)
            if deser_output.build_type == BuildType.FUZZER:
                for tgt in targets:
                    logger.info(f"Adding target: {tgt}")
                    print(f"Adding target: {tgt}")
                target_list.push_harness(
                    WeightedHarness(
                        weight=1.0,
                        harness_name=os.path.basename(tgt),
                        package_name=deser_output.package_name,
                        task_id=deser_output.task_id,
                    )
                )
            output_queue.ack_item(output.item_id)


def main():
    prsr = argparse.ArgumentParser("Fuzzing orchestrator")
    prsr.add_argument("--redis_url", default="redis://127.0.0.1:6379")
    prsr.add_argument("--timer", default=1000, type=int)
    args = prsr.parse_args()
    conn = Redis.from_url(args.redis_url)
    seconds = args.timer // 1000
    builder_output = QueueFactory(conn).create(QueueNames.BUILD_OUTPUT, GroupNames.ORCHESTRATOR)
    target_list = HarnessWeights(conn)
    build_map = BuildMap(conn)
    loop(builder_output, target_list, build_map, seconds)


if __name__ == "__main__":
    main()
