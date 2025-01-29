"""Utility functions"""

import importlib.resources
from pathlib import Path

from buttercup.seed_gen import __module_name__


def resolve_module_subpath(subpath: str) -> Path:
    """Returns absolute path for file at subpath in module"""
    traversable = importlib.resources.files(f"buttercup.{__module_name__}").joinpath(subpath)
    return Path(str(traversable)).resolve()
