from buttercup.common.oss_fuzz_tool import OSSFuzzTool, Conf
import argparse
from pathlib import Path
import subprocess
import json
import logging

logger = logging.getLogger(__name__)


class CoverageRunner:
    def __init__(self, tool: OSSFuzzTool, llvm_cov_path: str):
        self.tool = tool
        self.llvm_cov_path = llvm_cov_path

    def run(self, harness_name: str, corpus_dir: str, package_name: str) -> dict | None:
        ret = self.tool.run_coverage(harness_name, corpus_dir, package_name)
        if not ret:
            logger.error(f"Failed to run coverage for {harness_name} | {corpus_dir} | {package_name}")
            return False

        # after we run coverage we need to find the profdata report then convert it to json, and load it
        package_path = Path(self.tool.oss_fuzz_path) / "build" / "out" / package_name
        profdata_path = package_path / "dumps" / "merged.profdata"
        if not profdata_path.exists():
            logger.error(
                f"Failed to find profdata for {harness_name} | {corpus_dir} | {package_name} | in {profdata_path}"
            )
            return False

        # convert profdata to json
        coverage_file = package_path / "dumps" / "coverage.json"
        harness_path = package_path / harness_name
        args = [self.llvm_cov_path, "export", "-format=text", f"--instr-profile={profdata_path}", harness_path]
        ret = subprocess.run(args, stdout=subprocess.PIPE)
        if ret.returncode != 0:
            logger.error(
                f"Failed to convert profdata to json for {harness_name} | {corpus_dir} | {package_name} | in {coverage_file}"
            )
            return False

        # load the coverage file
        coverage = ret.stdout.decode("utf-8")
        coverage = json.loads(coverage)
        logging.info(f"Coverage for {harness_name} | {corpus_dir} | {package_name} | in {len(coverage)}")

        return coverage


def main():
    prsr = argparse.ArgumentParser("Coverage runner")
    prsr.add_argument("--allow-pull", action="store_true", default=False)
    prsr.add_argument("--base-image-url", default="gcr.io/oss-fuzz")
    prsr.add_argument("--python", default="python")
    prsr.add_argument("--oss-fuzz-dir", required=True)
    prsr.add_argument("--harness-name", required=True)
    prsr.add_argument("--corpus-dir", required=True)
    prsr.add_argument("--package-name", required=True)
    prsr.add_argument("--llvm-cov-path", default="llvm-cov")
    args = prsr.parse_args()

    tool = OSSFuzzTool(Conf(args.oss_fuzz_dir, args.python, args.allow_pull, args.base_image_url))
    runner = CoverageRunner(tool, args.llvm_cov_path)
    runner.run(args.harness_name, args.corpus_dir, args.package_name)


if __name__ == "__main__":
    main()
