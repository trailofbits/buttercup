"""Scratch cleaner background task for the scheduler.

This module integrates the scratch cleaner functionality as a background task
within the scheduler, eliminating the need for a separate service container.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

from redis import Redis

from buttercup.common.task_registry import TaskRegistry
from buttercup.orchestrator.scheduler.background_tasks import BackgroundTask

logger = logging.getLogger(__name__)


class ScratchCleanerTask(BackgroundTask):
    """Background task for cleaning up old task directories from scratch storage."""

    def __init__(
        self,
        redis: Redis,
        scratch_dir: Path,
        interval: float = 60.0,
        delete_old_tasks_delta_seconds: int = 1800,  # 30 minutes default
    ):
        super().__init__(name="scratch-cleaner", interval=interval)
        self.redis = redis
        self.scratch_dir = scratch_dir
        self.delete_old_tasks_delta_seconds = delete_old_tasks_delta_seconds
        self.task_registry = TaskRegistry(redis)

    def execute(self) -> bool:
        """Delete old task directories from the scratch directory.

        Returns:
            bool: True if any directories were deleted, False otherwise
        """
        if not self.scratch_dir or not self.scratch_dir.exists():
            logger.warning(f"Scratch directory {self.scratch_dir} does not exist")
            return False

        logger.info(f"Checking for old tasks in scratch directory {self.scratch_dir}")
        did_delete = False
        deleted_count = 0
        error_count = 0

        try:
            for task in self.task_registry:
                if not self.task_registry.is_expired(
                    task, delta_seconds=self.delete_old_tasks_delta_seconds
                ):
                    continue

                task_dir = self.scratch_dir / task.task_id
                if task_dir.exists() and task_dir.is_dir():
                    try:
                        logger.info(f"Deleting CRS scratch space for expired task {task.task_id}")
                        shutil.rmtree(task_dir, ignore_errors=True)
                        logger.info(f"Deleted CRS scratch space for expired task {task.task_id}")
                        deleted_count += 1
                        did_delete = True
                    except Exception:
                        logger.exception(f"Failed to delete CRS scratch space for expired task {task.task_id}")
                        error_count += 1

            if deleted_count > 0:
                logger.info(f"Scratch cleaner deleted {deleted_count} expired task directories")
            else:
                logger.debug("Scratch cleaner found no expired task directories to delete")

            if error_count > 0:
                logger.warning(f"Scratch cleaner encountered {error_count} errors during cleanup")

            return did_delete

        except Exception as e:
            logger.error(f"Error during scratch cleanup: {e}", exc_info=True)
            return False