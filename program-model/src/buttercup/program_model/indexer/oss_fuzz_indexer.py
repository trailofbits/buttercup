import logging
import argparse
import uuid
import subprocess
from dataclasses import dataclass
from buttercup.common import oss_fuzz_tool
from buttercup.common.oss_fuzz_tool import OSSFuzzTool
from pathlib import Path
import os

logger = logging.getLogger(__name__)


@dataclass
class IndexTarget:
    oss_fuzz_dir: str
    package_name: str


@dataclass
class Conf:
    scriptdir: str
    url: str
    python: str
    allow_pull: bool
    base_image_url: str
    wdir: str


class Indexer:
    def __init__(self, conf: Conf):
        self.conf = conf

    def build_image(self, idx_target: IndexTarget):
        fzz_tool = OSSFuzzTool(
            oss_fuzz_tool.Conf(
                idx_target.oss_fuzz_dir,
                self.conf.python,
                self.conf.allow_pull,
                self.conf.base_image_url,
            )
        )
        base_image_name = fzz_tool.build_base_image(idx_target.package_name)
        print(base_image_name)
        if base_image_name is None:
            return None

        buildid = str(uuid.uuid4())
        emitted_image = f"kyther_indexer_image_{idx_target.package_name}_{buildid}"
        wdir = f"{self.conf.scriptdir}"
        command = [
            "docker",
            "build",
            "-t",
            emitted_image,
            "--build-arg",
            f"BASE_IMAGE={base_image_name}",
            ".",
        ]
        subprocess.run(command, check=True, cwd=wdir)
        # TODO(Ian): do more forgiving error handling
        return emitted_image

    def index_target(self, idx_target: IndexTarget):
        emitted_image = self.build_image(idx_target)
        if emitted_image is None:
            return None

        indexuid = str(uuid.uuid4())
        output_dir = f"{self.conf.wdir}/output_{indexuid}"
        os.makedirs(output_dir, exist_ok=True)
        # TODO(Ian): we need to figure out how to make ccwrapper.sh not break LD detection
        command = [
            "docker",
            "run",
            "-v",
            f"{output_dir}:/kythe_out",
            "-e",
            "LD=ld",
            "-e",
            "KYTHE_OUTPUT_DIRECTORY=/kythe_out",
            emitted_image,
            "compile",
        ]
        # TODO(Ian): we probably shouldnt keep around indexing images for disk space reasons
        subprocess.run(command, check=True)
        return output_dir


@dataclass
class KytheConf:
    kythe_dir: Path


@dataclass
class KytheTool:
    """Class for indexing and merging with Kythe"""
    def __init__(self, conf: KytheConf):
        self.conf = conf

    def merge_kythe_output(self, input_dir: Path, output_kzip: Path) -> None:
        merge_path = Path(self.conf.kythe_dir, "tools", "kzip")

        total = []
        for fl in os.listdir(input_dir):
            if fl.endswith(".kzip"):
                total.append(Path(input_dir, fl))

        command = [merge_path, "merge", "--output", output_kzip] + total
        subprocess.run(command, check=True)

    def cxx_index(self, input_kzip: Path, output_bin: Path) -> None:
        indexer_path = Path(self.conf.kythe_dir, "indexers", "cxx_indexer")
        command = [indexer_path, "-i", input_kzip, "-o", output_bin]
        subprocess.run(command, check=True)

    def java_index(self, input_kzip: Path, output_bin: Path) -> None:
        indexer_path = Path(self.conf.kythe_dir, "indexers", "java_indexer.jar")
        command = ["java", "-jar", indexer_path, "-i", input_kzip, "-o", output_bin]
        subprocess.run(command, check=True)


@dataclass
class ProgramIndexInput:
    """Input for the program indexer"""
    language: str
    target_dir: Path
    kythe_dir: Path
    output_dir: Path


@dataclass
class ProgramIndexOutput:
    """Output of the program indexer"""
    index_output: Path


@dataclass
class ProgramIndex:
    """Class for indexing a program"""
    output: ProgramIndexOutput

    def merge_kzip(self, indexer_input: ProgramIndexInput) -> None:
        """Merge kzip files"""
        output_id = str(uuid.uuid4())
        ktool = KytheTool(KytheConf(self.indexer_input.kythe_dir))

        self.output.merged_kzip = Path(self.indexer_input.wdir, f"kythe_output_merge_{output_id}.kzip")
        ktool.merge_kythe_output(self.output.output_dir, self.output.merged_kzip)

        self.output.cxx_bin = Path(self.indexer_input.wdir, f"kythe_output_cxx_{output_id}.bin")
        ktool.cxx_index(self.output.merged_kzip, self.output.cxx_bin)

        logger.info(f"Successfully merged index files into {self.output.merged_kzip}")

    # TODO(Evan): Implement C++ indexer
    def run_cxx_indexer(self, indexer_input: ProgramIndexInput) -> None:
        """Run the C++ indexer"""
        logger.error("C++ indexer not implemented")

    def run_c_indexer(self, indexer_input: ProgramIndexInput) -> None:
        """Run the C indexer"""
        logger.error("C indexer not implemented")

        # Run C indexer
        self.run_indexer(indexer_input)

    # TODO(Evan): Implement Java indexer
    def run_java_indexer(self, indexer_input: ProgramIndexInput) -> None:
        """Run the Java indexer"""
        logger.error("Java indexer not implemented")

    def get(self, indexer_input: ProgramIndexInput) -> ProgramIndexOutput | None:
        """Create index of a program"""

        # Run Kythe indexer
        kythe = KytheTool()
        kythe_input = KytheInput(
            indexer_input.language,
            indexer_input.target_dir,
            indexer_input.kythe_dir,
            indexer_input.output_dir,
        )
        if kythe.run_indexer(kythe_input) is None:
            return None
        return kythe.output

        if indexer_input.language == "c++":
            run_indexer = self.run_cxx_indexer
        elif indexer_input.language == "c":
            run_indexer = self.run_c_indexer
        elif indexer_input.language == "java":
            run_indexer = self.run_java_indexer

        # Run indexer
        if run_indexer(indexer_input) is None:
            return None

        # Merge kzip files
        self.merge_kzip(indexer_input)

        return self.output


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--language", required=True, type=str, choices=["c", "c++", "java"], help="Language of the program.")
    parser.add_argument("--target-dir", required=True, type=Path, help="Path to program directory to be indexed.")
    parser.add_argument("--indexer-dir", required=True, type=Path, help="Path to indexer tool directory.")
    parser.add_argument("--output-dir", required=True, type=Path, help="Path to indexer output directory.")

    prsr.add_argument("--scriptdir", required=True)
    prsr.add_argument("--url", required=True)
    prsr.add_argument("--python", default="python")
    prsr.add_argument("--allow_pull", action="store_true", default=False)
    prsr.add_argument("--base_image_url", required=True)
    prsr.add_argument("--oss_fuzz_dir", required=True)  # Get from tsk
    prsr.add_argument("--package_name", required=True)  # libpng (under projects/name)
    prsr.add_argument("--wdir", required=True)  # ./crs_scratch
    prsr.add_argument("--kythe_dir", required=True)
    args = parser.parse_args()

    indexer = ProgramIndex()
    indexer_input = ProgramIndexInput(
        language=args.language,
        target_dir=args.target_dir,
        indexer_dir=args.indexer_dir,
        output_dir=args.output_dir,
    )
    res = indexer.get(indexer_input)
    if res is None:
        logger.error(f"Failed to index program {args.package_name}")
    else:
        logger.info(f"Successfully indexed program {args.package_name}")
