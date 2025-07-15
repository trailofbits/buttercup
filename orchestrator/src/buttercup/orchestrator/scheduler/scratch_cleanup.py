"""Scratch cleanup background task for the scheduler.

This module provides scratch directory cleanup functionality as a background task,
replacing the standalone scratch-cleaner service.
"""

import logging
import shutil
from pathlib import Path
from typing import Optional

from redis import Redis

from buttercup.common.task_registry import TaskRegistry
from .background_tasks import BackgroundTask

logger = logging.getLogger(__name__)


class ScratchCleanupTask(BackgroundTask):
    """Background task for cleaning up expired task scratch directories."""
    
    def __init__(
        self,
        redis: Redis,
        scratch_dir: Path,
        interval_seconds: float = 60.0,
        delete_old_tasks_delta_seconds: int = 1800,  # 30 minutes default
    ):
        super().__init__("scratch-cleanup", interval_seconds)
        self.redis = redis
        self.scratch_dir = scratch_dir
        self.delete_old_tasks_delta_seconds = delete_old_tasks_delta_seconds
        self.task_registry = TaskRegistry(self.redis)
        
    def execute(self) -> bool:
        """Delete old tasks related directories from the scratch directory.
        
        Returns:
            bool: True if any directories were deleted, False otherwise
        """
        if not self.scratch_dir or not self.scratch_dir.exists():
            logger.warning(f"Scratch directory {self.scratch_dir} does not exist")
            return False
        
        logger.debug(f"Checking for old tasks in scratch directory {self.scratch_dir}")
        did_delete = False
        
        try:
            for task in self.task_registry:
                # Check if task is expired
                if not self.task_registry.is_expired(
                    task, delta_seconds=self.delete_old_tasks_delta_seconds
                ):
                    continue
                
                # Check if task directory exists
                task_dir = self.scratch_dir / task.task_id
                if not task_dir.exists() or not task_dir.is_dir():
                    continue
                
                try:
                    logger.info(f"Deleting CRS scratch space for expired task {task.task_id}")
                    shutil.rmtree(task_dir, ignore_errors=True)
                    logger.info(f"Deleted CRS scratch space for expired task {task.task_id}")
                    did_delete = True
                except Exception:
                    logger.exception(
                        f"Failed to delete CRS scratch space for expired task {task.task_id}"
                    )
                    
        except Exception as e:
            logger.error(f"Error during scratch cleanup scan: {e}")
            raise
            
        return did_delete