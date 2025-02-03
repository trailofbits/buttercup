from buttercup.common.queues import BuildConfiguration, QueueNames, GroupNames
from buttercup.common.oss_fuzz_tool import OSSFuzzTool, Conf
from redis import Redis
import argparse
import tempfile
from pathlib import Path
from buttercup.common.queues import RQItem, QueueFactory
from buttercup.common.datastructures.msg_pb2 import BuildRequest, BuildOutput
from buttercup.common.logger import setup_logging
from buttercup.common.challenge_task import ChallengeTask
import shutil
import time
import uuid
import os

logger = setup_logging(__name__)


def main():
    prsr = argparse.ArgumentParser("Builder bot")
    prsr.add_argument("--wdir", default="/tmp/builder-bot")
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
    queue = queue_factory.create(QueueNames.BUILD, GroupNames.BUILDER_BOT)
    output_q = queue_factory.create(QueueNames.BUILD_OUTPUT)

    seconds = float(args.timer) // 1000.0
    while True:
        rqit: RQItem[BuildRequest] = queue.pop()
        if rqit is not None:
            msg = rqit.deserialized
            logger.info(f"Received build request for {msg.package_name}")
            task_dir = os.path.dirname(os.path.dirname(msg.source_path))
            if args.allow_caching:
                origin_task = ChallengeTask(task_dir, msg.package_name, python_path=args.python, local_task_dir=task_dir, logger=logger)
            else:
                origin_task = ChallengeTask(task_dir, msg.package_name, python_path=args.python, logger=logger)

            with origin_task.get_rw_copy(work_dir=args.wdir, delete=False) as task:
                res = task.build_fuzzers(engine=msg.engine, sanitizer=msg.sanitizer)
                if not res.success:
                    logger.error(f"Could not build fuzzer {msg.package_name}")
                    task.clean_task_dir()
                    continue

                logger.info(f"Pushing build output for {msg.package_name}")
                output_q.push(
                    BuildOutput(
                        package_name=msg.package_name,
                        engine=msg.engine,
                        sanitizer=msg.sanitizer,
                        output_ossfuzz_path=str(task.get_oss_fuzz_path()),
                        source_path=str(task.get_source_path()),
                        task_id=msg.task_id,
                        build_type=msg.build_type,
                    )
                )
                logger.info(f"Acked build request for {msg.package_name}")
                queue.ack_item(rqit.item_id)

        logger.info(f"Sleeping {seconds} seconds")
        time.sleep(seconds)


if __name__ == "__main__":
    main()
