import logging
import os
import tempfile
from typing import Optional

_is_initialized = False


def setup_logging(logger_name: Optional[str] = None, log_level: str = "info") -> logging.Logger:
    global _is_initialized

    if not _is_initialized:
        # Clear any existing handlers to avoid duplicates
        root = logging.getLogger()
        if root.handlers:
            for handler in root.handlers:
                root.removeHandler(handler)

        # Configure root logger
        logging.basicConfig(
            level=log_level.upper(),
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            handlers=[
                logging.StreamHandler(),
                logging.FileHandler(os.path.join(tempfile.gettempdir(), f"{logger_name or __name__}.log")),
            ],
        )

        _is_initialized = True

    # Return a logger with the caller's module name or specified name
    return logging.getLogger(logger_name or __name__)
