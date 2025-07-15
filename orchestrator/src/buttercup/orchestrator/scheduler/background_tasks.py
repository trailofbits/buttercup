"""Background task management for the scheduler.

This module provides infrastructure for running periodic background tasks
within the scheduler, eliminating the need for separate service containers.
"""

from __future__ import annotations

import logging
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from redis import Redis

logger = logging.getLogger(__name__)


class BackgroundTask(ABC):
    """Abstract base class for background tasks."""

    def __init__(self, name: str, interval: float):
        self.name = name
        self.interval = interval
        self.last_run: Optional[datetime] = None
        self.is_running = False
        self.error_count = 0
        self.success_count = 0

    @abstractmethod
    def execute(self) -> bool:
        """Execute the background task.

        Returns:
            bool: True if the task executed successfully, False otherwise
        """
        pass

    def should_run(self) -> bool:
        """Check if the task should run based on its interval."""
        if self.last_run is None:
            return True
        
        elapsed = (datetime.now() - self.last_run).total_seconds()
        return elapsed >= self.interval

    def run(self) -> None:
        """Run the task with error handling and statistics tracking."""
        if self.is_running:
            logger.warning(f"Background task {self.name} is already running, skipping")
            return

        self.is_running = True
        try:
            logger.debug(f"Starting background task: {self.name}")
            success = self.execute()
            if success:
                self.success_count += 1
                self.error_count = 0  # Reset error count on success
            else:
                self.error_count += 1
                
            self.last_run = datetime.now()
            logger.debug(f"Completed background task: {self.name} (success={success})")
        except Exception as e:
            self.error_count += 1
            self.last_run = datetime.now()  # Update last_run even on error
            logger.error(f"Error in background task {self.name}: {e}", exc_info=True)
        finally:
            self.is_running = False

    def get_status(self) -> Dict[str, Any]:
        """Get the current status of the background task."""
        return {
            "name": self.name,
            "interval": self.interval,
            "last_run": self.last_run.isoformat() if self.last_run else None,
            "is_running": self.is_running,
            "error_count": self.error_count,
            "success_count": self.success_count,
        }


@dataclass
class BackgroundTaskManager:
    """Manages multiple background tasks in separate threads."""

    tasks: list[BackgroundTask] = field(default_factory=list)
    _threads: Dict[str, threading.Thread] = field(default_factory=dict)
    _stop_event: threading.Event = field(default_factory=threading.Event)

    def add_task(self, task: BackgroundTask) -> None:
        """Add a background task to the manager."""
        self.tasks.append(task)
        logger.info(f"Added background task: {task.name} (interval={task.interval}s)")

    def start(self) -> None:
        """Start all background tasks in separate threads."""
        logger.info(f"Starting {len(self.tasks)} background tasks")
        self._stop_event.clear()
        
        for task in self.tasks:
            thread = threading.Thread(
                target=self._run_task_loop,
                args=(task,),
                name=f"bg-{task.name}",
                daemon=True
            )
            self._threads[task.name] = thread
            thread.start()
            logger.info(f"Started background task thread: {task.name}")

    def stop(self) -> None:
        """Stop all background tasks."""
        logger.info("Stopping background tasks")
        self._stop_event.set()
        
        # Wait for all threads to complete
        for name, thread in self._threads.items():
            if thread.is_alive():
                logger.info(f"Waiting for background task {name} to stop")
                thread.join(timeout=5.0)
                if thread.is_alive():
                    logger.warning(f"Background task {name} did not stop gracefully")
        
        self._threads.clear()
        logger.info("All background tasks stopped")

    def _run_task_loop(self, task: BackgroundTask) -> None:
        """Run a background task in a loop until stopped."""
        logger.info(f"Background task loop started: {task.name}")
        
        while not self._stop_event.is_set():
            if task.should_run():
                task.run()
            
            # Sleep in small intervals to allow for responsive shutdown
            sleep_interval = min(1.0, task.interval / 10)
            elapsed = 0.0
            while elapsed < task.interval and not self._stop_event.is_set():
                time.sleep(sleep_interval)
                elapsed += sleep_interval
        
        logger.info(f"Background task loop stopped: {task.name}")

    def get_status(self) -> Dict[str, Any]:
        """Get the status of all background tasks."""
        return {
            "tasks": [task.get_status() for task in self.tasks],
            "active_threads": len([t for t in self._threads.values() if t.is_alive()]),
        }

    def health_check(self) -> bool:
        """Check if all background tasks are healthy.

        A task is considered unhealthy if:
        - Its thread is not alive
        - It has too many consecutive errors (>5)
        """
        all_healthy = True
        
        for task in self.tasks:
            thread = self._threads.get(task.name)
            if thread and not thread.is_alive():
                logger.error(f"Background task thread {task.name} is not alive")
                all_healthy = False
            
            if task.error_count > 5:
                logger.error(f"Background task {task.name} has {task.error_count} consecutive errors")
                all_healthy = False
        
        return all_healthy