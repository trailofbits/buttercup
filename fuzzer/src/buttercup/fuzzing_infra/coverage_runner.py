import argparse
import json
import logging
import subprocess
from dataclasses import dataclass
from typing import Any, NamedTuple, cast

import cxxfilt
from bs4 import BeautifulSoup, Tag

from buttercup.common.challenge_task import ChallengeTask
from buttercup.common.project_yaml import Language, ProjectYaml

logger = logging.getLogger(__name__)


# Type definitions for LLVM coverage data structures
class RegionCoords(NamedTuple):
    """Source location coordinates for a region (line_start, col_start, line_end, col_end)."""

    line_start: int
    col_start: int
    line_end: int
    col_end: int


class ExpansionKey(NamedTuple):
    """Key for expansion map: filename + region coordinates."""

    filename: str
    line_start: int
    col_start: int
    line_end: int
    col_end: int

    @classmethod
    def from_coords(cls, filename: str, coords: RegionCoords) -> "ExpansionKey":
        return cls(filename, coords.line_start, coords.col_start, coords.line_end, coords.col_end)


class CachedExpansionLines(NamedTuple):
    """Cached result of processing an expansion's lines."""

    total_lines: frozenset[int]
    covered_lines: frozenset[int]


# Type aliases for complex data structures
ExpansionMap = dict[ExpansionKey, list[Any]]
CoordToFilenames = dict[RegionCoords, list[str]]
ExpansionLinesCache = dict[ExpansionKey, CachedExpansionLines]

# LLVM Coverage Region Kind constants (from CoverageMapping.h)
# See: https://llvm.org/doxygen/structllvm_1_1coverage_1_1CounterMappingRegion.html
REGION_KIND_CODE = 0  # Associates code with an execution counter
REGION_KIND_EXPANSION = 1  # Macro instantiation or #include file
REGION_KIND_SKIPPED = 2  # Preprocessor-skipped code (#ifdef)
REGION_KIND_GAP = 3  # Formatting gaps (whitespace between regions)
REGION_KIND_BRANCH = 4  # Branch condition with true/false counters
REGION_KIND_MCDC_DECISION = 5  # MC/DC top-level boolean expression
REGION_KIND_MCDC_BRANCH = 6  # MC/DC branch with control flow IDs


@dataclass
class CoveredFunction:
    """Coverage metrics for a single function."""

    names: str
    total_lines: int
    covered_lines: int
    function_paths: list[str]


class CoverageRunner:
    def __init__(self, tool: ChallengeTask, llvm_cov_path: str):
        self.tool = tool
        self.llvm_cov_path = llvm_cov_path
        self.language = ProjectYaml(self.tool, self.tool.project_name).unified_language

    def _process_function_coverage(self, coverage_data: dict[str, Any]) -> list[CoveredFunction]:
        """Process the LLVM coverage data to extract function-level line coverage.

        Returns a list of CoveredFunction objects with line coverage metrics.

        This method filters coverage data by region kind to provide accurate metrics:
        - Only CodeRegions (kind=0) are counted as reachable lines
        - ExpansionRegions (kind=1) are counted as 1 reachable line if they expand to CodeRegions
        - SkippedRegions, GapRegions, BranchRegions, and MCDC regions are excluded

        Reference for coverage data format:
            https://github.com/llvm/llvm-project/blob/main/llvm/tools/llvm-cov/CoverageExporterJson.cpp
        """
        function_coverage: list[CoveredFunction] = []

        if "data" not in coverage_data:
            logger.error("Invalid coverage data format: 'data' field missing")
            return function_coverage

        for export_obj in coverage_data["data"]:
            if "functions" not in export_obj:
                continue

            # Build expansion coverage map and coordinate index for fast lookups
            expansion_map, coord_to_filenames = self._build_expansion_coverage_map(export_obj)
            # Cache for computed expansion lines to avoid recomputing the same macro across functions
            expansion_lines_cache: ExpansionLinesCache = {}
            num_functions = len(export_obj.get("functions", []))
            logger.info(f"Processing {num_functions} functions with {len(expansion_map)} expansion entries")

            for func_idx, function in enumerate(export_obj["functions"]):
                if "name" not in function or "regions" not in function:
                    continue
                if func_idx % 100 == 0:
                    logger.info(
                        f"Processing function {func_idx}/{num_functions}: {function.get('name', 'unknown')[:50]}"
                    )

                # Demangle the function name if necessary, depending on the language.
                name = function["name"]
                if self.language in {Language.CPP, Language.C}:
                    try:
                        demangled_name: str = cxxfilt.demangle(name)
                        if demangled_name != "":
                            name = demangled_name
                    except Exception as e:
                        logger.debug(f"Failed to demangle name {name}: {e!r}")

                regions = function["regions"]
                filenames = function.get("filenames", [])

                covered_lines: set[int] = set()
                total_lines: set[int] = set()

                self._process_regions(
                    regions,
                    total_lines,
                    covered_lines,
                    expansion_map,
                    coord_to_filenames,
                    filenames,
                    expansion_lines_cache,
                )

                total_line_count = len(total_lines)
                covered_line_count = len(covered_lines)
                if covered_line_count > 0:
                    function_coverage.append(
                        CoveredFunction(
                            name,
                            total_line_count,
                            covered_line_count,
                            function.get("filenames", []),
                        ),
                    )

        return function_coverage

    def _build_expansion_coverage_map(self, export_obj: dict[str, Any]) -> tuple[ExpansionMap, CoordToFilenames]:
        """Build a map of macro expansion target_regions from file-level expansions.

        Returns:
            expansion_map: Maps ExpansionKey to the list of target_regions for that expansion.
            coord_to_filenames: Maps RegionCoords to list of filenames with expansions at those
                coordinates. This enables O(1) lookup instead of iterating through all filenames.

        The filename is included in the expansion_map key to prevent cross-file collisions
        when different files have macros at the same line/column coordinates.
        """
        expansion_map: ExpansionMap = {}
        coord_to_filenames: CoordToFilenames = {}

        for file_obj in export_obj.get("files", []):
            filename = file_obj.get("filename", "")
            for expansion in file_obj.get("expansions", []):
                source_region = expansion.get("source_region", [])
                if len(source_region) < 4:
                    continue

                coords = RegionCoords(source_region[0], source_region[1], source_region[2], source_region[3])
                key = ExpansionKey.from_coords(filename, coords)
                target_regions = expansion.get("target_regions", [])
                expansion_map[key] = target_regions

                # Build secondary index for fast coordinate lookup
                if coords not in coord_to_filenames:
                    coord_to_filenames[coords] = []
                coord_to_filenames[coords].append(filename)

        return expansion_map, coord_to_filenames

    def _process_expansion_lines(
        self,
        target_regions: list[Any],
        total_lines: set[int],
        covered_lines: set[int],
        expansion_map: ExpansionMap,
        coord_to_filenames: CoordToFilenames,
        filenames_set: set[str],
        expansion_lines_cache: ExpansionLinesCache,
        visited: set[ExpansionKey] | None = None,
    ) -> None:
        """Recursively process macro expansion target_regions to extract line coverage.

        For each region in target_regions:
        - CodeRegion: add all lines to total_lines/covered_lines
        - ExpansionRegion: recursively look up and process its target_regions

        Args:
            target_regions: The regions from a macro expansion to process
            total_lines: Set to accumulate all reachable lines
            covered_lines: Set to accumulate lines with execution_count > 0
            expansion_map: Map from ExpansionKey to target_regions
            coord_to_filenames: Map from RegionCoords to filenames with expansions at those coords
            filenames_set: Set of filenames for O(1) membership check
            expansion_lines_cache: Cache for computed expansion lines
            visited: Set of already-visited expansion keys to prevent infinite loops
        """
        if visited is None:
            visited = set()

        for region in target_regions:
            if len(region) < 5:
                continue

            region_kind = region[7] if len(region) > 7 else REGION_KIND_CODE

            if region_kind == REGION_KIND_CODE:
                self._add_region_lines(region, total_lines, covered_lines)
            elif region_kind == REGION_KIND_EXPANSION:
                # Look up nested expansion using coordinate index for O(1) lookup
                coords = RegionCoords(region[0], region[1], region[2], region[3])
                expansion_filenames = coord_to_filenames.get(coords, [])
                for fn in expansion_filenames:
                    if fn in filenames_set:
                        key = ExpansionKey.from_coords(fn, coords)
                        if key in expansion_map and key not in visited:
                            visited.add(key)
                            # Check cache for nested expansion
                            if key in expansion_lines_cache:
                                cached = expansion_lines_cache[key]
                                total_lines.update(cached.total_lines)
                                covered_lines.update(cached.covered_lines)
                            else:
                                # Compute and cache nested expansion lines
                                nested_total: set[int] = set()
                                nested_covered: set[int] = set()
                                self._process_expansion_lines(
                                    expansion_map[key],
                                    nested_total,
                                    nested_covered,
                                    expansion_map,
                                    coord_to_filenames,
                                    filenames_set,
                                    expansion_lines_cache,
                                    visited,
                                )
                                expansion_lines_cache[key] = CachedExpansionLines(
                                    frozenset(nested_total),
                                    frozenset(nested_covered),
                                )
                                total_lines.update(nested_total)
                                covered_lines.update(nested_covered)
                            break

    def _process_regions(
        self,
        regions: list[Any],
        total_lines: set[int],
        covered_lines: set[int],
        expansion_map: ExpansionMap,
        coord_to_filenames: CoordToFilenames,
        filenames: list[str],
        expansion_lines_cache: ExpansionLinesCache,
    ) -> None:
        """Process regions, filtering by region kind for accurate coverage.

        Only CodeRegions (kind=0) are counted as reachable lines.
        ExpansionRegions (kind=1) are processed recursively to count all lines from the
        expanded macro body (not just the call site).
        All other region kinds are skipped (SkippedRegion, GapRegion, BranchRegion, MCDC).

        Args:
            expansion_map: Map from ExpansionKey to target_regions.
            coord_to_filenames: Map from RegionCoords to filenames with expansions at those coords.
            filenames: List of filenames associated with the function.
            expansion_lines_cache: Cache for computed expansion lines to avoid recomputation.
        """
        filenames_set = set(filenames) if filenames else set()

        for region in regions:
            # Region format: [lineStart, colStart, lineEnd, colEnd, executionCount, fileID, expandedFileID, kind]
            if len(region) < 5:
                continue

            # Get region kind (index 7), default to CodeRegion for backwards compatibility
            # with older LLVM versions that may not include the kind field
            region_kind = region[7] if len(region) > 7 else REGION_KIND_CODE

            if region_kind == REGION_KIND_CODE:
                # CodeRegion: count all lines as reachable
                self._add_region_lines(region, total_lines, covered_lines)

            elif region_kind == REGION_KIND_EXPANSION:
                # ExpansionRegion: recursively process all lines from the expanded macro
                # Use coordinate index for O(1) lookup instead of iterating filenames
                coords = RegionCoords(region[0], region[1], region[2], region[3])
                expansion_filenames = coord_to_filenames.get(coords, [])
                for fn in expansion_filenames:
                    if fn in filenames_set:
                        key = ExpansionKey.from_coords(fn, coords)
                        if key in expansion_map:
                            # Check cache first to avoid recomputing the same macro's lines
                            if key in expansion_lines_cache:
                                cached = expansion_lines_cache[key]
                                total_lines.update(cached.total_lines)
                                covered_lines.update(cached.covered_lines)
                            else:
                                # Compute lines and cache the result
                                expansion_total: set[int] = set()
                                expansion_covered: set[int] = set()
                                self._process_expansion_lines(
                                    expansion_map[key],
                                    expansion_total,
                                    expansion_covered,
                                    expansion_map,
                                    coord_to_filenames,
                                    filenames_set,
                                    expansion_lines_cache,
                                )
                                expansion_lines_cache[key] = CachedExpansionLines(
                                    frozenset(expansion_total),
                                    frozenset(expansion_covered),
                                )
                                total_lines.update(expansion_total)
                                covered_lines.update(expansion_covered)
                            break

            # Skip other region types:
            # - REGION_KIND_SKIPPED: #ifdef'd out code, never compiled
            # - REGION_KIND_GAP: whitespace/formatting, not real code
            # - REGION_KIND_BRANCH: branch metadata, overlaps with CodeRegions
            # - REGION_KIND_MCDC_*: MC/DC metadata

    def _add_region_lines(
        self,
        region: list[Any],
        total_lines: set[int],
        covered_lines: set[int],
    ) -> None:
        """Add lines from a CodeRegion to the coverage sets."""
        line_start = region[0]
        line_end = region[2]
        execution_count = region[4]

        # Use set.update with range for O(n) bulk insertion instead of O(n) individual adds
        lines = range(line_start, line_end + 1)
        total_lines.update(lines)
        if execution_count > 0:
            covered_lines.update(lines)

    def run(self, harness_name: str, corpus_dir: str) -> list[CoveredFunction] | None:
        lang = ProjectYaml(self.tool, self.tool.project_name).unified_language
        if lang in [Language.C, Language.CPP]:
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
        assert build_dir is not None, "build_dir is required for java coverage"
        jacoco_path = build_dir / "dumps" / f"{harness_name}.xml"
        if not jacoco_path.exists():
            logger.error(
                f"Failed to find jacoco file for {harness_name} | {corpus_dir} | {self.tool.project_name} | in {jacoco_path}",  # noqa: E501
            )
            return None

        # parse the jacoco file
        with open(jacoco_path) as f:
            soup = BeautifulSoup(f, "xml")
            covered_functions = []
            for target_class in soup.find_all("class"):
                target_class = cast("Tag", target_class)
                file_paths = []
                source_file_name = target_class.get("sourcefilename")
                if source_file_name is not None:
                    file_paths.append(source_file_name)

                for method in target_class.find_all("method"):
                    method = cast("Tag", method)
                    method_name = method.get("name")
                    if method_name is None:
                        continue
                    method_name = str(method_name)
                    for ctr in method.find_all("counter"):
                        ctr = cast("Tag", ctr)
                        if ctr.get("type") == "LINE":
                            covered_attr = ctr.get("covered")
                            missed_attr = ctr.get("missed")
                            if covered_attr is None or missed_attr is None:
                                continue
                            covered_lines = int(str(covered_attr))
                            total_lines = int(str(missed_attr)) + int(str(covered_attr))
                            if covered_lines > 0:
                                covered_functions.append(
                                    CoveredFunction(
                                        method_name,
                                        total_lines,
                                        covered_lines,
                                        [str(f) for f in file_paths],
                                    ),
                                )

        return covered_functions

    def run_c(self, harness_name: str, corpus_dir: str) -> list[CoveredFunction] | None:
        ret = self.tool.run_coverage(harness_name, corpus_dir)
        if not ret:
            logger.error(f"Failed to run coverage for {harness_name} | {corpus_dir} | {self.tool.project_name}")
            return None

        # after we run coverage we need to find the profdata report then convert it to json, and load it
        package_path = self.tool.get_build_dir()
        assert package_path is not None, "build_dir is required for coverage"
        profdata_path = package_path / "dumps" / "merged.profdata"
        if not profdata_path.exists():
            logger.error(
                f"Failed to find profdata for {harness_name} | {corpus_dir} | {self.tool.project_name} | in {profdata_path}",  # noqa: E501
            )
            return None

        # convert profdata to json
        coverage_file = package_path / "dumps" / "coverage.json"
        harness_path = package_path / harness_name
        args = [self.llvm_cov_path, "export", "-format=text", f"--instr-profile={profdata_path}", harness_path]
        ret = subprocess.run(args, check=False, stdout=subprocess.PIPE)
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

        return self._process_function_coverage(coverage)


def main() -> None:
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
