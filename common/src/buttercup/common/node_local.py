# Store the node local path for subsequent use
from contextlib import contextmanager
import logging
import os
from pathlib import Path
import shutil
import tarfile
from tempfile import NamedTemporaryFile
import tempfile
from typing import Any, Iterator, TypeAlias

logger = logging.getLogger(__name__)

node_local_path = os.getenv("NODE_DATA_DIR")


NodeLocalPath: TypeAlias = Path
RemotePath: TypeAlias = Path


def _get_root_path() -> NodeLocalPath:
    assert node_local_path is not None, "NODE_DATA_DIR environment variable is not defined"
    return NodeLocalPath(node_local_path)


class TmpDir:
    def __init__(self, path: Path):
        self.path = path
        self.commit = False

    def __fspath__(self) -> str:
        return str(self.path)


@contextmanager
def temp_dir(root_path: Path) -> Iterator[TmpDir]:
    # Manually create the directory to control deletion based on commit flag
    tmp_path_str = tempfile.mkdtemp(dir=root_path)
    tmp_path = Path(tmp_path_str)
    d = TmpDir(tmp_path)
    try:
        yield d
    finally:
        # Only remove the directory if it wasn't committed
        if not d.commit:
            shutil.rmtree(tmp_path, ignore_errors=True)


def rename_atomically(src: Path, dst: Path) -> Path | None:
    """Rename a file atomically"""
    src = Path(src)
    dst = Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.rename(src, dst)
    except OSError as e:
        # If the path already exists, it means another pod already downloaded it
        # we can just ignore this error and return None to signify that the path already exists
        if e.errno == 39:
            logger.debug(f"Local path {dst} already exists for {src}")
            return None
        raise e
    return dst


def remote_path(local_path: NodeLocalPath) -> RemotePath:
    """Convert the node local path to a remote path"""
    local_path = Path(local_path)

    # Get path relative to NODE_DATA_DIR if applicable
    root_path = _get_root_path()
    assert local_path.is_relative_to(root_path), (
        f"Input path ({local_path}) must be relative to NODE_DATA_DIR ({root_path})"
    )
    relative_path = local_path.relative_to(root_path)
    # Make absolute path
    return Path("/") / relative_path


def remote_archive_path(local_path: NodeLocalPath) -> RemotePath:
    """Convert the node local path to a remote path with .tgz suffix for archived directories"""
    return RemotePath(str(remote_path(local_path)) + ".tgz")


def scratch_path() -> NodeLocalPath:
    """Return the local path to the scratch directory"""
    scratch_dir = _get_root_path() / "scratch"
    scratch_dir.mkdir(parents=True, exist_ok=True)
    return scratch_dir


def scratch_dir() -> TmpDir:
    """Return a temporary directory in the scratch directory"""
    return temp_dir(scratch_path())


def local_scratch_file(**kwargs) -> NamedTemporaryFile:
    """Return a temporary file in the local scratch directory"""
    sp = scratch_path()
    return NamedTemporaryFile(dir=sp, **kwargs)


def remote_scratch_file(local_path: NodeLocalPath, **kwargs) -> NamedTemporaryFile:
    """Get a temporary file in the remote storage corresponding to the node local path"""
    dp = remote_path(local_path)
    assert dp.is_absolute(), "Input path must be absolute"
    return NamedTemporaryFile(dir=Path("/") / dp.parts[1], **kwargs)


def make_locally_available(local_path: NodeLocalPath) -> NodeLocalPath:
    """Download a file from the remote storage and make it locally available"""
    local_path = Path(local_path)
    assert local_path.is_absolute(), f"Local path ({local_path}) must be absolute"
    if local_path.exists():
        return NodeLocalPath(local_path)
    rpath = remote_path(local_path)
    local_path.parent.mkdir(parents=True, exist_ok=True)
    with local_scratch_file(delete=False) as scratch_file:
        with open(rpath, "rb") as remote_file:
            shutil.copyfileobj(remote_file, scratch_file)
        local_temp_path = scratch_file.name

    renamed_path = rename_atomically(local_temp_path, local_path)
    if renamed_path is None:
        # If the path already exists, it means another pod already downloaded it
        # just drop our temp file
        os.unlink(local_temp_path)
    return NodeLocalPath(local_path)


def remote_archive_to_dir(local_path: NodeLocalPath) -> NodeLocalPath:
    """Download a directory from the remote storage, it is stored as a .tgz file remotely"""
    local_path = Path(local_path)
    assert local_path.is_absolute(), f"Input path ({local_path}) must be absolute"
    if local_path.exists():
        return NodeLocalPath(local_path)

    # Get the remote path
    rpath = remote_archive_path(local_path)
    logger.info(f"Downloading {rpath} to {local_path}")

    with open(rpath, "rb") as remote_file:
        with local_scratch_file(suffix=".tgz") as scratch_file:
            shutil.copyfileobj(remote_file, scratch_file)
            scratch_file.flush()
            scratch_file.seek(0)

            # Unpack the tgz file into a temporary directory
            with scratch_dir() as tmp_dir:
                # Shouldn't be a security risk as we create the archives ourselves
                with tarfile.open(fileobj=scratch_file, mode="r:gz") as tar:
                    tar.extractall(path=tmp_dir.path)

                # Now, atomically move the tmp_dir to the final location
                renamed_path = rename_atomically(tmp_dir.path, local_path)
                if renamed_path is not None:
                    tmp_dir.commit = True

    return NodeLocalPath(local_path)


def dir_to_remote_archive(local_path: NodeLocalPath) -> RemotePath:
    """Upload a directory as a .tgz file to the remote storage"""
    local_path = Path(local_path)
    assert local_path.is_absolute(), f"Local path ({local_path}) must be absolute"
    assert local_path.is_dir(), f"Local path ({local_path}) must be a directory"

    with local_scratch_file(suffix=".tgz") as scratch_file:
        with tarfile.open(scratch_file.name, "w:gz") as tar:
            tar.add(local_path, arcname=".")
        scratch_file.flush()
        scratch_file.seek(0)

        rpath = remote_archive_path(local_path)
        with remote_scratch_file(local_path, delete=False) as remote_file:
            shutil.copyfileobj(scratch_file, remote_file)
            remote_tmp_name = remote_file.name

        renamed_path = rename_atomically(remote_tmp_name, rpath)
        if renamed_path is None:
            # If the path already exists, it means another pod already downloaded it
            # just drop our temp file
            os.unlink(remote_tmp_name)
    return rpath


def lopen(local_path: NodeLocalPath, mode: str) -> Any:
    """Open a file in the node local storage

    If it doesn't exist, it will be downloaded from the remote storage"""
    make_locally_available(local_path)
    return open(local_path, mode)
