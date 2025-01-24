"""Logging utilities"""

import logging

import buttercup.seed_gen

MAIN_LOGGER_NAME = buttercup.seed_gen.__module_name__


def logger_configurer(log_level: str) -> None:
    """Configure main logger."""
    logger = logging.getLogger(MAIN_LOGGER_NAME)
    logger.setLevel(log_level)
    handler = logging.StreamHandler()
    handler.setLevel(log_level)
    formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    handler.setFormatter(formatter)
    if logger.hasHandlers():
        logger.handlers.clear()
    logger.addHandler(handler)
    logger.propagate = False
