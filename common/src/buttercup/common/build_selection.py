"""Utilities for selecting and resolving builds and binaries."""

import logging
import stat
from dataclasses import dataclass
from pathlib import Path

from buttercup.common.challenge_task import ChallengeTask
from buttercup.common.datastructures.msg_pb2 import BuildOutput, BuildType

logger = logging.getLogger(__name__)


@dataclass
class SelectedBuild:
    """Result of build selection for a specific harness"""

    build_output: BuildOutput
    task: ChallengeTask
    using_debug: bool = False
    binary_path: Path | None = None
    binary_name: str | None = None


def select_build_for_harness(
    build_outputs: list[BuildOutput],
    builds_cache: list[ChallengeTask],
    harness_name: str,
    prefer_sanitizer: str = "debug",
) -> SelectedBuild | None:
    """Select the best build that contains the specified harness.

    Selection priority:
    1. FUZZER_DEBUG build with harness (best for debugging - has debug symbols, no sanitizer)
    2. Preferred sanitizer build with harness (default: address)
    3. Any build with harness
    4. First build (fallback)

    Args:
        build_outputs: List of build outputs
        builds_cache: List of cached ChallengeTask instances (must match build_outputs)
        harness_name: Name of the harness binary to find
        prefer_sanitizer: Preferred sanitizer type (default: "address")

    Returns:
        SelectedBuild with build_output and task, or None if no builds available
    """
    if not builds_cache:
        return None

    # First, try to find FUZZER_DEBUG build (best for debugging)
    for build, cached_task in zip(build_outputs, builds_cache, strict=False):
        if build.build_type == BuildType.FUZZER_DEBUG:
            if _has_harness_in_build(cached_task, harness_name, is_debug_build=True):
                logger.info(f"Using FUZZER_DEBUG build with harness '{harness_name}' (task_id: {build.task_id})")
                binary_path, binary_name = resolve_actual_binary(
                    cached_task, harness_name, using_debug=True, is_fuzzer_debug=True
                )
                return SelectedBuild(
                    build_output=build,
                    task=cached_task,
                    using_debug=True,
                    binary_path=binary_path,
                    binary_name=binary_name,
                )

    # Second, try to find preferred sanitizer build with the harness
    for build, cached_task in zip(build_outputs, builds_cache, strict=False):
        if build.sanitizer == prefer_sanitizer:
            if _has_harness(cached_task, harness_name):
                logger.info(
                    f"Using {prefer_sanitizer} sanitizer build with harness '{harness_name}' (task_id: {build.task_id})"
                )
                using_debug = _has_debug_binary(cached_task, harness_name)
                binary_path, binary_name = resolve_actual_binary(cached_task, harness_name, using_debug)
                return SelectedBuild(
                    build_output=build,
                    task=cached_task,
                    using_debug=using_debug,
                    binary_path=binary_path,
                    binary_name=binary_name,
                )

    # If no preferred sanitizer build found, try any build with the harness
    for build, cached_task in zip(build_outputs, builds_cache, strict=False):
        if _has_harness(cached_task, harness_name):
            logger.info(
                f"Using build with harness '{harness_name}' (task_id: {build.task_id}, sanitizer: {build.sanitizer})"
            )
            using_debug = _has_debug_binary(cached_task, harness_name)
            binary_path, binary_name = resolve_actual_binary(cached_task, harness_name, using_debug)
            return SelectedBuild(
                build_output=build,
                task=cached_task,
                using_debug=using_debug,
                binary_path=binary_path,
                binary_name=binary_name,
            )

    # Fallback to first build
    logger.warning(
        f"No build found with harness '{harness_name}', using first build "
        f"(task_id: {build_outputs[0].task_id}). This may fail if harness doesn't exist."
    )
    # Try to resolve binary for fallback case too
    try:
        binary_path, binary_name = resolve_actual_binary(builds_cache[0], harness_name, False)
    except Exception as e:
        logger.warning(f"Failed to resolve binary for fallback build: {e}")
        binary_path, binary_name = Path(""), ""

    return SelectedBuild(
        build_output=build_outputs[0],
        task=builds_cache[0],
        using_debug=False,
        binary_path=binary_path,
        binary_name=binary_name,
    )


def _has_harness(task: ChallengeTask, harness_name: str) -> bool:
    """Check if task has the specified harness (debug or regular binary)"""
    build_dir = task.get_build_dir()
    if not build_dir or not build_dir.exists():
        return False

    debug_binary_path = task.get_debug_binary_path(harness_name)
    regular_binary_path = build_dir / harness_name

    return (debug_binary_path and debug_binary_path.exists()) or regular_binary_path.exists()


def _has_harness_in_build(task: ChallengeTask, harness_name: str, is_debug_build: bool = False) -> bool:
    """Check if task has the specified harness in a specific build type.

    Args:
        task: ChallengeTask with the build
        harness_name: Name of the harness
        is_debug_build: If True, check in /out (FUZZER_DEBUG build),
                       otherwise check in /out or /out/debug (legacy)
    """
    build_dir = task.get_build_dir()
    if not build_dir or not build_dir.exists():
        return False

    if is_debug_build:
        # FUZZER_DEBUG builds output to /out (same as regular builds)
        return (build_dir / harness_name).exists()
    else:
        # Legacy: check both /out and /out/debug
        regular_binary_path = build_dir / harness_name
        debug_binary_path = task.get_debug_binary_path(harness_name)
        return regular_binary_path.exists() or (
            debug_binary_path is not None and debug_binary_path is not Path("") and debug_binary_path.exists()
        )


def _has_debug_binary(task: ChallengeTask, harness_name: str) -> bool:
    """Check if task has debug binary for the harness"""
    debug_binary_path = task.get_debug_binary_path(harness_name)
    return debug_binary_path is not None and debug_binary_path.exists()


def resolve_actual_binary(
    task: ChallengeTask,
    harness_name: str,
    using_debug: bool,
    is_fuzzer_debug: bool = False,
) -> tuple[Path, str]:
    """Resolve the actual binary path, handling wrapper scripts.

    Some harness binaries are wrapper scripts that call the actual ELF binary.
    This method detects such cases and finds the real binary.

    Args:
        task: ChallengeTask with the build
        harness_name: Name of the harness
        using_debug: Whether to use debug binary
        is_fuzzer_debug: If True, this is a FUZZER_DEBUG build (binary in /out, not /out/debug)

    Returns:
        Tuple of (binary_path, binary_name)
    """
    build_dir = task.get_build_dir()
    if not build_dir or not build_dir.exists():
        raise ValueError(f"Build directory not found: {build_dir}")

    # Get initial binary path
    if using_debug:
        # FUZZER_DEBUG builds output to /out (same as regular builds)
        harness_binary_path = build_dir / harness_name

        if not harness_binary_path or not harness_binary_path.exists():
            raise ValueError(f"Debug binary not found for harness: {harness_name}")
    else:
        harness_binary_path = build_dir / harness_name
        if not harness_binary_path.exists():
            available_files = [f.name for f in build_dir.iterdir()] if build_dir.is_dir() else []
            raise ValueError(
                f"Harness binary '{harness_name}' not found in {build_dir}. Available files: {available_files}"
            )

    # Ensure execute permissions
    current_perms = harness_binary_path.stat().st_mode
    harness_binary_path.chmod(current_perms | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    # Check if it's an ELF binary
    try:
        with open(harness_binary_path, "rb") as f:
            magic = f.read(4)
            is_elf = magic == b"\x7fELF"
    except Exception:
        is_elf = False

    binary_size = harness_binary_path.stat().st_size

    # If it's a valid ELF binary of reasonable size, use it as-is
    if is_elf and binary_size >= 1024:
        return (harness_binary_path, harness_name)

    # Otherwise, it's likely a wrapper script - search for the actual binary
    logger.warning(
        f"File '{harness_name}' appears to be a wrapper script (size={binary_size}, is_elf={is_elf}). "
        f"Searching for actual ELF binary..."
    )

    # Try to find the actual binary by looking for ELF files in the build directory
    # Priority: 1) Base name without suffix, 2) Any ELF file with base name as prefix
    base_name = harness_name

    # Remove common sanitizer suffixes
    for suffix in ["_nalloc", "_asan", "_msan", "_ubsan", "_tsan", "_hwasan"]:
        if base_name.endswith(suffix):
            base_name = base_name[: -len(suffix)]
            break

    # First, try the base name directly
    candidate_path = build_dir / base_name
    if candidate_path.exists() and candidate_path.is_file():
        try:
            with open(candidate_path, "rb") as f:
                candidate_magic = f.read(4)
                candidate_is_elf = candidate_magic == b"\x7fELF"
            candidate_size = candidate_path.stat().st_size
            if candidate_is_elf and candidate_size > 1024:
                logger.info(
                    f"Found actual binary: {base_name} (size={candidate_size}, is_elf={candidate_is_elf}). "
                    f"Using this instead of wrapper '{harness_name}'."
                )
                # Set execute permissions
                current_perms = candidate_path.stat().st_mode
                candidate_path.chmod(current_perms | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
                return (candidate_path, base_name)
        except Exception as e:
            logger.debug(f"Error checking candidate {base_name}: {e}")

    # If base name didn't work, search for any ELF file with base name as prefix
    if build_dir.is_dir():
        for candidate in build_dir.iterdir():
            if candidate.is_file() and candidate != harness_binary_path:
                if candidate.name.startswith(base_name):
                    try:
                        with open(candidate, "rb") as f:
                            candidate_magic = f.read(4)
                            candidate_is_elf = candidate_magic == b"\x7fELF"
                        candidate_size = candidate.stat().st_size
                        if candidate_is_elf and candidate_size > 1024:
                            logger.info(
                                f"Found actual binary: {candidate.name} (size={candidate_size}). "
                                f"Using this instead of wrapper '{harness_name}'."
                            )
                            # Set execute permissions
                            current_perms = candidate.stat().st_mode
                            candidate.chmod(current_perms | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
                            return (candidate, candidate.name)
                    except Exception as e:
                        logger.debug(f"Error checking candidate {candidate.name}: {e}")

    # If we couldn't find a better binary, use the original (even if it's a wrapper)
    logger.warning(f"Could not find actual ELF binary, using original: {harness_name}")
    return (harness_binary_path, harness_name)
