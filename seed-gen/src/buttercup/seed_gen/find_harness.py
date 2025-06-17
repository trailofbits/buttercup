"""Module for finding libfuzzer and jazzer harnesses in source code."""

import logging
import subprocess
from pathlib import Path

import rapidfuzz

from buttercup.common.project_yaml import Language, ProjectYaml
from buttercup.program_model.codequery import CONTAINER_SRC_DIR, CodeQuery

logger = logging.getLogger(__name__)


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


def get_harness_source_candidates(
    codequery: CodeQuery, project_name: str, harness_name: str
) -> list[Path]:
    """Get the list of candidate source files for a harness, in descending order
    of fuzzy similarity to the harness name.
    """
    project_yaml = ProjectYaml(codequery.challenge, project_name)
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
