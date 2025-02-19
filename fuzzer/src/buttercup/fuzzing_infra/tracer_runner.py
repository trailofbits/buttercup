from buttercup.common.maps import BuildMap
from buttercup.common.challenge_task import ChallengeTask
from buttercup.common.maps import BUILD_TYPES
from pathlib import Path
from dataclasses import dataclass
import logging
from redis import Redis

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

    def does_crash(self, local_task: ChallengeTask, harness_name: str, crash_path: Path) -> bool:
        res = local_task.reproduce_pov(harness_name, crash_path)
        return res.did_crash()

    def run(self, harness_name: str, crash_path: Path) -> TracerInfo | None:
        builds = BuildMap(self.redis)
        build_output_with_diff = builds.get_build(self.tsk_id, BUILD_TYPES.TRACER)
        if build_output_with_diff is None:
            logging.warning("No tracer build output found for task %s", self.tsk_id)
            return None

        diff_task = ChallengeTask(
            read_only_task_dir=build_output_with_diff.task_dir, project_name=build_output_with_diff.package_name
        )
        is_diff_mode = len(diff_task.get_diffs()) > 0

        with diff_task.get_rw_copy(work_dir=self.wdir) as local_diff_task:
            info_with_diff = local_diff_task.reproduce_pov(harness_name, crash_path)

        if not is_diff_mode:
            if info_with_diff.did_crash():
                return TracerInfo(is_valid=True, stacktrace=info_with_diff.stacktrace())
            else:
                return TracerInfo(is_valid=False, stacktrace=None)

        build_output_no_diffs = builds.get_build(self.tsk_id, BUILD_TYPES.TRACER_NO_DIFF)
        if build_output_no_diffs is None:
            logging.warning("No tracer no diff build output found for task %s", self.tsk_id)
            return None

        no_diff_task = ChallengeTask(
            read_only_task_dir=build_output_no_diffs.task_dir, project_name=build_output_no_diffs.package_name
        )

        with no_diff_task.get_rw_copy(work_dir=self.wdir) as local_no_diff_task:
            info_without_diff = local_no_diff_task.reproduce_pov(harness_name, crash_path)

        if info_with_diff.did_crash() and not info_without_diff.did_crash():
            return TracerInfo(is_valid=True, stacktrace=info_with_diff.stacktrace())
        else:
            return TracerInfo(is_valid=False, stacktrace=None)
