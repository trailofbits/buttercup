"""POV reproducer background task for the scheduler.

This module integrates the POV reproducer functionality as a background task
within the scheduler, eliminating the need for a separate service container.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from redis import Redis

from buttercup.common.challenge_task import ChallengeTask
from buttercup.common.datastructures.msg_pb2 import BuildOutput, BuildType, POVReproduceRequest
from buttercup.common.maps import BuildMap
from buttercup.common.sets import PoVReproduceStatus
from buttercup.common.task_registry import TaskRegistry
import buttercup.common.node_local as node_local
from buttercup.orchestrator.scheduler.background_tasks import BackgroundTask

logger = logging.getLogger(__name__)


class POVReproducerTask(BackgroundTask):
    """Background task for reproducing POVs against patched builds."""

    def __init__(
        self,
        redis: Redis,
        interval: float = 0.1,
        max_retries: int = 10,
    ):
        super().__init__(name="pov-reproducer", interval=interval)
        self.redis = redis
        self.max_retries = max_retries
        self.pov_status = PoVReproduceStatus(redis)
        self.registry = TaskRegistry(redis)
        self.builds = BuildMap(redis)

    def execute(self) -> bool:
        """Process one pending POV reproduction request.

        Returns:
            bool: True if a POV was processed, False otherwise
        """
        entry: Optional[POVReproduceRequest] = self.pov_status.get_one_pending()
        if entry is None:
            return False

        task_id: str = entry.task_id
        internal_patch_id: str = entry.internal_patch_id
        pov_path: str = entry.pov_path
        sanitizer: str = entry.sanitizer
        harness_name: str = entry.harness_name

        # Check if task should still be processed
        if self.registry.should_stop_processing(task_id):
            logger.info(f"Task {task_id} is cancelled or expired, will not reproduce POV")
            was_marked = self.pov_status.mark_expired(entry)
            if not was_marked:
                logger.debug(
                    f"Failed to mark POV as expired for task {task_id} - "
                    "item was not in pending state (another worker might have marked it)"
                )
            return True  # We processed an item, even if we didn't run it

        logger.info(f"Reproducing POV for {task_id} | {harness_name} | {pov_path}")

        # Get the patched build
        build_output_with_patch: Optional[BuildOutput] = self.builds.get_build_from_san(
            task_id,
            BuildType.PATCH,
            sanitizer,
            internal_patch_id,
        )
        if build_output_with_patch is None:
            logger.warning(f"No patched build output found for task {task_id}. Will retry later.")
            return False

        try:
            # Make POV available locally
            local_path: Path = node_local.make_locally_available(Path(pov_path))

            # Run POV against patched build
            challenge_task_dir = ChallengeTask(read_only_task_dir=build_output_with_patch.task_dir)
            with challenge_task_dir.get_rw_copy(work_dir=node_local.scratch_path()) as task:
                info = task.reproduce_pov(harness_name, local_path)
                
                if not info.did_run():
                    logger.warning(
                        f"Reproduce did not run for task {task_id}. Will retry later. Output: {info}"
                    )
                    return False

                logger.debug(
                    f"POV reproduction output for task {task_id}: "
                    f"stdout: {info.command_result.output}, "
                    f"stderr: {info.command_result.error}"
                )
                
                logger.info(f"POV {pov_path} for task {task_id} crashed: {info.did_crash()}")
                
                # Mark POV status based on result
                if info.did_crash():
                    was_marked = self.pov_status.mark_non_mitigated(entry)
                    if not was_marked:
                        logger.debug(
                            f"Failed to mark POV as non-mitigated for task {task_id} - "
                            "item was not in pending state (another worker might have marked it)"
                        )
                else:
                    was_marked = self.pov_status.mark_mitigated(entry)
                    if not was_marked:
                        logger.debug(
                            f"Failed to mark POV as mitigated for task {task_id} - "
                            "item was not in pending state (another worker might have marked it)"
                        )

            return True

        except Exception as e:
            logger.error(f"Error reproducing POV for task {task_id}: {e}", exc_info=True)
            return False