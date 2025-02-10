import shutil
import errno
import tempfile
import contextlib
import logging
from contextlib import contextmanager
from typing import Iterator, Any
from tempfile import TemporaryDirectory
from pathlib import Path
from os import PathLike

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
        except PermissionError:
            logger.warning("Issues while creating/deleting a temporary directory...")
    else:
        with contextlib.nullcontext(tempfile.mkdtemp(dir=work_dir, prefix=prefix)) as tmp_dir:
            yield Path(tmp_dir)


def get_diffs(path: Path) -> list[Path]:
    """Get all diff files in the given path."""
    diff_files = list(path.rglob("*.patch")) + list(path.rglob("*.diff"))
    if not diff_files:
        # If no .patch or .diff files found, try any file
        diff_files = list(path.rglob("*"))

    return sorted(diff_files)
