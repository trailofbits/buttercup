from buttercup.common.maps import BuildMap
from buttercup.common.challenge_task import ChallengeTask, ReproduceResult
from buttercup.common.datastructures.msg_pb2 import BuildType
from pathlib import Path
from dataclasses import dataclass
import logging
from redis import Redis
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode
from buttercup.common.telemetry import set_crs_attributes, CRSActionCategory

logger = logging.getLogger(__name__)


@dataclass
class TracerInfo:
    is_valid: bool
    stacktrace: str | None


class TracerRunner:
    def __init__(self, tsk_id: str, wdir: str, redis: Redis) -> None:
        self.tsk_id = tsk_id
        self.wdir = wdir
        self.redis = redis

    def _create_tracer_info(self, info: ReproduceResult) -> TracerInfo:
        crashed = info.did_crash()
        return TracerInfo(
            is_valid=crashed,
            stacktrace=info.stacktrace() if crashed else None,
        )

    def run(self, harness_name: str, crash_path: Path, sanitizer: str) -> TracerInfo | None:
        builds = BuildMap(self.redis)
        build_output_with_diff = builds.get_build_from_san(self.tsk_id, BuildType.FUZZER, sanitizer)
        if build_output_with_diff is None:
            logger.warning("No tracer build output found for task %s", self.tsk_id)
            return None

        diff_task = ChallengeTask(read_only_task_dir=build_output_with_diff.task_dir)
        is_diff_mode = len(diff_task.get_diffs()) > 0
        build_output_no_diffs = builds.get_build_from_san(self.tsk_id, BuildType.TRACER_NO_DIFF, sanitizer)
        if is_diff_mode and build_output_no_diffs is None:
            logger.warning("No tracer no diff build output found for task %s", self.tsk_id)
            return None

        logger.info("Checking if task %s crashed", self.tsk_id)
        with diff_task.get_rw_copy(work_dir=self.wdir) as local_diff_task:
            # log telemetry
            tracer = trace.get_tracer(__name__)
            with tracer.start_as_current_span("reproduce_pov") as span:
                set_crs_attributes(
                    span,
                    crs_action_category=CRSActionCategory.DYNAMIC_ANALYSIS,
                    crs_action_name="reproduce_pov",
                    task_metadata=dict(diff_task.task_meta.metadata),
                    extra_attributes={
                        "crs.action.target.sanitizer": sanitizer,
                        "crs.action.target.harness": harness_name,
                    },
                )
                info_with_diff = local_diff_task.reproduce_pov(harness_name, crash_path)
                span.set_status(Status(StatusCode.OK))

        if not info_with_diff.did_run():
            logger.warning("Could not reproduce task %s in diff mode", self.tsk_id)
            logger.debug(
                "Task %s in diff mode, stdout: %s, stderr: %s",
                self.tsk_id,
                info_with_diff.command_result.output,
                info_with_diff.command_result.error,
            )
            return None

        if not info_with_diff.did_crash():
            logger.warning("Task %s did not generate a valid crash", self.tsk_id)
            return TracerInfo(is_valid=False, stacktrace=None)

        if not is_diff_mode:
            return self._create_tracer_info(info_with_diff)

        logger.info("Checking if task %s crashed without diffs", self.tsk_id)
        no_diff_task = ChallengeTask(read_only_task_dir=build_output_no_diffs.task_dir)

        with no_diff_task.get_rw_copy(work_dir=self.wdir) as local_no_diff_task:
            # log telemetry
            tracer = trace.get_tracer(__name__)
            with tracer.start_as_current_span("reproduce_pov_no_diff") as span:
                set_crs_attributes(
                    span,
                    crs_action_category=CRSActionCategory.DYNAMIC_ANALYSIS,
                    crs_action_name="reproduce_pov_no_diff",
                    task_metadata=dict(no_diff_task.task_meta.metadata),
                    extra_attributes={
                        "crs.action.target.sanitizer": sanitizer,
                        "crs.action.target.harness": harness_name,
                    },
                )
                info_without_diff = local_no_diff_task.reproduce_pov(harness_name, crash_path)
                span.set_status(Status(StatusCode.OK))

        if not info_without_diff.did_run():
            logger.warning("Could not reproduce task %s in no diff mode", self.tsk_id)
            logger.debug(
                "Task %s in no diff mode, stdout: %s, stderr: %s",
                self.tsk_id,
                info_without_diff.command_result.output,
                info_without_diff.command_result.error,
            )
            return None

        if info_with_diff.did_crash() and not info_without_diff.did_crash():
            logger.info("Task %s crashed in diff mode but not in no diff mode", self.tsk_id)
            return self._create_tracer_info(info_with_diff)

        logger.info("Task %s crashed both before and after the diff", self.tsk_id)
        return TracerInfo(is_valid=False, stacktrace=None)
