from buttercup.fuzzing_infra.builder import OSSFuzzTool, Conf, BuildConfiguration
from redis import Redis
import argparse
import tempfile
from buttercup.common.queues import RQItem, QueueFactory
from buttercup.common.datastructures.fuzzer_msg_pb2 import BuildRequest, BuildOutput
import shutil
import time
import logging
import uuid
import os
logger = logging.getLogger(__name__)


def main():
    prsr = argparse.ArgumentParser("Builder bot")
    prsr.add_argument("--wdir", default=tempfile.TemporaryDirectory())
    prsr.add_argument("--python",default="python")
    prsr.add_argument("--redis_url", default="redis://127.0.0.1:6379")
    prsr.add_argument("--timer", default=1000, type=int)
    prsr.add_argument("--allow-caching", action="store_true", default=False)
    args = prsr.parse_args()

    redis = Redis.from_url(args.redis_url) 

    queue_factory = QueueFactory(redis)
    queue = queue_factory.create_build_queue()
    output_q = queue_factory.create_build_output_queue()

    seconds = float(args.timer) // 1000.0
    while True:
        rqit: RQItem = queue.pop()
        if rqit is not None:
            msg: BuildRequest = rqit.deserialized
            conf = BuildConfiguration(msg.package_name, msg.engine, msg.sanitizer)
            ossfuzz_dir = msg.ossfuzz
            dirid = str(uuid.uuid4())
            
            target = ossfuzz_dir
            if not args.allow_caching:
                wdirstr = args.wdir
                if not isinstance(wdirstr, str):
                    wdirstr = args.wdir.name

                target = os.path.join(wdirstr, f"ossfuzz-snapshot-{dirid}")
                shutil.copytree(ossfuzz_dir, target)
            
            build_tool = OSSFuzzTool(Conf(target, args.python))
            if not build_tool.build_fuzzer_with_cache(conf):
                logging.error(f"Could not build fuzzer {msg.package_name}")

            output_q.push(BuildOutput(package_name=msg.package_name, engine=msg.engine, sanitizer=msg.sanitizer, output_ossfuzz_path=target))
            queue.ack_item(rqit.item_id)
        time.sleep(seconds)


if __name__ == "__main__":
    main()
