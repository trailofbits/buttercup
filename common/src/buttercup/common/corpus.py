from buttercup.common.constants import CORPUS_DIR_NAME
import os 
import hashlib
import shutil



def hash_file(fl):
    h = hashlib.new('sha256')
    bts = fl.read(100)
    while bts:
        h.update(bts)
        bts = fl.read(100)
    return h.hexdigest()

class Corpus:
    def __init__(self, harness_path: str):
        build_dir = os.path.dirname(harness_path)
        self.corpus_dir = os.path.join(build_dir, f"{CORPUS_DIR_NAME}_{os.path.basename(harness_path)}")
        os.makedirs(self.corpus_dir, exist_ok=True)

    def basename(self) -> str:
        return os.path.basename(self.corpus_dir)

    def copy_corpus(self, src_dir: str):
        for file in os.listdir(src_dir):
            with open(os.path.join(src_dir, file), "rb") as f:
                nm = hash_file(f)
                shutil.copy(os.path.join(src_dir, file), os.path.join(self.corpus_dir, nm))
