from buttercup.fuzzing_infra.builder.builder import (
    OSSFuzzTool,
    Conf,
    BuildConfiguration,
)
from redis import Redis
from buttercup.common.queues import RQItem, QueueFactory
from buttercup.common.datastructures.fuzzer_msg_pb2 import BuildRequest, BuildOutput
from buttercup.common.logger import setup_logging
import shutil
import time
import uuid
import os
from buttercup.fuzzing_infra.builder.config import Settings


def main():
    settings = Settings()
    logger = setup_logging(__name__, settings.log_level)

    logger.info(f"Starting builder bot ({settings.wdir})")
    redis = Redis.from_url(settings.redis_url)
    queue_factory = QueueFactory(redis)
    queue = queue_factory.create_build_queue()
    output_q = queue_factory.create_build_output_queue()

    seconds = float(settings.timer) // 1000.0

    while True:
        rqit: RQItem = queue.pop()
        if rqit is not None:
            msg: BuildRequest = rqit.deserialized
            logger.info(f"Received build request for {msg.package_name}")
            conf = BuildConfiguration(msg.package_name, msg.engine, msg.sanitizer)
            ossfuzz_dir = msg.ossfuzz
            dirid = str(uuid.uuid4())

            target = ossfuzz_dir
            if not settings.allow_caching:
                wdirstr = settings.wdir
                if not isinstance(wdirstr, str):
                    wdirstr = settings.wdir.name

                target = os.path.join(wdirstr, f"ossfuzz-snapshot-{dirid}")
                logger.info(f"Copying {ossfuzz_dir} to {target}")
                shutil.copytree(ossfuzz_dir, target)

            logger.info(f"Building oss-fuzz project {msg.package_name}")
            build_tool = OSSFuzzTool(Conf(target, settings.python))
            if not build_tool.build_fuzzer_with_cache(conf):
                logger.error(f"Could not build fuzzer {msg.package_name}")

            logger.info(f"Pushing build output for {msg.package_name}")
            output_q.push(
                BuildOutput(
                    package_name=msg.package_name,
                    engine=msg.engine,
                    sanitizer=msg.sanitizer,
                    output_ossfuzz_path=target,
                )
            )
            logger.info(f"Acked build request for {msg.package_name}")
            queue.ack_item(rqit.item_id)

        logger.info(f"Sleeping {seconds} seconds")
        time.sleep(seconds)


if __name__ == "__main__":
    main()
