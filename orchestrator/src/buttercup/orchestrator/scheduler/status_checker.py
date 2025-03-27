import logging
import time
from typing import Callable

logger = logging.getLogger(__name__)


class StatusChecker:
    """Class that handles status checking with rate limiting."""

    def __init__(self, check_interval: float = 60.0):
        """Initialize the status checker.

        Args:
            check_interval: How often to check statuses in seconds
        """
        self.last_check = 0.0
        self.check_interval = check_interval

    def should_check(self) -> bool:
        """Check if enough time has passed since the last status check."""
        current_time = time.time()
        if current_time - self.last_check < self.check_interval:
            return False
        self.last_check = current_time
        return True

    def check_statuses(self, check_fn: Callable[[], bool]) -> bool:
        """Execute the provided check function if rate limit allows.

        Args:
            check_fn: Function to execute for checking statuses

        Returns:
            bool: True if the check was executed, False otherwise
        """
        if not self.should_check():
            return False
        try:
            return check_fn()
        except Exception as e:
            logger.error(f"Failed to check statuses: {str(e)}")
            return False
