"""Configure loggers."""

from __future__ import annotations

import logging

import buttercup.program_model

MAIN_LOGGER_NAME = buttercup.program_model.__module_name__


def logger_configurer(log_level: str | int) -> None:
    """Configure main logger."""
    logger = logging.getLogger(MAIN_LOGGER_NAME)
    logger.setLevel(log_level)
    handler = logging.StreamHandler()
    handler.setLevel(log_level)
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    handler.setFormatter(formatter)
    if logger.hasHandlers():
        logger.handlers.clear()
    logger.addHandler(handler)
    logger.propagate = False
