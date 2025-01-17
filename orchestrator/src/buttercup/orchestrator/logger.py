import logging
from typing import Optional
from buttercup.orchestrator.dependencies import get_settings

_is_initialized = False


def setup_logging(logger_name: Optional[str] = None) -> logging.Logger:
    global _is_initialized
    settings = get_settings()

    if not _is_initialized:
        # Clear any existing handlers to avoid duplicates
        root = logging.getLogger()
        if root.handlers:
            for handler in root.handlers:
                root.removeHandler(handler)

        # Configure root logger
        logging.basicConfig(
            level=settings.log_level,
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            handlers=[logging.StreamHandler(), logging.FileHandler("app.log")],
        )

        _is_initialized = True

    # Return a logger with the caller's module name or specified name
    return logging.getLogger(logger_name or __name__)
