from __future__ import annotations

from dataclasses import dataclass, field
import logging
from pathlib import Path
import shutil
from redis import Redis
from buttercup.common.task_registry import TaskRegistry
from buttercup.common.utils import serve_loop

logger = logging.getLogger(__name__)


@dataclass
class ScratchCleaner:
    redis: Redis
    scratch_dir: Path
    sleep_time: float = 60.0
    delete_old_tasks_scratch_delta_seconds: int = 1800  # 30 minutes default

    task_registry: TaskRegistry = field(init=False)

    def __post_init__(self) -> None:
        self.task_registry = TaskRegistry(self.redis)

    def serve_item(self) -> bool:
        """Delete old tasks related directories from the scratch directory"""
        if self.scratch_dir is None:
            return False

        logger.info(f"Checking for old tasks in scratch directory {self.scratch_dir}")
        did_delete = False
        for task in self.task_registry:
            if not self.task_registry.is_expired(task, delta_seconds=self.delete_old_tasks_scratch_delta_seconds):
                continue

            task_dir = self.scratch_dir / task.task_id
            if task_dir.exists() and task_dir.is_dir():
                try:
                    logger.info(f"Deleting CRS scratch space for expired task {task.task_id}")
                    shutil.rmtree(task_dir, ignore_errors=True)
                    logger.info(f"Deleted CRS scratch space for expired task {task.task_id}")
                    did_delete = True
                except Exception:
                    logger.exception(f"Failed to delete CRS scratch space for expired task {task.task_id}")

        return did_delete

    def serve(self) -> None:
        """Main loop for the scratch cleaner service"""
        logger.info("Starting scratch cleaner service")
        serve_loop(self.serve_item, self.sleep_time)
