import os
import tempfile
import contextvars
import logging
from contextlib import contextmanager
from typing import Iterator
from unittest.mock import patch
from clusterfuzz._internal.system import environment, shell
from buttercup.common.node_local import scratch_dir, TmpDir

logger = logging.getLogger(__name__)

# Context variable to store the current scratch directory path
_scratch_path_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("scratch_path", default=None)


def get_temp_dir(use_fuzz_inputs_disk: bool = True) -> str:
    """Return the temp dir."""
    temp_dirname = "temp-" + str(os.getpid())

    # Use the current scratch path if available, otherwise fall back to original logic
    scratch_path = _scratch_path_var.get()
    if scratch_path is not None:
        prefix = scratch_path
        logger.debug(f"PATCHED get_temp_dir called: using scratch path {prefix}")
    elif use_fuzz_inputs_disk:
        prefix = environment.get_value("FUZZ_INPUTS_DISK", tempfile.gettempdir())
        logger.debug(f"PATCHED get_temp_dir called: using FUZZ_INPUTS_DISK {prefix}")
    else:
        prefix = tempfile.gettempdir()
        logger.debug(f"PATCHED get_temp_dir called: using system temp {prefix}")

    temp_directory = os.path.join(prefix, temp_dirname)
    shell.create_directory(temp_directory)
    logger.debug(f"PATCHED get_temp_dir created: {temp_directory}")
    return temp_directory


@contextmanager
def patched_temp_dir() -> Iterator[TmpDir]:
    """Context manager that creates a node-local scratch directory and patches
    clusterfuzz._internal.bot.fuzzers.utils.get_temp_dir to return our get_temp_dir.

    While the context is active, any calls to clusterfuzz's get_temp_dir will be
    redirected to our custom implementation that uses the node-local scratch directory.
    """
    with scratch_dir() as scratch:
        # Set the scratch path in the context variable
        token = _scratch_path_var.set(str(scratch.path))

        try:
            # Patch the clusterfuzz get_temp_dir function to use our implementation
            with patch("clusterfuzz._internal.bot.fuzzers.utils.get_temp_dir", get_temp_dir):
                yield scratch
        finally:
            # Reset the context variable to its previous value
            _scratch_path_var.reset(token)


@contextmanager
def scratch_cwd() -> Iterator[TmpDir]:
    """Context manager that creates a node-local scratch directory and changes
    the current working directory to it.

    While the context is active, the current working directory will be the scratch
    directory. Upon exit, the original working directory is restored.
    """
    original_cwd = os.getcwd()

    with scratch_dir() as scratch:
        try:
            os.chdir(scratch.path)
            logger.debug(f"Changed working directory to scratch: {scratch.path}")
            yield scratch
        finally:
            os.chdir(original_cwd)
            logger.debug(f"Restored working directory to: {original_cwd}")
