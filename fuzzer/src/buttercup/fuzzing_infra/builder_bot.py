from fuzzing_infra.builder import OSSFuzzTool, Conf, BuildConfiguration
from redis import Redis
import argparse
import tempfile
from common.queues import BUILD_QUEUE_NAME, ReliableQueue, BUILD_OUTPUT_NAME, ORCHESTRATOR_GROUP_NAME, SerializationDeserializationQueue, BUILDER_BOT_GROUP_NAME, RQItem
from common.datastructures.fuzzer_msg_pb2 import BuildRequest, BuildOutput
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

    queue = ReliableQueue(BUILD_QUEUE_NAME,BUILDER_BOT_GROUP_NAME,redis, 108000, BuildRequest)
    output_q = ReliableQueue(BUILD_OUTPUT_NAME, ORCHESTRATOR_GROUP_NAME, redis, 108000, BuildOutput)
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
                target = os.path.join(args.wdir.name, f"ossfuzz-snapshot-{dirid}")
                shutil.copytree(ossfuzz_dir, target)
            
            build_tool = OSSFuzzTool(Conf(target, args.python))
            if not build_tool.build_fuzzer_with_cache(conf):
                logging.error(f"Could not build fuzzer {msg.package_name}")

            output_q.push(BuildOutput(package_name=msg.package_name, engine=msg.engine, sanitizer=msg.sanitizer, output_ossfuzz_path=target))
            queue.ack_item(rqit)
        time.sleep(seconds)


if __name__ == "__main__":
    main()