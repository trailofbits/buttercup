"""Background task manager for the scheduler.

This module manages background tasks that run periodically alongside the main scheduler loop.
It provides a thread-safe way to run maintenance tasks like scratch cleanup, corpus merging, etc.
"""

import logging
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, Optional, Callable, Any
from datetime import datetime

logger = logging.getLogger(__name__)


class BackgroundTask(ABC):
    """Base class for background tasks."""
    
    def __init__(self, name: str, interval_seconds: float):
        self.name = name
        self.interval_seconds = interval_seconds
        self.last_run: Optional[datetime] = None
        self.run_count: int = 0
        self.error_count: int = 0
        self.last_error: Optional[str] = None
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        
    @abstractmethod
    def execute(self) -> bool:
        """Execute the background task.
        
        Returns:
            bool: True if work was done, False otherwise
        """
        pass
    
    def _run_loop(self) -> None:
        """Main loop for the background task thread."""
        logger.info(f"Starting background task: {self.name}")
        
        while not self._stop_event.is_set():
            try:
                # Execute the task
                start_time = time.time()
                did_work = self.execute()
                elapsed = time.time() - start_time
                
                self.last_run = datetime.now()
                self.run_count += 1
                
                if did_work:
                    logger.debug(
                        f"Background task '{self.name}' completed in {elapsed:.2f}s (did work)"
                    )
                else:
                    logger.debug(
                        f"Background task '{self.name}' completed in {elapsed:.2f}s (no work)"
                    )
                    
            except Exception as e:
                self.error_count += 1
                self.last_error = str(e)
                logger.exception(f"Error in background task '{self.name}': {e}")
            
            # Wait for interval or stop event
            self._stop_event.wait(self.interval_seconds)
    
    def start(self) -> None:
        """Start the background task thread."""
        if self._thread is not None and self._thread.is_alive():
            logger.warning(f"Background task '{self.name}' is already running")
            return
            
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, name=f"bg-{self.name}")
        self._thread.daemon = True
        self._thread.start()
    
    def stop(self) -> None:
        """Stop the background task thread."""
        if self._thread is None:
            return
            
        logger.info(f"Stopping background task: {self.name}")
        self._stop_event.set()
        self._thread.join(timeout=5.0)
        
        if self._thread.is_alive():
            logger.warning(f"Background task '{self.name}' did not stop cleanly")
    
    def get_status(self) -> Dict[str, Any]:
        """Get status information about the task."""
        return {
            "name": self.name,
            "running": self._thread.is_alive() if self._thread else False,
            "interval_seconds": self.interval_seconds,
            "last_run": self.last_run.isoformat() if self.last_run else None,
            "run_count": self.run_count,
            "error_count": self.error_count,
            "last_error": self.last_error,
        }


@dataclass
class BackgroundTaskManager:
    """Manager for background tasks in the scheduler."""
    
    tasks: Dict[str, BackgroundTask] = field(default_factory=dict)
    
    def register_task(self, task: BackgroundTask) -> None:
        """Register a background task."""
        if task.name in self.tasks:
            raise ValueError(f"Task '{task.name}' is already registered")
            
        self.tasks[task.name] = task
        logger.info(f"Registered background task: {task.name}")
    
    def start_all(self) -> None:
        """Start all registered background tasks."""
        logger.info(f"Starting {len(self.tasks)} background tasks")
        for task in self.tasks.values():
            task.start()
    
    def stop_all(self) -> None:
        """Stop all background tasks."""
        logger.info(f"Stopping {len(self.tasks)} background tasks")
        for task in self.tasks.values():
            task.stop()
    
    def get_status(self) -> Dict[str, Dict[str, Any]]:
        """Get status of all background tasks."""
        return {name: task.get_status() for name, task in self.tasks.items()}
    
    def log_status(self) -> None:
        """Log the status of all background tasks."""
        status = self.get_status()
        for task_name, task_status in status.items():
            if task_status["running"]:
                logger.info(
                    f"Background task '{task_name}': runs={task_status['run_count']}, "
                    f"errors={task_status['error_count']}, last_run={task_status['last_run']}"
                )
            else:
                logger.warning(f"Background task '{task_name}' is not running")


class CallableBackgroundTask(BackgroundTask):
    """A background task that runs a callable function."""
    
    def __init__(self, name: str, interval_seconds: float, func: Callable[[], bool]):
        super().__init__(name, interval_seconds)
        self.func = func
    
    def execute(self) -> bool:
        """Execute the callable function."""
        return self.func()