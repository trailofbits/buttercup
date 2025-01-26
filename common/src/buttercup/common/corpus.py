from buttercup.common.constants import CORPUS_DIR_NAME
import os 
import hashlib
import shutil

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
                digest = hashlib.file_digest(f, "sha256")
                digest_hex = digest.hexdigest()
                shutil.copy(os.path.join(src_dir, file), os.path.join(self.corpus_dir, digest_hex))
