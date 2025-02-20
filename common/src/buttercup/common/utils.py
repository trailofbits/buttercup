import shutil
import errno
import tempfile
import contextlib
import logging
from contextlib import contextmanager
from typing import Iterator, Any, Callable
from tempfile import TemporaryDirectory
from pathlib import Path
from os import PathLike
import time

logger = logging.getLogger(__name__)


def copyanything(src: PathLike, dst: PathLike, **kwargs: Any) -> None:
    """Copy a file or directory to a destination.
    This function will:
    - Copy directories recursively
    - Copy single files
    - Handle existing destinations
    """
    src, dst = Path(src), Path(dst)
    try:
        shutil.copytree(src, dst, dirs_exist_ok=True, **kwargs)
    except OSError as exc:  # python >2.5
        if exc.errno in (errno.ENOTDIR, errno.EINVAL):
            shutil.copy(src, dst)
        else:
            raise


@contextmanager
def create_tmp_dir(work_dir: Path | None, delete: bool = True, prefix: str | None = None) -> Iterator[Path]:
    """Create a temporary directory inside a working dir and either keep or
    delete it after use."""
    if work_dir:
        work_dir.mkdir(parents=True, exist_ok=True)

    if delete:
        try:
            with TemporaryDirectory(dir=work_dir, prefix=prefix, ignore_cleanup_errors=True) as tmp_dir:
                yield Path(tmp_dir)
        except PermissionError as e:
            logger.warning("Issues while creating/deleting a temporary directory...")
            if logger.getEffectiveLevel() == logging.DEBUG:
                logger.exception(f"PermissionError: {e}")
    else:
        with contextlib.nullcontext(tempfile.mkdtemp(dir=work_dir, prefix=prefix)) as tmp_dir:
            yield Path(tmp_dir)


def get_diffs(path: Path | None) -> list[Path]:
    """Get all diff files in the given path."""
    if path is None:
        return []
    logger.info(f"Getting diffs from {path}")
    diff_files = list(path.rglob("*.patch")) + list(path.rglob("*.diff"))
    if not diff_files:
        # If no .patch or .diff files found, try any file
        diff_files = list(path.rglob("*"))

    return sorted(diff_files)


def serve_loop(func: Callable[[], bool], sleep_time: float = 1.0, report_time: float = 60.0) -> None:
    """Serve a function in a loop."""
    if sleep_time < 0:
        raise ValueError("sleep_time must be greater than 0")

    if report_time < 0:
        raise ValueError("report_time must be greater than 0")

    did_work = False
    start_time = time.time()

    while True:
        if time.time() - start_time > report_time:
            logger.info("Sleeping, waiting for inputs")
            start_time = time.time()

        did_work = func()
        if not did_work:
            time.sleep(sleep_time)
