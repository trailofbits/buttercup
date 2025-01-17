"""Initial testing module."""

import logging
import os

import contextualizer
from contextualizer.logger import logger_configurer

logger_configurer(os.getenv("LOG_LEVEL", "INFO").upper())
logger = logging.getLogger(__name__)


def test_version() -> None:
    version = getattr(contextualizer, "__version__", None)
    logger.info("Version: %s", version)
    assert version is not None
    assert isinstance(version, str)
