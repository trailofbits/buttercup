from buttercup.common.queues import QueueNames, GroupNames
from redis import Redis
from buttercup.common.queues import QueueFactory
from buttercup.common.datastructures.msg_pb2 import BuildType, BuildOutput
from buttercup.common.logger import setup_package_logger
import logging
from buttercup.common.utils import serve_loop
from buttercup.common.challenge_task import ChallengeTask
from pathlib import Path
from buttercup.fuzzing_infra.settings import BuilderBotSettings
import buttercup.common.node_local as node_local
from buttercup.common.telemetry import init_telemetry
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode
from buttercup.common.telemetry import set_crs_attributes, CRSActionCategory

logger = logging.getLogger(__name__)


def main():
    args = BuilderBotSettings()

    setup_package_logger("builder-bot", __name__, args.log_level)
    init_telemetry("builder-bot")

    logger.info(f"Starting builder bot ({args.wdir})")
    redis = Redis.from_url(args.redis_url)

    queue_factory = QueueFactory(redis)
    queue = queue_factory.create(QueueNames.BUILD, GroupNames.BUILDER_BOT)
    output_q = queue_factory.create(QueueNames.BUILD_OUTPUT)

    seconds = float(args.timer) // 1000.0

    def serve_item() -> bool:
        rqit = queue.pop()
        if rqit is None:
            return False

        msg = rqit.deserialized
        logger.info(
            f"Received build request for {msg.task_id} | {msg.engine} | {msg.sanitizer} | {BuildType.Name(msg.build_type)} | diff {msg.apply_diff}"
        )
        task_dir = Path(msg.task_dir)
        if args.allow_caching:
            origin_task = ChallengeTask(
                task_dir,
                python_path=args.python,
                local_task_dir=task_dir,
            )
        else:
            origin_task = ChallengeTask(
                task_dir,
                python_path=args.python,
            )

        with origin_task.get_rw_copy(work_dir=args.wdir) as task:
            if msg.apply_diff:
                logger.info(
                    f"Applying diff for {msg.task_id} | {msg.engine} | {msg.sanitizer} | {BuildType.Name(msg.build_type)} | diff {msg.apply_diff}"
                )
                res = task.apply_patch_diff()
                if not res:
                    logger.info(
                        f"No diffs for {msg.task_id} | {msg.engine} | {msg.sanitizer} | {BuildType.Name(msg.build_type)} | diff {msg.apply_diff}"
                    )
            # log telemetry
            tracer = trace.get_tracer(__name__)
            with tracer.start_as_current_span("build_fuzzers_with_cache") as span:
                set_crs_attributes(
                    span,
                    crs_action_category=CRSActionCategory.BUILDING,
                    crs_action_name="build_fuzzers_with_cache",
                    task_metadata=dict(origin_task.task_meta.metadata),
                )
                res = task.build_fuzzers_with_cache(
                    engine=msg.engine, sanitizer=msg.sanitizer, pull_latest_base_image=args.allow_pull
                )

                if not res.success:
                    logger.error(
                        f"Could not build fuzzer {msg.task_id} | {msg.engine} | {msg.sanitizer} | {BuildType.Name(msg.build_type)} | diff {msg.apply_diff}"
                    )
                    span.set_status(Status(StatusCode.ERROR))
                    return True

                span.set_status(Status(StatusCode.OK))

            task.commit()
            logger.info(
                f"Pushing build output for {msg.task_id} | {msg.engine} | {msg.sanitizer} | {BuildType.Name(msg.build_type)} | diff {msg.apply_diff}"
            )
            node_local.dir_to_remote_archive(task.task_dir)
            output_q.push(
                BuildOutput(
                    engine=msg.engine,
                    sanitizer=msg.sanitizer,
                    task_dir=str(task.task_dir),
                    task_id=msg.task_id,
                    build_type=msg.build_type,
                    apply_diff=msg.apply_diff,
                )
            )
            logger.info(
                f"Acked build request for {msg.task_id} | {msg.engine} | {msg.sanitizer} | {BuildType.Name(msg.build_type)} | diff {msg.apply_diff}"
            )
            queue.ack_item(rqit.item_id)
            return True

    serve_loop(serve_item, seconds)


if __name__ == "__main__":
    main()
