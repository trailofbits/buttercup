"""Module for finding libfuzzer and jazzer harnesses in source code."""

import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path

import rapidfuzz
from pydantic import BaseModel
from redis import Redis

from buttercup.common.maps import CoverageMap
from buttercup.common.project_yaml import Language, ProjectYaml
from buttercup.program_model.codequery import CONTAINER_SRC_DIR, CodeQuery

logger = logging.getLogger(__name__)


class HarnessInfo(BaseModel):
    """Harness info"""

    file_path: Path
    code: str
    harness_name: str

    def __str__(self) -> str:
        return f"""<harness>
<harness_binary_name>{self.harness_name}</harness_binary_name>
<source_file_path>{self.file_path}</source_file_path>
<code>
{self.code}
</code>
</harness>
"""


@dataclass
class HarnessSourceCacheKey:
    task_id: str
    harness_name: str

    def __hash__(self) -> int:
        return hash((self.task_id, self.harness_name))

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, HarnessSourceCacheKey):
            return False
        return self.task_id == other.task_id and self.harness_name == other.harness_name


_harness_source_cache: dict[HarnessSourceCacheKey, HarnessInfo] = {}


def _exclude_common_harnesses(harness_files: list[Path], container_src_dir: Path) -> list[Path]:
    # Filter out prebuilt harnesses
    exclude_list = [
        "src/aflplusplus/",
        "src/fuzztest/centipede/",
        "src/honggfuzz/",
        "src/libfuzzer/",
    ]

    def is_in_exclude_list(path: Path) -> bool:
        return any(path.as_posix().startswith(exclude) for exclude in exclude_list)

    return [
        path
        for path in harness_files
        if not is_in_exclude_list(path.relative_to(container_src_dir))
    ]


def _find_source_files(
    codequery: CodeQuery, file_patterns: list[str], grep_pattern: str
) -> list[Path]:
    """Find source files that match file patterns and contain a search string

    Searches both the source path and the oss-fuzz project path.
    """
    container_src_dir = codequery.challenge.task_dir / CONTAINER_SRC_DIR
    if not container_src_dir.exists():
        logger.error("Container source path does not exist: %s", container_src_dir)
        return []

    globs = []
    for pattern in file_patterns:
        globs.extend(["--glob", pattern])

    try:
        cmd = [
            "rg",
            "--files-with-matches",
            *globs,
            "--multiline",
            grep_pattern,
            str(container_src_dir),
        ]

        result = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=60)
    except subprocess.CalledProcessError as e:
        if e.returncode == 1:  # No matches found
            return []
        logger.warning(f"Error running ripgrep command: {e}")
        return []
    except Exception as e:
        logger.warning(f"Unexpected error finding harnesses: {e}")
        return []

    harness_files = []
    for line in result.stdout.splitlines():
        path = Path(line)
        if path.exists():
            harness_files.append(path)

    return _exclude_common_harnesses(harness_files, container_src_dir)


def find_libfuzzer_harnesses(codequery: CodeQuery) -> list[Path]:
    """Find libfuzzer harnesses in the source directory.

    Heuristic: C/C++ file that defines the LLVMFuzzerTestOneInput function.
    """

    grep_pattern = r"int\s+LLVMFuzzerTestOneInput\s*\([^)]*\)"

    return _find_source_files(
        codequery,
        file_patterns=["*.c", "*.cc", "*.cpp", "*.cxx"],
        grep_pattern=grep_pattern,
    )


def find_jazzer_harnesses(codequery: CodeQuery) -> list[Path]:
    """Find Jazzer harnesses in the source directory.

    Heuristic: Java file that defines the fuzzerTestOneInput method.
    """
    # Match: void fuzzerTestOneInput(...) with optional newlines
    grep_pattern = r"void\s+fuzzerTestOneInput\s*\([^)]*\)"

    return _find_source_files(
        codequery,
        file_patterns=["*.java"],
        grep_pattern=grep_pattern,
    )


def _rebase_path(task_dir: Path, path: Path) -> Path:
    container_src_dir = task_dir / CONTAINER_SRC_DIR
    try:
        res = path.relative_to(container_src_dir)
        return Path("/", *res.parts)
    except ValueError:
        return path.absolute()


def get_harness_source_candidates(codequery: CodeQuery, harness_name: str) -> list[Path]:
    """Get the list of candidate source files for a harness, in descending order
    of fuzzy similarity to the harness name.
    """
    project_yaml = ProjectYaml(codequery.challenge, codequery.challenge.project_name)
    language = project_yaml.unified_language

    harnesses = []
    if language == Language.JAVA:
        harnesses = find_jazzer_harnesses(codequery)
    else:
        harnesses = find_libfuzzer_harnesses(codequery)

    # Sort harnesses by fuzzy similarity to harness_name
    harnesses.sort(
        key=lambda x: rapidfuzz.fuzz.ratio(x.name.lower(), harness_name.lower()),
        reverse=True,
    )

    return harnesses


def get_harness_source(
    redis: Redis | None, codequery: CodeQuery, harness_name: str
) -> HarnessInfo | None:
    task_id = codequery.challenge.task_meta.task_id
    logger.info("Getting harness source for %s | %s", task_id, harness_name)
    key = HarnessSourceCacheKey(
        task_id=task_id,
        harness_name=harness_name,
    )
    if key in _harness_source_cache:
        logger.info(
            "Found harness source for %s | %s in cache",
            task_id,
            harness_name,
        )
        return _harness_source_cache[key]

    harnesses = get_harness_source_candidates(codequery, harness_name)
    if len(harnesses) == 0:
        logger.error("No harness found for %s | %s", task_id, harness_name)
        return None

    if len(harnesses) == 1:
        logger.info("Found single harness for %s | %s: %s", task_id, harness_name, harnesses[0])
        harness_info = HarnessInfo(
            file_path=_rebase_path(codequery.challenge.task_dir, harnesses[0]),
            code=harnesses[0].read_text(),
            harness_name=harness_name,
        )
        return harness_info

    if redis is None:
        logger.warning(
            "No redis connection available, using first harness found: %s",
            harnesses[0],
        )
        function_coverages = []
    else:
        logger.info(
            "Multiple harnesses found for %s | %s, using coverage map to select the best one",
            task_id,
            harness_name,
        )
        coverage_map = CoverageMap(redis, harness_name, codequery.challenge.project_name, task_id)
        function_coverages = coverage_map.list_function_coverage()

    # Check if any of the harnesses found through get_harness_source_candidates
    # intersect with the covered functions
    for function_coverage in function_coverages:
        for harness_path in harnesses:
            rebased_harness_path = _rebase_path(codequery.challenge.task_dir, harness_path)
            if any(str(rebased_harness_path) == path for path in function_coverage.function_paths):
                harness_info = HarnessInfo(
                    file_path=rebased_harness_path,
                    code=harness_path.read_text(),
                    harness_name=harness_name,
                )
                _harness_source_cache[key] = harness_info
                logger.info(
                    "Harness source for %s | %s matched through coverage map: %s",
                    task_id,
                    harness_name,
                    harness_path,
                )
                return _harness_source_cache[key]

    # If we couldn't determine a better match or don't have coverage map, use the first one
    logger.warning(
        "Multiple harnesses found for %s | %s. "
        "Returning first one based on name similarity "
        "as coverage map could not be used: %s",
        task_id,
        harness_name,
        harnesses[0],
    )
    rebased_harness_path = _rebase_path(codequery.challenge.task_dir, harnesses[0])
    harness_info = HarnessInfo(
        file_path=rebased_harness_path,
        code=harnesses[0].read_text(),
        harness_name=harness_name,
    )
    return harness_info
