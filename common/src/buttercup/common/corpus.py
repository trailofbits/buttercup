import re
from typing import List
import buttercup.common.node_local as node_local
from buttercup.common.constants import CORPUS_DIR_NAME, CRASH_DIR_NAME
import os
import hashlib
import shutil
import subprocess
import uuid


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

    def copy_corpus(self, src_dir: str):
        for file in os.listdir(src_dir):
            self.copy_file(os.path.join(src_dir, file))

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


class CrashDir(InputDir):
    def __init__(self, wdir: str, task_id: str, harness_name: str):
        self.crash_dir = os.path.join(task_id, f"{CRASH_DIR_NAME}_{harness_name}")
        super().__init__(wdir, self.crash_dir)


class Corpus(InputDir):
    def __init__(self, wdir: str, task_id: str, harness_name: str):
        self.corpus_dir = os.path.join(task_id, f"{CORPUS_DIR_NAME}_{harness_name}")
        super().__init__(wdir, self.corpus_dir)

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
