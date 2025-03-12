import subprocess
import logging
import os
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class KytheConf:
    kythe_dir: str


class KytheTool:
    def __init__(self, conf: KytheConf):
        self.conf = conf

    def merge_kythe_output(self, input_dir: str, output_kzip: str):
        logger.debug(f"Merging kythe output from {input_dir} to {output_kzip}")
        merge_path = os.path.join(self.conf.kythe_dir, "tools/kzip")

        total = []
        for fl in os.listdir(input_dir):
            if fl.endswith(".kzip"):
                total.append(os.path.join(input_dir, fl))

        command = [merge_path, "merge", "--output", output_kzip] + total
        subprocess.run(command, check=True)
        logger.debug(f"Finished merging kythe output from {input_dir} to {output_kzip}")
        return True

    def cxx_index(self, input_kzip: str, output_bin: str):
        logger.debug(f"Indexing kythe output from {input_kzip} to {output_bin}")
        indexer_path = os.path.join(self.conf.kythe_dir, "indexers/cxx_indexer")
        command = [indexer_path, input_kzip, "-o", output_bin]
        subprocess.run(command, check=True)
        logger.debug(
            f"Finished indexing kythe output from {input_kzip} to {output_bin}"
        )
        return True
