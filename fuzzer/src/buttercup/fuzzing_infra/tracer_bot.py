from buttercup.fuzzing_infra.settings import TracerSettings
from buttercup.fuzzing_infra.tracer_runner import TracerRunner
from buttercup.common.logger import setup_package_logger
import os
import logging
from redis import Redis
from buttercup.common.queues import QueueFactory, QueueNames, GroupNames
from buttercup.common.datastructures.msg_pb2 import TracedCrash
from buttercup.common.task_registry import TaskRegistry
from pathlib import Path
from buttercup.common import stack_parsing
from buttercup.common.utils import serve_loop, setup_periodic_zombie_reaper
import buttercup.common.node_local as node_local
from buttercup.common.telemetry import init_telemetry

logger = logging.getLogger(__name__)


class TracerBot:
    def __init__(self, redis: Redis, seconds_sleep: int, wdir: str, python: str, max_tries: int):
        self.redis = redis
        self.seconds_sleep = seconds_sleep
        self.wdir = wdir
        self.python = python
        self.max_tries = max_tries
        queue_factory = QueueFactory(redis)
        self.queue = queue_factory.create(QueueNames.CRASH, GroupNames.TRACER_BOT)
        self.output_q = queue_factory.create(QueueNames.TRACED_VULNERABILITIES)
        self.registry = TaskRegistry(redis)

    def serve_item(self) -> bool:
        item = self.queue.pop()
        if item is None:
            return False

        logger.info(f"Received tracer request for {item.deserialized.target.task_id}")
        if self.registry.should_stop_processing(item.deserialized.target.task_id):
            logger.info(f"Task {item.deserialized.target.task_id} is cancelled or expired, skipping")
            self.queue.ack_item(item.item_id)
            return True

        if self.queue.times_delivered(item.item_id) > self.max_tries:
            logger.warning(f"Reached max tries for {item.deserialized.target.task_id}")
            self.queue.ack_item(item.item_id)
            return True

        runner = TracerRunner(item.deserialized.target.task_id, self.wdir, self.redis)

        # Ensure the crash input is locally available
        logger.info(f"Making locally available: {item.deserialized.crash_input_path}")
        local_path = node_local.make_locally_available(Path(item.deserialized.crash_input_path))

        tinfo = runner.run(
            item.deserialized.harness_name,
            local_path,
            item.deserialized.target.sanitizer,
        )
        if tinfo is None:
            logger.warning(f"No tracer info found for {item.deserialized.target.task_id}")
            return True

        if tinfo.is_valid:
            logger.info(f"Valid tracer info found for {item.deserialized.target.task_id}")
            prsed = stack_parsing.parse_stacktrace(tinfo.stacktrace)
            output = prsed.crash_stacktrace
            ntrace = output if output is not None and len(output) > 0 else tinfo.stacktrace
            self.output_q.push(
                TracedCrash(
                    crash=item.deserialized,
                    tracer_stacktrace=ntrace,
                )
            )

        logger.info(f"Acknowledging tracer request for {item.deserialized.target.task_id}")
        self.queue.ack_item(item.item_id)
        return True

    def run(self):
        serve_loop(self.serve_item, self.seconds_sleep)


def main():
    args = TracerSettings()

    setup_package_logger("tracer-bot", __name__, "DEBUG", None)
    init_telemetry("tracer-bot")

    setup_periodic_zombie_reaper()

    os.makedirs(args.wdir, exist_ok=True)
    logger.info(f"Starting tracer-bot (wdir: {args.wdir})")

    seconds_sleep = args.timer // 1000
    tracer_bot = TracerBot(Redis.from_url(args.redis_url), seconds_sleep, args.wdir, args.python, args.max_tries)
    tracer_bot.run()


if __name__ == "__main__":
    main()
