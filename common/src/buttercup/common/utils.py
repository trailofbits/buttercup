import shutil
import errno
import tempfile
import contextlib
from contextlib import contextmanager
from typing import Iterator, Any
from tempfile import TemporaryDirectory
from buttercup.common.logger import setup_logging
from pathlib import Path

logger = setup_logging(__name__)


def copyanything(src: Path | str, dst: Path | str, **kwargs: Any) -> None:
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
            with TemporaryDirectory(dir=work_dir, prefix=prefix) as tmp_dir:
                yield Path(tmp_dir)
        except PermissionError:
            logger.warning("Issues while creating/deleting a temporary directory...")
    else:
        with contextlib.nullcontext(tempfile.mkdtemp(dir=work_dir, prefix=prefix)) as tmp_dir:
            yield Path(tmp_dir)
