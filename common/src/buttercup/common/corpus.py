import logging
from typing import List
import buttercup.common.node_local as node_local
from buttercup.common.constants import CORPUS_DIR_NAME, CRASH_DIR_NAME
import os
import hashlib
import shutil
import subprocess
from pathlib import Path
from redis import Redis
from buttercup.common.sets import MergedCorpusSet
import tempfile

logger = logging.getLogger(__name__)


def hash_file(fl):
    h = hashlib.new("sha256")
    bts = fl.read(100)
    while bts:
        h.update(bts)
        bts = fl.read(100)
    return h.hexdigest()


class InputDir:
    def __init__(self, wdir: str, name: str, copy_corpus_max_size: int | None = None):
        self.path = os.path.join(wdir, name)
        self.remote_path = node_local.remote_path(self.path)
        self.copy_corpus_max_size = copy_corpus_max_size
        os.makedirs(self.path, exist_ok=True)

    def basename(self) -> str:
        return os.path.basename(self.path)

    def copy_file(self, src_file: str):
        with open(src_file, "rb") as f:
            nm = hash_file(f)
            dst = os.path.join(self.path, nm)
            dst_remote = os.path.join(self.remote_path, nm)
            os.makedirs(self.remote_path, exist_ok=True)
            # Make the file available both node-local and remote
            shutil.copy(src_file, dst)
            shutil.copy(dst, dst_remote)
            return dst

    def copy_corpus(self, src_dir: str) -> list[str]:
        files = []
        for file in os.listdir(src_dir):
            file_path = os.path.join(src_dir, file)
            size = Path(file_path).stat().st_size
            if self.copy_corpus_max_size is not None and size > self.copy_corpus_max_size:
                logger.warning(
                    "Not copying corpus input (size %s bytes) which exceeds max size %s bytes",
                    size,
                    self.copy_corpus_max_size,
                )
                continue
            files.append(self.copy_file(file_path))
        return files

    def local_corpus_size(self) -> int:
        # this is only the local corpus size
        tot = 0
        for file in os.listdir(self.path):
            try:
                tot += (Path(self.path) / file).lstat().st_size
            except Exception:
                # Files can be renamed and deleted by other pods not an error,
                # but it causes this function to fail. Just ignore them.
                continue
        return tot

    def local_corpus_count(self) -> int:
        return len(os.listdir(self.path))

    def remove_local_file(self, file: str):
        try:
            os.remove(os.path.join(self.path, file))
        except Exception as e:
            logger.error(f"Error removing file {file} from local corpus {self.path}: {e}")

    def remove_file(self, file: str):
        self.remove_local_file(file)
        try:
            os.remove(os.path.join(self.remote_path, file))
        except Exception as e:
            logger.error(f"Error removing file {file} from remote corpus {self.remote_path}: {e}")

    @classmethod
    def has_hashed_name(cls, filename: str | Path) -> bool:
        if not isinstance(filename, Path):
            filename = Path(filename)
        name = filename.name
        return len(name) == 64 and all(c in "0123456789abcdef" for c in name)

    @classmethod
    def hash_corpus(cls, path: str) -> List[str]:
        hashed_files = []
        for file in os.listdir(path):
            # If the file is already a hash, skip it
            if cls.has_hashed_name(file):
                continue
            file_path = os.path.join(path, file)
            try:
                with open(file_path, "rb") as f:
                    hash_filename = hash_file(f)
                os.rename(file_path, os.path.join(path, hash_filename))
                hashed_files.append(hash_filename)
            except Exception as e:
                # Likely already hashed by another pod
                logger.info(f"Error hashing file: {file} {e}")
                continue
        return hashed_files

    def hash_new_corpus(self):
        InputDir.hash_corpus(self.path)

    def _do_sync(self, src_path: str, dst_path: str):
        # Pattern to match SHA256 hashes (64 hex chars)
        hash_pattern = "[0-9a-f]" * 64
        subprocess.call(
            [
                "rsync",
                "-a",
                "--ignore-existing",
                f"--include={hash_pattern}",
                "--exclude=*",
                str(src_path) + "/",
                str(dst_path) + "/",
            ]
        )

    def sync_to_remote(self):
        self.hash_new_corpus()
        os.makedirs(self.remote_path, exist_ok=True)
        self._do_sync(self.path, self.remote_path)

    def sync_specific_files_to_remote(self, files):
        """
        Sync only specific files to remote storage.

        Args:
            files: List of filenames (basename only, not full path) to sync to remote
        """
        self.hash_new_corpus()
        os.makedirs(self.remote_path, exist_ok=True)

        # Create a temporary file containing the list of files to sync
        with tempfile.NamedTemporaryFile(mode="w", delete=True) as file_list:
            # Write each filename to the temporary file
            for file in files:
                file_list.write(f"{file}\n")

            # Flush the file to ensure it's written to disk
            file_list.flush()

            # Use rsync with --files-from to sync only the specified files
            subprocess.call(
                [
                    "rsync",
                    "-a",
                    "--ignore-existing",
                    f"--files-from={file_list.name}",
                    str(self.path) + "/",
                    str(self.remote_path) + "/",
                ]
            )

    def sync_from_remote(self):
        os.makedirs(self.remote_path, exist_ok=True)
        self._do_sync(self.remote_path, self.path)

    def list_local_corpus(self) -> list[str]:
        return [os.path.join(self.path, f) for f in os.listdir(self.path)]

    def list_remote_corpus(self) -> list[str]:
        return [os.path.join(self.remote_path, f) for f in os.listdir(self.remote_path)]

    def list_corpus(self) -> list[str]:
        return self.list_local_corpus()


class CrashDir:
    def __init__(self, wdir: str, task_id: str, harness_name: str, count_limit: int | None = None):
        self.wdir = wdir
        self.crash_dir = os.path.join(task_id, f"{CRASH_DIR_NAME}_{harness_name}")
        self.count_limit = count_limit

    def _input_dir_for_token(self, token: str, sanitizer: str | None = None) -> InputDir:
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        input_dir = os.path.join(self.crash_dir, token_hash)
        if sanitizer:
            input_dir = os.path.join(input_dir, sanitizer)
        return InputDir(self.wdir, input_dir)

    def copy_file(self, src_file: str, crash_token: str, sanitizer: str) -> str:
        idir = self._input_dir_for_token(crash_token, sanitizer)
        first_elem = next(iter(idir.list_corpus()), None)
        if (
            (self.count_limit is not None)
            and (idir.local_corpus_count() > self.count_limit)
            and (first_elem is not None)
        ):
            return first_elem
        return idir.copy_file(src_file)

    def list_crashes_for_token(self, token: str, sanitizer: str, *, get_remote: bool = True) -> list[str]:
        idir = self._input_dir_for_token(token, sanitizer)
        if get_remote:
            idir.sync_from_remote()
        return idir.list_corpus()


class Corpus(InputDir):
    def __init__(self, wdir: str, task_id: str, harness_name: str, copy_corpus_max_size: int | None = None):
        self.task_id = task_id
        self.harness_name = harness_name
        self.corpus_dir = os.path.join(task_id, f"{CORPUS_DIR_NAME}_{harness_name}")
        super().__init__(wdir, self.corpus_dir, copy_corpus_max_size=copy_corpus_max_size)

    def remove_any_merged(self, redis: Redis):
        merged_corpus_set = MergedCorpusSet(redis, self.task_id, self.harness_name)
        logger.info(f"Removing merged files from local corpus {self.path}")
        removed = 0
        local_files = set([os.path.basename(fl) for fl in self.list_local_corpus()])
        for file in merged_corpus_set:
            if file in local_files:
                removed += 1
                try:
                    self.remove_local_file(file)
                except Exception as e:
                    logger.error(f"Error removing file {file} from local corpus {self.path}: {e}")
        if removed > 0:
            logger.info(f"Removed {removed} files from local corpus {self.path}")
