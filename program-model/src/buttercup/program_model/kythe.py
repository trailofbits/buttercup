import subprocess
import logging
import os
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class KytheConf:
    kythe_dir: Path


class KytheTool:
    def __init__(self, conf: KytheConf):
        self.conf = conf

    def merge_kythe_output(self, input_dir: Path, output_kzip: Path) -> bool:
        logger.debug(f"Merging kythe output from {input_dir} to {output_kzip}")
        merge_path = os.path.join(self.conf.kythe_dir, "tools/kzip")

        total = []
        for fl in os.listdir(input_dir):
            if fl.endswith(".kzip"):
                total.append(os.path.join(input_dir, fl))

        command = [merge_path, "merge", "--output", str(output_kzip)] + total
        subprocess.run(command, check=True)
        logger.debug(f"Finished merging kythe output from {input_dir} to {output_kzip}")
        return True

    def cxx_index(self, input_kzip: Path, output_bin: Path) -> bool:
        logger.debug(f"Indexing kythe output from {input_kzip} to {output_bin}")
        indexer_path = os.path.join(self.conf.kythe_dir, "indexers/cxx_indexer")
        command = [indexer_path, str(input_kzip), "-o", str(output_bin)]
        subprocess.run(command, check=True)
        logger.debug(
            f"Finished indexing kythe output from {input_kzip} to {output_bin}"
        )
        return True
