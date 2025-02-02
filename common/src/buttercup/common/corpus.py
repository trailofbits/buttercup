from buttercup.common.constants import CORPUS_DIR_NAME, CRASH_DIR_NAME
import os
import hashlib
import shutil


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
        os.makedirs(self.path, exist_ok=True)

    def basename(self) -> str:
        return os.path.basename(self.path)

    def copy_file(self, src_file: str):
        with open(src_file, "rb") as f:
            nm = hash_file(f)
            dst = os.path.join(self.path, nm)
            shutil.copy(src_file, dst)
            return dst

    def copy_corpus(self, src_dir: str):
        for file in os.listdir(src_dir):
            self.copy_file(os.path.join(src_dir, file))


class CrashDir(InputDir):
    def __init__(self, task_id: str, harness_name: str):
        self.crash_dir = os.path.join(task_id, f"{CRASH_DIR_NAME}_{harness_name}")
        super().__init__(self.crash_dir)


class Corpus(InputDir):
    def __init__(self, task_id: str, harness_name: str):
        self.corpus_dir = os.path.join(task_id, f"{CORPUS_DIR_NAME}_{harness_name}")
        super().__init__(self.corpus_dir)
