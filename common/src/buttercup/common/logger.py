import logging
import os
import tempfile

_is_initialized = False
PACKAGE_LOGGER_NAME = "buttercup"


def setup_package_logger(logger_name: str, log_level: str = "info") -> logging.Logger:
    global _is_initialized

    if not _is_initialized:
        # Clear any existing handlers to avoid duplicates
        root = logging.getLogger()
        if root.handlers:
            for handler in root.handlers:
                root.removeHandler(handler)

        persistent_log_dir = os.getenv("PERSISTENT_LOG_DIR", None)

        handlers = [
            logging.StreamHandler(),
            logging.FileHandler(os.path.join(tempfile.gettempdir(), f"{logger_name}.log")),
        ]
        if persistent_log_dir:
            handlers.append(logging.FileHandler(os.path.join(persistent_log_dir, f"{logger_name}.log")))

        # Configure root logger
        logging.basicConfig(
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            handlers=handlers,
        )

        _package_logger = logging.getLogger(PACKAGE_LOGGER_NAME)
        _package_logger.setLevel(log_level.upper())

        _is_initialized = True

    return logging.getLogger(PACKAGE_LOGGER_NAME)
