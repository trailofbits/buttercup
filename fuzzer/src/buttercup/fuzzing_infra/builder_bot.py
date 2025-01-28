from buttercup.common.queues import BuildConfiguration, QueueNames, GroupNames
from buttercup.common.oss_fuzz_tool import OSSFuzzTool, Conf
from redis import Redis
import argparse
import tempfile
from buttercup.common.queues import RQItem, QueueFactory
from buttercup.common.datastructures.fuzzer_msg_pb2 import BuildRequest, BuildOutput
from buttercup.common.logger import setup_logging
import shutil
import time
import uuid
import os

logger = setup_logging(__name__)


def main():
    prsr = argparse.ArgumentParser("Builder bot")
    prsr.add_argument("--wdir", default=tempfile.TemporaryDirectory())
    prsr.add_argument("--python", default="python")
    prsr.add_argument("--redis_url", default="redis://127.0.0.1:6379")
    prsr.add_argument("--timer", default=1000, type=int)
    prsr.add_argument("--allow-caching", action="store_true", default=False)
    prsr.add_argument("--allow-pull", action="store_true", default=False)
    prsr.add_argument("--base-image-url", default="gcr.io/oss-fuzz")
    args = prsr.parse_args()

    logger.info(f"Starting builder bot ({args.wdir})")
    redis = Redis.from_url(args.redis_url)

    queue_factory = QueueFactory(redis)
    queue = queue_factory.create_queue(QueueNames.BUILD, GroupNames.BUILDER_BOT)
    output_q = queue_factory.create_queue(QueueNames.BUILD_OUTPUT)

    seconds = float(args.timer) // 1000.0
    while True:
        rqit: RQItem = queue.pop()
        if rqit is not None:
            msg: BuildRequest = rqit.deserialized
            logger.info(f"Received build request for {msg.package_name}")
            ossfuzz_dir = msg.ossfuzz
            dirid = str(uuid.uuid4())

            target = ossfuzz_dir
            source_path_output = msg.source_path
            if not args.allow_caching:
                wdirstr = args.wdir
                if not isinstance(wdirstr, str):
                    wdirstr = args.wdir.name

                target = os.path.join(wdirstr, f"ossfuzz-snapshot-{dirid}")
                logger.info(f"Copying {ossfuzz_dir} to {target}")
                shutil.copytree(ossfuzz_dir, target)
                source_snapshot = os.path.join(wdirstr, f"source-snapshot-{dirid}-{msg.package_name}")
                shutil.copytree(msg.source_path, source_snapshot)
                source_path_output = source_snapshot

            conf = BuildConfiguration(msg.package_name, msg.engine, msg.sanitizer, source_path_output)
            logger.info(f"Building oss-fuzz project {msg.package_name}")
            build_tool = OSSFuzzTool(Conf(target, args.python, args.allow_pull, args.base_image_url))
            if not build_tool.build_fuzzer_with_cache(conf):
                logger.error(f"Could not build fuzzer {msg.package_name}")

            logger.info(f"Pushing build output for {msg.package_name}")
            output_q.push(
                BuildOutput(
                    package_name=msg.package_name,
                    engine=msg.engine,
                    sanitizer=msg.sanitizer,
                    output_ossfuzz_path=target,
                    source_path=source_path_output,
                )
            )
            logger.info(f"Acked build request for {msg.package_name}")
            queue.ack_item(rqit.item_id)

        logger.info(f"Sleeping {seconds} seconds")
        time.sleep(seconds)


if __name__ == "__main__":
    main()
