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


def extract_code(msg: AIMessage) -> str:
    """Extract last markdown block or partial block from the AIMessage"""
    if not isinstance(msg, AIMessage):
        raise OutputParserException("Did not receive an AIMessage. Received: %s", type(msg))
    content = msg.content

    if not isinstance(content, str):
        raise OutputParserException(f"Content is not a string. Content is {type(content)}")

    # Try to get last complete markdown block
    find_iter = re.finditer(r"```([A-Za-z]*)\n(.*?)```", content, re.DOTALL)
    match = None
    for m in find_iter:
        match = m

    if match is not None:
        return match.group(2)

    # If no complete block found, try to get partial block
    # Captures everything except the last function definition (likely incomplete)
    partial_match = re.search(
        r"```([A-Za-z]*)\n(.*)(?=\n\s*def\s+[A-Za-z0-9_]+\s*\([^)]*\))", content, re.DOTALL
    )
    if partial_match is not None:
        logger.info("Found partial code block")
        return partial_match.group(2)

    raise OutputParserException("Failed to extract code from message")


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
