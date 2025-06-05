from buttercup.common.challenge_task import ChallengeTask
import argparse
import subprocess
import json
import logging
from dataclasses import dataclass
from buttercup.common.project_yaml import ProjectYaml, Language
from bs4 import BeautifulSoup
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class CoveredFunction:
    names: str
    total_lines: int
    covered_lines: int
    function_paths: list[str]


class CoverageRunner:
    def __init__(self, tool: ChallengeTask, llvm_cov_path: str):
        self.tool = tool
        self.llvm_cov_path = llvm_cov_path

    @staticmethod
    def _process_function_coverage(coverage_data: dict[str, Any]) -> list[CoveredFunction]:
        """
        Process the LLVM coverage data to extract function-level line coverage.

        Returns a dictionary mapping function names to their line coverage metrics.

        Reference for coverage data format:
            https://github.com/llvm/llvm-project/blob/main/llvm/tools/llvm-cov/CoverageExporterJson.cpp
        """
        function_coverage = []

        if "data" not in coverage_data:
            logger.error("Invalid coverage data format: 'data' field missing")
            return function_coverage

        for export_obj in coverage_data["data"]:
            if "functions" not in export_obj:
                continue

            for function in export_obj["functions"]:
                if "name" not in function or "regions" not in function:
                    continue

                name = function["name"]
                regions = function["regions"]

                covered_lines = set()
                total_lines = set()

                for region in regions:
                    # Region format: [lineStart, colStart, lineEnd, colEnd, executionCount, ...]
                    if len(region) < 5:
                        continue

                    line_start = region[0]
                    line_end = region[2]
                    execution_count = region[4]

                    for line in range(line_start, line_end + 1):
                        total_lines.add(line)

                        if execution_count > 0:
                            covered_lines.add(line)

                total_line_count = len(total_lines)
                covered_line_count = len(covered_lines)
                if covered_line_count > 0:
                    function_coverage.append(
                        CoveredFunction(
                            name,
                            total_line_count,
                            covered_line_count,
                            function.get("filenames", []),
                        )
                    )

        return function_coverage

    def run(self, harness_name: str, corpus_dir: str) -> list[CoveredFunction] | None:
        lang = ProjectYaml(self.tool, self.tool.project_name).unified_language
        if lang == Language.C:
            ret = self.run_c(harness_name, corpus_dir)
        elif lang == Language.JAVA:
            ret = self.run_java(harness_name, corpus_dir)
        else:
            logger.error(f"Unsupported language: {lang}")
            return None

        return ret

    def run_java(self, harness_name: str, corpus_dir: str) -> list[CoveredFunction] | None:
        ret = self.tool.run_coverage(harness_name, corpus_dir)
        if not ret:
            logger.error(f"Failed to run coverage for {harness_name} | {corpus_dir} | {self.tool.project_name}")
            return None

        build_dir = self.tool.get_build_dir()
        jacoco_path = build_dir / "dumps" / f"{harness_name}.xml"
        if not jacoco_path.exists():
            logger.error(
                f"Failed to find jacoco file for {harness_name} | {corpus_dir} | {self.tool.project_name} | in {jacoco_path}"
            )
            return None

        # parse the jacoco file
        with open(jacoco_path, "r") as f:
            soup = BeautifulSoup(f, "xml")
            covered_functions = []
            for target_class in soup.find_all("class"):
                file_paths = []
                source_file_name = target_class.get("sourcefilename")
                if source_file_name is not None:
                    file_paths.append(source_file_name)

                for method in target_class.find_all("method"):
                    method_name = method.get("name")
                    for ctr in method.find_all("counter"):
                        if ctr.get("type") == "LINE":
                            covered_lines = int(ctr.get("covered"))
                            total_lines = int(ctr.get("missed")) + int(ctr.get("covered"))
                            if covered_lines > 0:
                                covered_functions.append(
                                    CoveredFunction(method_name, total_lines, covered_lines, file_paths)
                                )

        return covered_functions

    def run_c(self, harness_name: str, corpus_dir: str) -> list[CoveredFunction] | None:
        ret = self.tool.run_coverage(harness_name, corpus_dir)
        if not ret:
            logger.error(f"Failed to run coverage for {harness_name} | {corpus_dir} | {self.tool.project_name}")
            return None

        # after we run coverage we need to find the profdata report then convert it to json, and load it
        package_path = self.tool.get_build_dir()
        profdata_path = package_path / "dumps" / "merged.profdata"
        if not profdata_path.exists():
            logger.error(
                f"Failed to find profdata for {harness_name} | {corpus_dir} | {self.tool.project_name} | in {profdata_path}"
            )
            return None

        # convert profdata to json
        coverage_file = package_path / "dumps" / "coverage.json"
        harness_path = package_path / harness_name
        args = [self.llvm_cov_path, "export", "-format=text", f"--instr-profile={profdata_path}", harness_path]
        ret = subprocess.run(args, stdout=subprocess.PIPE)
        if ret.returncode != 0:
            logger.error(
                "Failed to convert profdata to json for %s | %s | %s | in %s (return code: %s)",
                harness_name,
                corpus_dir,
                self.tool.project_name,
                coverage_file,
                ret.returncode,
            )
            return None

        # load the coverage file
        coverage = ret.stdout.decode("utf-8")
        coverage = json.loads(coverage)
        logger.info(f"Coverage for {harness_name} | {corpus_dir} | {self.tool.project_name} | in {len(coverage)}")

        return CoverageRunner._process_function_coverage(coverage)


def main():
    prsr = argparse.ArgumentParser("Coverage runner")
    prsr.add_argument("--allow-pull", action="store_true", default=False)
    prsr.add_argument("--base-image-url", default="gcr.io/oss-fuzz")
    prsr.add_argument("--python", default="python")
    prsr.add_argument("--task-dir", required=True)
    prsr.add_argument("--harness-name", required=True)
    prsr.add_argument("--corpus-dir", required=True)
    prsr.add_argument("--package-name", required=True)
    prsr.add_argument("--llvm-cov-path", default="llvm-cov")
    prsr.add_argument("--work-dir", required=True)
    args = prsr.parse_args()

    tool = ChallengeTask(read_only_task_dir=args.task_dir)
    with tool.get_rw_copy(work_dir=args.work_dir, delete=False) as local_tool:
        runner = CoverageRunner(local_tool, args.llvm_cov_path)
        print(runner.run(args.harness_name, args.corpus_dir))


if __name__ == "__main__":
    main()
