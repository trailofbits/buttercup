from buttercup.common.queues import Queue, SerializationDeserializationQueue, ReliableQueue, NormalQueue, RQItem, QueueNames, QueueFactory
import argparse
from redis import Redis
from buttercup.common.datastructures.fuzzer_msg_pb2 import BuildOutput, WeightedTarget
import time
from clusterfuzz.fuzz import get_fuzz_targets
import os 
import logging
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
DEFAULT_WEIGHT = 1.0

def loop(output_queue: ReliableQueue, target_list: Queue, sleep_time_seconds: int):
    while True:
        time.sleep(sleep_time_seconds)
        output: RQItem = output_queue.pop()
        if output is not None:
            deser_output: BuildOutput = output.deserialized
            build_dir = os.path.join(deser_output.output_ossfuzz_path, "build", "out", deser_output.package_name)
            logger.info(f"Received build of package: {build_dir}")
            print(f"Received build of package: {build_dir}")
            targets = get_fuzz_targets(build_dir)
            for tgt in targets:
                logger.info(f"Adding target: {tgt}")
                print(f"Adding target: {tgt}")
                # TODO(Ian): to make this idempotent this should be hashed rather than a list we can add a target mutliple times.
                target_list.push(WeightedTarget(weight=1.0, target=deser_output, harness_path=tgt))
            output_queue.ack_item(output.item_id)
def main():
    prsr = argparse.ArgumentParser("Fuzzing orchestrator")
    prsr.add_argument("--redis_url", default="redis://127.0.0.1:6379")
    prsr.add_argument("--timer", default=1000, type=int)
    args = prsr.parse_args()
    conn = Redis.from_url(args.redis_url)
    seconds = args.timer//1000
    builder_output = QueueFactory(conn).create_build_output_queue()
    target_list = SerializationDeserializationQueue(NormalQueue(QueueNames.TARGET_LIST, conn), WeightedTarget)
    loop(builder_output, target_list, seconds)

if __name__ == "__main__":
    main()
