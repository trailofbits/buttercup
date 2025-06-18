from __future__ import annotations

from dataclasses import dataclass, field
import logging
from pathlib import Path
from typing import Optional
from buttercup.common.maps import BuildMap
from buttercup.common.challenge_task import ChallengeTask
from buttercup.common.datastructures.msg_pb2 import BuildType, BuildOutput, POVReproduceRequest
from buttercup.common.sets import PoVReproduceStatus
from buttercup.common.task_registry import TaskRegistry
import buttercup.common.node_local as node_local

from redis import Redis
from buttercup.common.utils import serve_loop

logger = logging.getLogger(__name__)


@dataclass
class POVReproducer:
    redis: Redis
    sleep_time: float = 0.1
    max_retries: int = 10

    pov_status: PoVReproduceStatus = field(init=False)
    registry: TaskRegistry = field(init=False)

    def __post_init__(self) -> None:
        self.pov_status = PoVReproduceStatus(self.redis)
        self.registry = TaskRegistry(self.redis)

    def serve_item(self) -> bool:
        entry: Optional[POVReproduceRequest] = self.pov_status.get_one_pending()
        if entry is None:
            return False

        task_id: str = entry.task_id
        internal_patch_id: str = entry.internal_patch_id
        pov_path: str = entry.pov_path
        sanitizer: str = entry.sanitizer
        harness_name: str = entry.harness_name

        if self.registry.should_stop_processing(task_id):
            logger.info("Task %s is cancelled or expired, will not reproduce POV.", task_id)
            was_marked = self.pov_status.mark_expired(entry)
            if not was_marked:
                logger.debug(
                    "Failed to mark POV as expired for task %s - item was not in pending state (another worker might have marked it)",
                    task_id,
                )
            return False

        logger.info(f"Reproducing POV for {task_id} | {harness_name} | {pov_path}")

        builds = BuildMap(self.redis)
        build_output_with_patch: Optional[BuildOutput] = builds.get_build_from_san(
            task_id,
            BuildType.PATCH,
            sanitizer,
            internal_patch_id,
        )
        if build_output_with_patch is None:
            logger.warning(
                "No patched build output found for task %s. Will retry later.",
                task_id,
            )
            return False

        local_path: Path = node_local.make_locally_available(Path(pov_path))

        challenge_task_dir = ChallengeTask(read_only_task_dir=build_output_with_patch.task_dir)
        with challenge_task_dir.get_rw_copy(work_dir=node_local.scratch_path()) as task:
            info = task.reproduce_pov(harness_name, local_path)
            if not info.did_run():
                logger.warning(
                    f"Reproduce did not run for task %s. Will retry later. Output {info}",
                    task_id,
                )
                return False

            logger.debug(
                "stdout: %s, stderr: %s for task %s",
                info.command_result.output,
                info.command_result.error,
                task_id,
            )
            logger.info(f"POV {pov_path} for task: {task_id} crashed: {info.did_crash()}")
            if info.did_crash():
                was_marked = self.pov_status.mark_non_mitigated(entry)
                if not was_marked:
                    logger.debug(
                        "Failed to mark POV as non-mitigated for task %s - item was not in pending state (another worker might have marked it)",
                        task_id,
                    )
            else:
                was_marked = self.pov_status.mark_mitigated(entry)
                if not was_marked:
                    logger.debug(
                        "Failed to mark POV as mitigated for task %s - item was not in pending state (another worker might have marked it)",
                        task_id,
                    )

        return True

    def serve(self) -> None:
        logger.info("Starting POV Reproducer")
        serve_loop(self.serve_item, self.sleep_time)
