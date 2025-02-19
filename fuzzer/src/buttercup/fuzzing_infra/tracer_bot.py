from buttercup.fuzzing_infra.settings import TracerSettings
from buttercup.fuzzing_infra.tracer_runner import TracerRunner
from buttercup.common.logger import setup_package_logger
import os
import logging
from redis import Redis
import time
from buttercup.common.queues import QueueFactory, QueueNames, GroupNames
from buttercup.common.datastructures.msg_pb2 import TracedCrash
from pathlib import Path
from buttercup.common import stack_parsing

logger = logging.getLogger(__name__)


class TracerBot:
    def __init__(self, redis: Redis, seconds_sleep: int, wdir: str, python: str):
        self.redis = redis
        self.seconds_sleep = seconds_sleep
        self.wdir = wdir
        self.python = python

        queue_factory = QueueFactory(redis)
        self.queue = queue_factory.create(QueueNames.CRASH, GroupNames.TRACER_BOT)
        self.output_q = queue_factory.create(QueueNames.TRACED_VULNERABILITIES)

    def run(self):
        while True:
            item = self.queue.pop()
            if item is not None:
                runner = TracerRunner(item.deserialized.target.task_id, self.wdir, self.redis)
                tinfo = runner.run(item.deserialized.harness_name, Path(item.deserialized.crash_input_path))
                if tinfo is None:
                    continue
                else:
                    if tinfo.is_valid:
                        prsed = stack_parsing.parse_stacktrace(tinfo.stacktrace)
                        output = prsed.crash_stacktrace
                        ntrace = output if output is not None and len(output) > 0 else tinfo.stacktrace
                        self.output_q.push(
                            TracedCrash(
                                crash=item.deserialized,
                                tracer_stacktrace=ntrace,
                            )
                        )
                    self.queue.ack_item(item.item_id)
            time.sleep(self.seconds_sleep)


def main():
    args = TracerSettings()
    setup_package_logger(__name__, "DEBUG")

    os.makedirs(args.wdir, exist_ok=True)
    logger.info(f"Starting tracer-bot (wdir: {args.wdir})")

    seconds_sleep = args.timer // 1000
    tracer_bot = TracerBot(Redis.from_url(args.redis_url), seconds_sleep, args.wdir, args.python)
    tracer_bot.run()


if __name__ == "__main__":
    main()
