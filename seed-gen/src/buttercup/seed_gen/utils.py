"""Utility functions"""

import importlib.resources
import logging
import re
from pathlib import Path

from langchain_core.exceptions import OutputParserException
from langchain_core.messages import AIMessage

from buttercup.seed_gen import __module_name__

logger = logging.getLogger(__name__)


def resolve_module_subpath(subpath: str) -> Path:
    """Returns absolute path for file at subpath in module"""
    traversable = importlib.resources.files(f"buttercup.{__module_name__}").joinpath(subpath)
    return Path(str(traversable)).resolve()


def extract_md(msg: AIMessage) -> str:
    """Extract last markdown block from the AI message."""
    if not isinstance(msg, AIMessage):
        raise OutputParserException(
            "extract_md: did not receive an AIMessage. Received: %s", type(msg)
        )
    content = msg.content

    if not isinstance(content, str):
        raise OutputParserException(
            "extract_md: content is not a string. Content is %s", type(content)
        )

    # get last markdown block
    find_iter = re.finditer(r"```([A-Za-z]*)\n(.*?)```", content, re.DOTALL)
    match = None
    for m in find_iter:
        match = m

    if match is not None:
        content = match.group(2)
    else:
        logger.warning(
            "extract_md: did not find a markdown block in the AI message. Content is %s...",
            content[:250],
        )

    return content.strip("`")


def get_diff_content(diffs: list[Path]) -> str | None:
    """Process diff files from ChallengeTask.get_diffs()

    Note: currently returns the first diff's content
    """
    # TODO: add support for multiple diffs if necessary
    if len(diffs) == 0:
        logger.info("No diffs found")
        return None
    if len(diffs) > 1:
        logger.warning("Multiple diffs found, using the first one")
    diff_content = diffs[0].read_text()
    return diff_content
