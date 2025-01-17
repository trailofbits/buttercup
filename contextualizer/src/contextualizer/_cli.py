"""The `contextualizer` entrypoint."""

from __future__ import annotations

import argparse
import logging
import os
from argparse import ArgumentDefaultsHelpFormatter

from contextualizer.logger import logger_configurer

logger_configurer(os.getenv("LOG_LEVEL", "INFO").upper())
logger = logging.getLogger(__name__)


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        "contextualizer",
        formatter_class=ArgumentDefaultsHelpFormatter,
    )

    parser.add_argument(
        "--id",
        required=True,
        type=int,
        help="ID",
    )

    args = parser.parse_args()

    logger.info("Starting contextualizer")
    logger.debug("Args %s", args)

    logger.info("Terminating contextualizer.")
