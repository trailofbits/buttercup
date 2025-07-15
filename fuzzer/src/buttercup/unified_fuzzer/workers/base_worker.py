"""Base worker class for unified fuzzer components."""

import logging
import queue
import threading
import time
from abc import ABC, abstractmethod
from typing import Any, Optional

logger = logging.getLogger(__name__)


class BaseWorker(ABC):
    """Base class for all worker threads in the unified fuzzer."""
    
    def __init__(self, name: str, config: dict):
        self.name = name
        self.config = config
        self._stop_event = threading.Event()
        self._sleep_seconds = float(config.get('timer', 1000)) / 1000.0
        
    @abstractmethod
    def process_item(self, item: Any) -> bool:
        """Process a single work item.
        
        Returns:
            bool: True if item was processed successfully, False otherwise
        """
        pass
    
    def stop(self):
        """Signal the worker to stop."""
        logger.info(f"Stopping {self.name} worker")
        self._stop_event.set()
    
    def should_stop(self) -> bool:
        """Check if the worker should stop."""
        return self._stop_event.is_set()
    
    def run(self):
        """Main worker loop."""
        logger.info(f"Starting {self.name} worker")
        
        while not self.should_stop():
            try:
                # Let subclasses implement their own work retrieval and processing
                if not self.work_iteration():
                    # No work available, sleep
                    time.sleep(self._sleep_seconds)
                    
            except Exception:
                logger.exception(f"Error in {self.name} worker")
                time.sleep(1)
        
        logger.info(f"{self.name} worker stopped")
    
    @abstractmethod  
    def work_iteration(self) -> bool:
        """Perform one iteration of work.
        
        Returns:
            bool: True if work was done, False if no work available
        """
        pass


class QueueWorker(BaseWorker):
    """Worker that processes items from a queue."""
    
    def __init__(self, name: str, input_queue: queue.Queue, config: dict):
        super().__init__(name, config)
        self.input_queue = input_queue
    
    def work_iteration(self) -> bool:
        """Get item from queue and process it."""
        try:
            # Try to get item with timeout
            item = self.input_queue.get(timeout=0.1)
            return self.process_item(item)
        except queue.Empty:
            return False