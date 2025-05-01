import re
import logging
from typing import List
import urllib.parse
import buttercup.common.node_local as node_local
from buttercup.common.constants import CORPUS_DIR_NAME, CRASH_DIR_NAME
import os
import hashlib
import shutil
import subprocess
import uuid
from pathlib import Path
import urllib
from redis import Redis
from buttercup.common.sets import MergedCorpusSet

logger = logging.getLogger(__name__)


def hash_file(fl):
    h = hashlib.new("sha256")
    bts = fl.read(100)
    while bts:
        h.update(bts)
        bts = fl.read(100)
    return h.hexdigest()


class InputDir:
    def __init__(self, wdir: str, name: str):
        self.path = os.path.join(wdir, name)
        self.remote_path = node_local.remote_path(self.path)
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
            files.append(self.copy_file(os.path.join(src_dir, file)))
        return files

    def local_corpus_size(self) -> int:
        # this is only the local corpus size
        tot = 0
        for file in os.listdir(self.path):
            tot += (Path(self.path) / file).lstat().st_size
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

    def hash_new_corpus(self):
        for file in os.listdir(self.path):
            # If the file is already a hash, skip it
            if len(file) == 64 and all(c in "0123456789abcdef" for c in file):
                continue
            path = os.path.join(self.path, file)
            try:
                with open(path, "rb") as f:
                    hash_filename = hash_file(f)
                os.rename(path, os.path.join(self.path, hash_filename))
            except Exception:
                # Likely already hashed by another pod
                continue

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

    def sync_from_remote(self):
        os.makedirs(self.remote_path, exist_ok=True)
        self._do_sync(self.remote_path, self.path)

    def list_local_corpus(self) -> list[str]:
        return [os.path.join(self.path, f) for f in os.listdir(self.path)]

    def list_corpus(self) -> list[str]:
        return [os.path.join(self.path, f) for f in os.listdir(self.path)]


class CrashDir:
    def __init__(self, wdir: str, task_id: str, harness_name: str, count_limit: int | None = None):
        self.wdir = wdir
        self.crash_dir = os.path.join(task_id, f"{CRASH_DIR_NAME}_{harness_name}")
        self.count_limit = count_limit

    def input_dir_for_token(self, token: str) -> InputDir:
        return InputDir(self.wdir, os.path.join(self.crash_dir, urllib.parse.quote(token)))

    def copy_file(self, src_file: str, crash_token: str) -> str:
        idir = self.input_dir_for_token(crash_token)
        first_elem = next(iter(idir.list_corpus()), None)
        if (
            (self.count_limit is not None)
            and (idir.local_corpus_count() > self.count_limit)
            and (first_elem is not None)
        ):
            return first_elem
        return idir.copy_file(src_file)

    def sync_token(self, token: str):
        idir = self.input_dir_for_token(token)
        idir.sync_from_remote()

    def list_crashes_for_token(self, token: str, get_remote: bool = True) -> list[str]:
        idir = self.input_dir_for_token(token)
        if get_remote:
            idir.sync_from_remote()
        return idir.list_corpus()


class Corpus(InputDir):
    def __init__(self, wdir: str, task_id: str, harness_name: str):
        self.task_id = task_id
        self.harness_name = harness_name
        self.corpus_dir = os.path.join(task_id, f"{CORPUS_DIR_NAME}_{harness_name}")
        super().__init__(wdir, self.corpus_dir)

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

    @staticmethod
    def locally_available(wdir: str) -> List["Corpus"]:
        """
        Returns a list of Corpus objects for all locally available corpora.

        Args:
            wdir (str): The directory containing the corpora.
        Returns:
            List[Corpus]: A list of Corpus objects for all locally available corpora.
        """
        corpus_re = re.compile(f"{CORPUS_DIR_NAME}_.*")
        available_corpus = []
        for file in os.listdir(wdir):
            # task_id is a uuid
            try:
                uuid.UUID(file)
            except ValueError:
                continue
            maybe_task = os.path.join(wdir, file)
            task_id = file
            for file in os.listdir(maybe_task):
                if corpus_re.match(file):
                    harness_name = file.lstrip(CORPUS_DIR_NAME + "_")
                    available_corpus.append(Corpus(wdir, task_id, harness_name))
        return available_corpus
