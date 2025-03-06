"""Module for finding libfuzzer and jazzer harnesses in source code."""

import logging
import subprocess
from pathlib import Path

from buttercup.common.challenge_task import ChallengeTask
from buttercup.common.project_yaml import ProjectYaml

logger = logging.getLogger(__name__)


def _find_source_files(
    task: ChallengeTask, file_patterns: list[str], grep_pattern: str
) -> list[Path]:
    """Find source files that match file patterns and contain a search string

    Searches both the source path and the oss-fuzz project path.
    """
    source_path = task.get_source_path()
    oss_fuzz_project_path = task.get_oss_fuzz_path() / "projects" / task.project_name
    if not source_path:
        logger.error("Source path does not exist: %s", source_path)
        return []
    if not oss_fuzz_project_path:
        logger.error("OSS-Fuzz project path does not exist: %s", oss_fuzz_project_path)
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
            str(source_path),
            str(oss_fuzz_project_path),
        ]

        result = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=60)

        harness_files = []
        for line in result.stdout.splitlines():
            path = Path(line)
            if path.exists():
                harness_files.append(path)

        return harness_files

    except subprocess.CalledProcessError as e:
        if e.returncode == 1:  # No matches found
            return []
        logger.warning(f"Error running ripgrep command: {e}")
        return []
    except Exception as e:
        logger.warning(f"Unexpected error finding harnesses: {e}")
        return []


def find_libfuzzer_harnesses(task: ChallengeTask) -> list[Path]:
    """Find libfuzzer harnesses in the source directory.

    Heuristic: C/C++ file that defines the LLVMFuzzerTestOneInput function.
    """

    grep_pattern = r"int\s+LLVMFuzzerTestOneInput\s*\([^)]*\)"

    return _find_source_files(
        task,
        file_patterns=["*.c", "*.cc", "*.cpp", "*.cxx"],
        grep_pattern=grep_pattern,
    )


def find_jazzer_harnesses(task: ChallengeTask) -> list[Path]:
    """Find Jazzer harnesses in the source directory.

    Heuristic: Java file that defines the fuzzerTestOneInput method.
    """
    # Match: void fuzzerTestOneInput(...) with optional newlines
    grep_pattern = r"void\s+fuzzerTestOneInput\s*\([^)]*\)"

    return _find_source_files(
        task,
        file_patterns=["*.java"],
        grep_pattern=grep_pattern,
    )


def get_harness_source_candidates(
    task: ChallengeTask, project_name: str, harness_name: str
) -> list[Path]:
    """Get the list of candidate source files for a harness.

    If multiple harnesses are found, attempts to filter to ones where the harness name
    appears in the filename.
    """
    project_yaml = ProjectYaml(task, project_name)
    language = project_yaml.language
    harnesses = []
    if language == "jvm":
        harnesses = find_jazzer_harnesses(task)
    else:
        harnesses = find_libfuzzer_harnesses(task)
    harnesses.sort(key=lambda x: x.name)

    # Filter harnesses by name if multiple found
    matching_harnesses = [h for h in harnesses if harness_name in h.name]
    if not matching_harnesses:
        matching_harnesses = [h for h in harnesses if harness_name.lower() in h.name.lower()]

    if not matching_harnesses:
        return harnesses

    return matching_harnesses
