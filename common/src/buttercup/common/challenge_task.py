from __future__ import annotations

import contextlib
import logging
import os
import re
import shlex
import shutil
import subprocess
import tempfile
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from functools import cached_property, wraps
from os import PathLike
from pathlib import Path
from typing import Any, TypeVar, cast

from packaging.version import Version

from buttercup.common import node_local
from buttercup.common.constants import ARCHITECTURE
from buttercup.common.stack_parsing import get_crash_token
from buttercup.common.task_meta import TaskMeta
from buttercup.common.utils import copyanything, get_diffs

logger = logging.getLogger(__name__)

# Patterns that indicate a file is a harness/fuzzing file (should not be patched)
HARNESS_PATH_PATTERNS = (
    "/fuzz/",
    "/fuzzer/",
    "/fuzzing/",
    "/fuzzers/",
    "Fuzz",
    "_fuzz",
    "_fuzzer",
    "harness",
)


def is_harness_file_path(file_path: str | Path) -> bool:
    """Check if a file path appears to be a harness/fuzzing file.

    Harness files should never be patched - they are test infrastructure,
    not the actual project code that contains vulnerabilities.

    Args:
        file_path: The file path to check (can be absolute or relative)

    Returns:
        True if the file appears to be a harness file, False otherwise.
    """
    path_str = str(file_path)

    # Check for common harness path patterns
    for pattern in HARNESS_PATH_PATTERNS:
        if pattern in path_str:
            return True

    return False


def filter_harness_files_from_diff(diff_content: str) -> tuple[str, list[str]]:
    """Filter out harness file changes from a unified diff.

    Args:
        diff_content: The full content of a unified diff file.

    Returns:
        A tuple of (filtered_diff, list_of_removed_harness_files).
        The filtered_diff has harness file hunks removed.
        list_of_removed_harness_files contains the paths of files that were filtered out.
    """
    removed_files: list[str] = []
    filtered_hunks: list[str] = []
    current_hunk: list[str] = []
    current_file: str | None = None
    is_harness = False

    for line in diff_content.splitlines(keepends=True):
        # Detect start of a new file's diff
        if line.startswith("diff --git "):
            # Save the previous hunk if it's not a harness file
            if current_hunk and not is_harness:
                filtered_hunks.extend(current_hunk)
            elif current_file and is_harness:
                removed_files.append(current_file)

            # Start a new hunk
            current_hunk = [line]
            # Extract file path from "diff --git a/path b/path"
            match = re.search(r"diff --git a/(.*?) b/", line)
            if match:
                current_file = match.group(1)
                is_harness = is_harness_file_path(current_file)
            else:
                current_file = None
                is_harness = False
        else:
            current_hunk.append(line)

    # Don't forget the last hunk
    if current_hunk and not is_harness:
        filtered_hunks.extend(current_hunk)
    elif current_file and is_harness:
        removed_files.append(current_file)

    return "".join(filtered_hunks), removed_files


@contextmanager
def create_tmp_dir(
    challenge: ChallengeTask,
    work_dir: Path | None,
    delete: bool = True,
    prefix: str | None = None,
) -> Iterator[Path]:
    """Create a temporary directory inside a working dir and either keep or
    delete it after use.
    """
    if work_dir:
        work_dir.mkdir(parents=True, exist_ok=True)

    if delete:
        global_tmp_dir = None
        try:
            with tempfile.TemporaryDirectory(dir=work_dir, prefix=prefix, ignore_cleanup_errors=True) as tmp_dir:
                global_tmp_dir = Path(tmp_dir)
                yield global_tmp_dir
        except PermissionError as e:
            logger.warning("Issues while creating/deleting a temporary directory, trying from docker...")
            if global_tmp_dir:
                res = challenge.exec_docker_cmd_rw(
                    ["rm", "-rf", f"/mnt/{global_tmp_dir.name}"],
                    mount_dirs={global_tmp_dir.parent: Path("/mnt")},
                    container_image="ubuntu:24.04",
                )
                if not res.success:
                    logger.error("Failed to remove temporary directory from docker: %s", res.output)
                    if logger.getEffectiveLevel() == logging.DEBUG:
                        logger.exception(f"PermissionError: {e}")
    else:
        with contextlib.nullcontext(tempfile.mkdtemp(dir=work_dir, prefix=prefix)) as tmp_dir:
            yield Path(tmp_dir)


class ChallengeTaskError(Exception):
    """Base class for Challenge Task errors."""


FAILURE_ERR_RESULT = 201
TIMEOUT_ERR_RESULT = 124


@dataclass
class CommandResult:
    success: bool
    returncode: int | None = None
    error: bytes | None = None
    output: bytes | None = None


@dataclass
class ReproduceResult:
    command_result: CommandResult

    def stacktrace(self) -> str | None:
        """Build clusterfuzz-compatible stacktrace"""
        # from clusterfuzz libfuzzer engine
        # https://github.com/google/clusterfuzz/blob/master/src/clusterfuzz/_internal/base/utils.py#L967
        MAX_OUTPUT_LEN = 1 * 1024 * 1024  # 1 MB
        if self.command_result.output:
            output_bytes = self.command_result.output
            if len(output_bytes) > MAX_OUTPUT_LEN:
                # Read first and last |half_max_len| bytes.
                half_max_len = MAX_OUTPUT_LEN // 2
                start = output_bytes[:half_max_len]
                end = output_bytes[-half_max_len:]

                truncated_marker = b"\n...truncated %d bytes...\n" % (len(output_bytes) - MAX_OUTPUT_LEN)

                output_bytes = start + truncated_marker + end

            output = output_bytes.decode("utf-8", errors="ignore")
            return output
        return None

    def did_run(self) -> bool:
        """Determine if the fuzzer at least ran"""
        return bool(
            (self.command_result.output and b"INFO: Seed: " in self.command_result.output)
            or (self.command_result.error and b"INFO: Seed: " in self.command_result.error),
        )

    # This is intended to encapsulate heuristics for determining if a run caused a crash
    # Could grep for strings from sanitizers as well
    def did_crash(self) -> bool:
        """Determine if a crash occurred

        Conditions:
         - Nonzero return code
         - Fuzzer ran (assumes libfuzzer or Jazzer)
        """
        crashed = bool(self.did_run() and self.command_result.returncode not in [None, 0, FAILURE_ERR_RESULT])
        if not crashed:
            return False

        return_code = self.command_result.returncode
        if return_code != TIMEOUT_ERR_RESULT:
            return True

        stacktrace = self.stacktrace()
        if stacktrace is None:
            return False

        crash_token = get_crash_token(stacktrace)
        if not crash_token:
            return False

        return True


F = TypeVar("F", bound=Callable[..., Any])


@dataclass
class ChallengeTask:
    """Class to manage Challenge Tasks."""

    read_only_task_dir: PathLike[str] | str
    task_meta: TaskMeta = field(init=False)
    python_path: PathLike[str] | str = Path("python")
    local_task_dir: PathLike[str] | str | None = None

    SRC_DIR = "src"
    DIFF_DIR = "diff"
    OSS_FUZZ_DIR = "fuzz-tooling"

    MAX_COMMIT_RETRIES = 3

    WORKDIR_REGEX = re.compile(r"\s*WORKDIR\s*([^\s]+)")

    _helper_path: Path = field(init=False)
    _full_helper_path: Path = field(init=False)
    _image_built: bool = field(default=False)

    def __post_init__(self) -> None:
        self.read_only_task_dir = self._local_ro_dir(self.read_only_task_dir)

        self.local_task_dir = Path(self.local_task_dir) if self.local_task_dir else None
        self.python_path = Path(self.python_path)

        self._check_dir_exists(self.read_only_task_dir)

        if self.local_task_dir:
            self._check_dir_exists(self.local_task_dir)

        # Pickup the TaskMeta from the read-only task directory
        self.task_meta = TaskMeta.load(self.read_only_task_dir)

        # Verify required directories exist
        for directory in [self.SRC_DIR, self.OSS_FUZZ_DIR]:
            if not (self.task_dir / directory).is_dir():
                raise ChallengeTaskError(f"Missing required directory: {self.task_dir / directory}")

        self._helper_path = Path("infra/helper.py")
        oss_fuzz_path = self.get_oss_fuzz_path()
        self._full_helper_path = oss_fuzz_path / self._helper_path
        if not self._full_helper_path.exists():
            raise ChallengeTaskError(f"Missing required file: {self._full_helper_path}")

        self._check_python_path()

    def _local_ro_dir(self, path: PathLike[str] | str) -> Path:
        """Return the local path to the read-only task directory.

        If the path doesn't exist, it will be downloaded from the remote storage
        """
        lp = Path(path)
        if not lp.exists():
            try:
                return node_local.remote_archive_to_dir(lp)
            except Exception as e:
                raise ChallengeTaskError(f"Failed to download task directory from remote storage: {e}") from e
        return lp

    def _check_dir_exists(self, path: Path) -> None:
        if not path.exists():
            raise ChallengeTaskError(f"Missing required directory: {path}")

        if not path.is_dir():
            raise ChallengeTaskError(f"Required directory is not a directory: {path}")

    def _find_first_dir(self, subpath: str) -> Path | None:
        if not (self.task_dir / subpath).exists():
            return None
        first_elem = next((self.task_dir / subpath).iterdir(), None)
        if first_elem is None:
            return None
        return first_elem.relative_to(self.task_dir)

    def get_source_subpath(self) -> Path | None:
        # Return the focus path relative to SRC_DIR
        return Path(self.SRC_DIR) / self.focus

    def get_diff_subpath(self) -> Path | None:
        # TODO: "Review task structure and Challenge Task operations" Issue #74
        return self._find_first_dir(self.DIFF_DIR)

    def get_oss_fuzz_subpath(self) -> Path | None:
        # TODO: "Review task structure and Challenge Task operations" Issue #74
        return self._find_first_dir(self.OSS_FUZZ_DIR)

    def _task_dir_compose_path(
        self,
        subpath_method: Callable[[], Path | None],
        raise_on_none: bool = False,
    ) -> Path | None:
        subpath = subpath_method()
        if subpath is None:
            if raise_on_none:
                raise ChallengeTaskError(f"Path not found: {subpath_method.__name__}")
            return None
        return self.task_dir / subpath

    def get_source_path(self) -> Path:
        return self._task_dir_compose_path(self.get_source_subpath, raise_on_none=True)  # type: ignore[return-value]

    def get_diff_path(self) -> Path | None:
        return self._task_dir_compose_path(self.get_diff_subpath)

    def get_oss_fuzz_path(self) -> Path:
        return self._task_dir_compose_path(self.get_oss_fuzz_subpath, raise_on_none=True)  # type: ignore[return-value]

    def get_build_dir(self) -> Path | None:
        return self.get_oss_fuzz_path() / "build" / "out" / self.project_name

    def get_diffs(self) -> list[Path]:
        return get_diffs(self.get_diff_path())

    def is_delta_mode(self) -> bool:
        return len(self.get_diffs()) > 0

    def _check_python_path(self) -> None:
        """Check if the configured python_path is available in system PATH."""
        try:
            subprocess.run([self.python_path, "--version"], check=False, capture_output=True, text=True)
        except Exception as e:
            raise ChallengeTaskError(f"Python executable couldn't be run: {self.python_path}") from e

    def _workdir_from_lines(self, lines: list[str], default: Path = Path("/src")) -> Path:
        """Gets the WORKDIR from the given lines."""
        for line in reversed(lines):  # reversed to get last WORKDIR.
            match = re.match(self.WORKDIR_REGEX, line)
            if match:
                workdir = match.group(1)
                workdir = workdir.replace("$SRC", "/src")

                workdir = Path(workdir)
                if not workdir.is_absolute():
                    workdir = Path("/src") / workdir

                return workdir

        return default

    def dockerfile_path(self) -> Path:
        """Read the Dockerfile for the given project."""
        return self.get_oss_fuzz_path() / "projects" / self.project_name / "Dockerfile"

    def workdir_from_dockerfile(self) -> Path:
        """Parses WORKDIR from the Dockerfile for the given project."""
        # NOTE: This is extracted and adapted from the OSS-Fuzz repository
        # https://github.com/google/oss-fuzz/blob/3beb664440843f159e38ef66eb68a7cbd2704dad/infra/helper.py#L704
        default_workdir = Path("/src") / self.project_name
        try:
            oss_fuzz_path = self.get_oss_fuzz_path()
            with open(oss_fuzz_path / "projects" / self.project_name / "Dockerfile") as file_handle:
                lines = file_handle.readlines()

            return self._workdir_from_lines(lines, default=default_workdir)
        except FileNotFoundError:
            return default_workdir

    def get_external_harness_sources(self) -> list[tuple[str, str]]:
        """Detect COPY directives that copy harness directories into the source.

        Public OSS-Fuzz projects often have harnesses in the projects/<name>/ directory
        rather than in the source repository. These are copied via COPY directives like:
            COPY fuzz/ $SRC/libmodbus/fuzz/
            COPY fuzzer/ $SRC/project/fuzzer/

        Returns:
            List of (source_dir, dest_subdir) tuples where:
            - source_dir: Directory in projects/<project>/ (e.g., "fuzz")
            - dest_subdir: Subdirectory in the source (e.g., "fuzz")
            Empty list if no external harness sources detected.
        """
        try:
            dockerfile_path = self.dockerfile_path()
            logger.debug(f"Looking for Dockerfile at: {dockerfile_path}")

            if not dockerfile_path.exists():
                logger.debug(f"Dockerfile not found at {dockerfile_path}")
                return []

            with open(dockerfile_path) as f:
                content = f.read()

            logger.debug(f"Dockerfile content length: {len(content)} chars")

            results = []
            # Pattern matches: COPY <dir>/ $SRC/<something>/<dir>/ or /src/<something>/<dir>/
            # Captures the source directory name
            # Examples:
            #   COPY fuzz/ $SRC/libmodbus/fuzz/  -> ("fuzz", "fuzz")
            #   COPY fuzzer/ $SRC/project/test/  -> ("fuzzer", "test")
            #   COPY fuzz/ /src/libmodbus/fuzz/  -> ("fuzz", "fuzz")
            # Handle both $SRC and /src variants, with or without trailing slash
            pattern = r"^\s*COPY\s+(\w+)/?\s+(?:\$SRC|/src)/[^/\s]+/(\w+)/?"
            for match in re.finditer(pattern, content, re.MULTILINE):
                src_dir = match.group(1)
                dest_dir = match.group(2)
                logger.debug(f"Regex matched: src_dir={src_dir}, dest_dir={dest_dir}")

                # Verify the source directory exists in the OSS-Fuzz project
                oss_fuzz_src = self.get_oss_fuzz_path() / "projects" / self.project_name / src_dir
                logger.debug(f"Checking if exists: {oss_fuzz_src}")

                if oss_fuzz_src.exists() and oss_fuzz_src.is_dir():
                    results.append((src_dir, dest_dir))
                    logger.info(
                        f"Detected external harness source: {src_dir} -> {dest_dir} (verified at {oss_fuzz_src})"
                    )
                else:
                    logger.debug(f"Source directory not found or not a dir: {oss_fuzz_src}")

            if not results:
                logger.debug("No external harness sources detected in Dockerfile")

            return results
        except FileNotFoundError as e:
            logger.warning(f"Dockerfile not found: {e}")
            return []
        except Exception as e:
            logger.warning(f"Error detecting external harness sources: {e}")
            return []

    def has_external_harnesses(self) -> bool:
        """Check if project uses external harnesses (public OSS-Fuzz style).

        Returns True if the Dockerfile copies harness directories from the
        OSS-Fuzz project into the source tree.
        """
        return len(self.get_external_harness_sources()) > 0

    def copy_external_harnesses(self) -> bool:
        """Copy external harness sources from OSS-Fuzz project to source directory.

        For public OSS-Fuzz projects, harnesses live in projects/<project>/<dir>/
        in the fuzz-tooling repository. These need to be copied to the source
        directory so they're available when the source is mounted during build.

        Returns:
            True if copying succeeded or no external harnesses detected,
            False if copying failed.
        """
        external_sources = self.task_meta.metadata.get("external_harness_sources", [])
        logger.debug(f"[task {self.task_meta.task_id}] Metadata: {self.task_meta.metadata}")

        if not external_sources:
            logger.debug(f"[task {self.task_meta.task_id}] No external harness sources in metadata")
            return True

        logger.info(f"[task {self.task_meta.task_id}] Copying external harness sources: {external_sources}")

        try:
            oss_fuzz_path = self.get_oss_fuzz_path()
            source_path = self.get_source_path()
            project_name = self.project_name

            logger.debug(f"[task {self.task_meta.task_id}] OSS-Fuzz path: {oss_fuzz_path}")
            logger.debug(f"[task {self.task_meta.task_id}] Source path: {source_path}")
            logger.debug(f"[task {self.task_meta.task_id}] Project name: {project_name}")

            for src_dir, dest_dir in external_sources:
                # Source: fuzz-tooling/<oss-fuzz>/projects/<project>/<src_dir>/
                harness_src = oss_fuzz_path / "projects" / project_name / src_dir

                if not harness_src.exists():
                    logger.warning(f"[task {self.task_meta.task_id}] External harness source not found: {harness_src}")
                    continue

                # Destination: src/<focus>/<dest_dir>/
                harness_dst = source_path / dest_dir

                logger.info(f"[task {self.task_meta.task_id}] Copying {harness_src} -> {harness_dst}")

                # Remove existing directory if present (will be replaced)
                if harness_dst.exists():
                    logger.debug(f"[task {self.task_meta.task_id}] Removing existing {harness_dst}")
                    shutil.rmtree(harness_dst)

                # Copy harnesses
                shutil.copytree(harness_src, harness_dst)

                # Verify copy
                if harness_dst.exists():
                    files = list(harness_dst.iterdir())
                    logger.info(
                        f"[task {self.task_meta.task_id}] Successfully copied {len(files)} files to {harness_dst}"
                    )
                else:
                    logger.error(f"[task {self.task_meta.task_id}] Copy failed - destination doesn't exist!")
                    return False

            return True
        except Exception as e:
            logger.exception(f"[task {self.task_meta.task_id}] Failed to copy external harnesses: {e}")
            return False

    @property
    def task_dir(self) -> Path:
        if self.local_task_dir is None:
            return Path(self.read_only_task_dir)
        return Path(self.local_task_dir)

    @property
    def name(self) -> str:
        return self.project_name

    @property
    def focus(self) -> str:
        return self.task_meta.focus

    @property
    def project_name(self) -> str:
        return self.task_meta.project_name

    @staticmethod
    def read_write_decorator(func: F) -> F:
        """Decorator to check if the task is read-only."""

        @wraps(func)
        def wrapper(self: ChallengeTask, *args: Any, **kwargs: Any) -> Any:
            if self.local_task_dir is None:
                raise ChallengeTaskError("Challenge Task is read-only, cannot perform this operation")
            return func(self, *args, **kwargs)

        return cast("F", wrapper)

    def _add_optional_arg(self, cmd: list[str], flag: str, arg: Any | None) -> None:
        if arg is not None:
            if isinstance(arg, bool):
                if arg:
                    cmd.append(flag)
            else:
                cmd.append(flag)
                cmd.append(str(arg))

    def _get_helper_cmd(self, helper_cmd: str, *args: Any, **kwargs: Any) -> list[str]:
        cmd = [str(self.python_path), str(self._helper_path), helper_cmd]
        for key, value in kwargs.items():
            if key == "e":
                for k, v in value.items() if isinstance(value, dict) else {}:
                    cmd.append("-e")
                    cmd.append(f"{k}={v}")
            else:
                self._add_optional_arg(cmd, f"--{key}", value)

        for arg in args:
            if arg is not None:
                if isinstance(arg, list):
                    cmd.extend(arg)
                else:
                    cmd.append(arg)

        return cmd

    def _log_output_line(self, current_line: bytes, new_data: bytes, log: bool) -> bytes:
        current_line += new_data
        line_to_print = b""
        if b"\n" in current_line:
            line_to_print = current_line[: current_line.index(b"\n")]
            current_line = current_line[current_line.index(b"\n") + 1 :]
            if log:
                logger.debug(line_to_print.decode(errors="ignore"))

        return current_line

    def _run_cmd(
        self,
        cmd: list[str],
        cwd: Path | None = None,
        log: bool = True,
        env_helper: dict[str, str] | None = None,
    ) -> CommandResult:
        try:
            if env_helper:
                logger.debug("Env helper: %s", env_helper)
                env_helper = {**os.environ, **env_helper}
            logger.debug(f"Running command (cwd={cwd}): {' '.join(cmd)}")
            process = subprocess.Popen(  # noqa: S603
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                cwd=cwd,
                env=env_helper,
            )

            # Poll process for new output until finished
            stdout = b""
            stderr = b""
            current_output_line = b""
            current_error_line = b""
            while True:
                stdout_line = process.stdout.readline() if process.stdout else b""
                stderr_line = process.stderr.readline() if process.stderr else b""
                if stdout_line:
                    current_output_line = self._log_output_line(current_output_line, stdout_line, log)
                    stdout += stdout_line

                if stderr_line:
                    current_error_line = self._log_output_line(current_error_line, stderr_line, log)
                    stderr += stderr_line

                # Break if process has finished and we've read all output
                if not stdout_line and not stderr_line and process.poll() is not None:
                    break

            returncode = process.wait()

            return CommandResult(
                success=returncode == 0,
                returncode=returncode,
                error=stderr,
                output=stdout,
            )
        except subprocess.CalledProcessError as e:
            logger.error(f"Command failed (cwd={cwd}): {' '.join(cmd)}")
            return CommandResult(
                success=False,
                returncode=None,
                error=e.stderr if e.stderr else None,
                output=e.stdout if e.stdout else None,
            )
        except Exception as e:
            logger.exception(f"Command failed (cwd={cwd}): {' '.join(cmd)}")
            return CommandResult(success=False, returncode=None, error=str(e).encode(), output=None)

    def _run_helper_cmd(self, cmd: list[str], env_helper: dict[str, str] | None = None) -> CommandResult:
        oss_fuzz_subpath = self.get_oss_fuzz_subpath()
        if oss_fuzz_subpath is None:
            raise ChallengeTaskError("OSS-Fuzz path not found")

        return self._run_cmd(cmd, cwd=self.task_dir / oss_fuzz_subpath, env_helper=env_helper)

    def _get_base_runner_version(self) -> Version | None:
        """The base-runner image tag is hardcoded in infra/helper.py."""
        grep_cmd = ["grep", "BASE_IMAGE_TAG =", str(self._helper_path)]
        try:
            result = self._run_helper_cmd(grep_cmd)
        except Exception as e:
            logger.exception(f"[task {self.task_dir}] Error grep'ing for base-runner version: {e!s}")
            return None
        if not result.success:
            return None

        if result.output is None:
            return None

        m = re.search(r"BASE_IMAGE_TAG = '([^']+)'", result.output.decode("utf-8"))
        if not m:
            return None

        try:
            base_runner_str = m.group(1).strip(":v")
            return Version(base_runner_str)
        except Exception as e:
            logger.exception(f"[task {self.task_dir}] Error parsing base-runner version: {e!s}")
            return None

    @cached_property
    def oss_fuzz_container_org(self) -> str:
        # Check environment variable first
        if env_org := os.environ.get("OSS_FUZZ_CONTAINER_ORG"):
            return env_org

        # Read the helper_path file and grep for the BASE_RUNNER_IMAGE line.
        result = "gcr.io/oss-fuzz"
        try:
            with self._full_helper_path.open("r") as f:
                for line in reversed(f.readlines()):
                    if "BASE_RUNNER_IMAGE" in line:
                        m = re.search(r"^BASE_RUNNER_IMAGE\s*=\s*f?['\"]([^'\"]+)['\"]", line)
                        if m:
                            image = m.group(1)
                            if image.startswith("gcr.io/oss-fuzz"):
                                logger.info(f"Using oss-fuzz container org: {result}")
                                break
                            if image.startswith("ghcr.io/aixcc-finals"):
                                result = "aixcc-afc"
                                logger.info(f"Using aixcc-afc container org: {result}")
                                break
        except Exception:
            logger.exception("Could not determine oss_fuzz_container_org from helper_path")

        return result

    def container_image(self) -> str:
        return f"{self.oss_fuzz_container_org}/{self.project_name}"

    def container_src_dir(self) -> str:
        """Name of the src directory in the container (e.g. /src/FreeRDP -> FreeRDP).
        This assumes that the src directory is the same as the workdir.
        """
        return self.workdir_from_dockerfile().parts[-1]

    @read_write_decorator
    def exec_docker_cmd(
        self,
        cmd: list[str] | str,
        mount_dirs: dict[Path, Path] | None = None,
        container_image: str | None = None,
        always_build_image: bool = False,
    ) -> CommandResult:
        """Execute a command inside a docker container. If not specified, the
        docker container is the oss-fuzz one.
        """
        return self.exec_docker_cmd_rw(cmd, mount_dirs, container_image, always_build_image=always_build_image)

    def exec_docker_cmd_rw(
        self,
        cmd: list[str] | str,
        mount_dirs: dict[Path, Path] | None = None,
        container_image: str | None = None,
        always_build_image: bool = False,
    ) -> CommandResult:
        """Execute a command inside a docker container. Allow to run even on non rw Challenge Tasks."""
        if container_image is None:
            if not self._image_built or always_build_image:
                res = self.build_image(cache=True)
                if not res.success:
                    raise ChallengeTaskError(f"Failed to build image: {res.error!r}")

                self._image_built = True

            container_image = self.container_image()
            if mount_dirs is None:
                mount_dirs = {}
            source_path = self.get_source_path()
            mount_dirs.update({source_path: self.workdir_from_dockerfile()})

        docker_cmd = ["docker", "run", "--privileged", "--shm-size=2g", "--rm"]
        if mount_dirs:
            for src, dst in mount_dirs.items():
                docker_cmd += ["-v", f"{src.resolve().as_posix()}:{dst.as_posix()}"]

        cmd_str = cmd if isinstance(cmd, str) else shlex.join(cmd)
        docker_cmd += [container_image, "bash", "-c", cmd_str]
        return self._run_cmd(docker_cmd, log=False)

    @read_write_decorator
    def build_image(
        self,
        *,
        pull_latest_base_image: bool = False,
        cache: bool | None = None,
        architecture: str | None = ARCHITECTURE,
    ) -> CommandResult:
        logger.info(
            "Building image for project %s | pull_latest_base_image=%s | cache=%s | architecture=%s",
            self.project_name,
            pull_latest_base_image,
            cache,
            architecture,
        )
        kwargs = {
            "pull": pull_latest_base_image,
            "no-pull": not pull_latest_base_image,
            "cache": cache,
            "architecture": architecture,
        }
        cmd = self._get_helper_cmd(
            "build_image",
            self.project_name,
            **kwargs,
        )

        return self._run_helper_cmd(cmd)

    @read_write_decorator
    def build_fuzzers(
        self,
        use_source_dir: bool = True,
        *,
        architecture: str | None = ARCHITECTURE,
        engine: str | None = None,
        sanitizer: str | None = None,
        env: dict[str, str] | None = None,
        env_helper: dict[str, str] | None = None,
    ) -> CommandResult:
        logger.info(
            "Building fuzzers for project %s | architecture=%s | engine=%s | sanitizer=%s | env=%s | use_source_dir=%s",
            self.project_name,
            architecture,
            engine,
            sanitizer,
            env,
            use_source_dir,
        )
        kwargs = {
            "architecture": architecture,
            "engine": engine,
            "sanitizer": sanitizer,
            "e": env,
        }
        if self.workdir_from_dockerfile() == Path("/src"):
            # oss-fuzz cannot automatically mount the local src directory if the
            # workdir is just /src, so in that case let's specify a mount point.
            # This should happen only for upstream oss-fuzz projects because
            # AIxCC guarantees `build_fuzzers <local-path>` to just work.
            # https://github.com/google/oss-fuzz/blob/80a57ca6da03069afabb5116cae0b338d19f9f27/infra/helper.py#L870-L872
            kwargs["mount_path"] = f"/src/{self.focus}"

        source_subpath = self.get_source_subpath()
        assert source_subpath is not None
        cmd = self._get_helper_cmd(
            "build_fuzzers",
            self.project_name,
            str((self.task_dir / source_subpath).absolute()) if use_source_dir else None,
            **kwargs,
        )

        return self._run_helper_cmd(cmd, env_helper=env_helper)

    @read_write_decorator
    def build_fuzzers_with_cache(
        self,
        use_source_dir: bool = True,
        *,
        architecture: str | None = ARCHITECTURE,
        engine: str | None = None,
        sanitizer: str | None = None,
        pull_latest_base_image: bool = True,
        env: dict[str, str] | None = None,
        env_helper: dict[str, str] | None = None,
    ) -> CommandResult:
        check_build_res = self.check_build(architecture=architecture, engine=engine, sanitizer=sanitizer, env=env)
        if check_build_res.success:
            logger.info("Build is up to date, skipping building fuzzers")
            return check_build_res

        self.build_image(pull_latest_base_image=pull_latest_base_image, architecture=architecture)

        return self.build_fuzzers(
            use_source_dir=use_source_dir,
            architecture=architecture,
            engine=engine,
            sanitizer=sanitizer,
            env=env,
            env_helper=env_helper,
        )

    @read_write_decorator
    def build_fuzzers_save_containers(
        self,
        container_name: str,
        use_source_dir: bool = True,
        *,
        architecture: str | None = ARCHITECTURE,
        engine: str | None = None,
        sanitizer: str | None = None,
        pull_latest_base_image: bool = True,
        env: dict[str, str] | None = None,
    ) -> CommandResult:
        env_helper = {
            "OSS_FUZZ_SAVE_CONTAINERS_NAME": container_name,
        }

        self.build_image(pull_latest_base_image=pull_latest_base_image, architecture=architecture)
        return self.build_fuzzers(
            use_source_dir=use_source_dir,
            architecture=architecture,
            engine=engine,
            sanitizer=sanitizer,
            env=env,
            env_helper=env_helper,
        )

    @read_write_decorator
    def check_build(
        self,
        *,
        architecture: str | None = ARCHITECTURE,
        engine: str | None = None,
        sanitizer: str | None = None,
        env: dict[str, str] | None = None,
    ) -> CommandResult:
        logger.info(
            "Checking build for project %s | architecture=%s | engine=%s | sanitizer=%s | env=%s",
            self.project_name,
            architecture,
            engine,
            sanitizer,
            env,
        )
        cmd = self._get_helper_cmd(
            "check_build",
            self.project_name,
            architecture=architecture,
            engine=engine,
            sanitizer=sanitizer,
            e=env,
        )

        return self._run_helper_cmd(cmd)

    @read_write_decorator
    def reproduce_pov(
        self,
        fuzzer_name: str,
        crash_path: Path,
        fuzzer_args: list[str] | None = None,
        *,
        architecture: str | None = ARCHITECTURE,
        env: dict[str, str] | None = None,
    ) -> ReproduceResult:
        logger.info(
            "Reproducing POV for project %s | fuzzer_name=%s | crash_path=%s | "
            "fuzzer_args=%s | architecture=%s | env=%s",
            self.project_name,
            fuzzer_name,
            crash_path,
            fuzzer_args,
            architecture,
            env,
        )
        kwargs: dict[str, Any] = {
            "architecture": architecture,
            "e": env,
        }
        if "aixcc" in self.oss_fuzz_container_org:
            kwargs["propagate_exit_code"] = True
            kwargs["err_result"] = FAILURE_ERR_RESULT

            # Get base-runner version
            base_runner_version = self._get_base_runner_version()

            # NOTE: This feature was added in v1.2.0 of infra/helper.py
            if base_runner_version and base_runner_version >= Version("1.2.0"):
                # Set timeout (in seconds) in the case it hangs
                # We use 120 seconds, which is larger than the suggested 65 seconds in the FAQ
                kwargs["timeout"] = 120

        cmd = self._get_helper_cmd(
            "reproduce",
            self.project_name,
            fuzzer_name,
            str(crash_path.absolute()),
            fuzzer_args,
            **kwargs,
        )

        return ReproduceResult(self._run_helper_cmd(cmd))

    @read_write_decorator
    def run_fuzzer(
        self,
        harness_name: str,
        fuzzer_args: list[str] | None = None,
        corpus_dir: Path | None = None,
        architecture: str | None = ARCHITECTURE,
        engine: str | None = None,
        sanitizer: str | None = None,
        env: dict[str, str] | None = None,
    ) -> CommandResult:
        logger.info(
            "Running fuzzer for project %s | harness_name=%s | fuzzer_args=%s | "
            "corpus_dir=%s | architecture=%s | engine=%s | sanitizer=%s | env=%s",
            self.project_name,
            harness_name,
            fuzzer_args,
            corpus_dir,
            architecture,
            engine,
            sanitizer,
            env,
        )
        kwargs = {
            "corpus-dir": corpus_dir,
            "architecture": architecture,
            "engine": engine,
            "sanitizer": sanitizer,
            "e": env,
        }
        cmd = self._get_helper_cmd(
            "run_fuzzer",
            self.project_name,
            harness_name,
            fuzzer_args,
            **kwargs,
        )
        return self._run_helper_cmd(cmd)

    @read_write_decorator
    def run_coverage(
        self,
        harness_name: str,
        corpus_dir: str,
        architecture: str | None = ARCHITECTURE,
        env: dict[str, str] | None = None,
    ) -> CommandResult:
        logger.info(
            "Running coverage for project %s | harness_name=%s | corpus_dir=%s | architecture=%s | env=%s",
            self.project_name,
            harness_name,
            corpus_dir,
            architecture,
            env,
        )
        kwargs = {
            "corpus-dir": corpus_dir,
            "fuzz-target": harness_name,
            "no-serve": True,
            "architecture": architecture,
            "e": env,
        }
        cmd = self._get_helper_cmd(
            "coverage",
            self.project_name,
            **kwargs,
        )
        return self._run_helper_cmd(cmd)

    @read_write_decorator
    def apply_patch_diff(self, diff_file: Path | None = None) -> bool:
        """Apply the patch diff to the source code.

        Note: Harness/fuzzing files are automatically filtered out from patches.
        These files should never be patched - only the actual source code should be modified.
        """
        try:
            if diff_file is None:
                # Find all .patch and .diff files in the directory
                diff_files = self.get_diffs()
                if not diff_files:
                    return False
            else:
                diff_files = [diff_file]

            for diff_file in diff_files:
                if not diff_file.exists():
                    raise ChallengeTaskError(f"[task {self.task_dir}] Diff file {diff_file} not found")

                logger.info(f"[task {self.task_dir}] Applying diff file: {diff_file}")

                # Read the diff content and filter out harness files
                diff_content = diff_file.read_text()
                filtered_diff, removed_files = filter_harness_files_from_diff(diff_content)

                if removed_files:
                    logger.warning(f"[task {self.task_dir}] Filtered out harness files from patch: {removed_files}")

                if not filtered_diff.strip():
                    logger.warning(
                        f"[task {self.task_dir}] Patch only contained harness file changes, nothing to apply"
                    )
                    continue

                # Write the filtered diff to a temporary file if we removed any harness files
                if removed_files:
                    with tempfile.NamedTemporaryFile(mode="w", suffix=".patch", delete=False) as f:
                        f.write(filtered_diff)
                        filtered_diff_path = Path(f.name)
                    try:
                        subprocess.run(
                            [
                                "git",
                                "-C",
                                str(self.get_source_path()),
                                "apply",
                                str(filtered_diff_path),
                            ],
                            text=True,
                            check=True,
                            timeout=10,
                            capture_output=True,
                        )
                    finally:
                        filtered_diff_path.unlink(missing_ok=True)
                else:
                    # No harness files to filter, apply original diff
                    subprocess.run(
                        [
                            "git",
                            "-C",
                            str(self.get_source_path()),
                            "apply",
                            str(diff_file),
                        ],
                        text=True,
                        check=True,
                        timeout=10,
                        capture_output=True,
                    )

                logger.info(f"[task {self.task_dir}] Successfully applied patch {diff_file}")

            return True
        except FileNotFoundError as e:
            logger.error(f"[task {self.task_dir}] File not found: {e!s}")
            raise ChallengeTaskError(f"[task {self.task_dir}] File not found: {e!s}") from e
        except subprocess.CalledProcessError as e:
            logger.error(f"[task {self.task_dir}] Error applying diff: {e!s}")
            logger.debug(f"[task {self.task_dir}] Error returncode: {e.returncode}")
            logger.debug(f"[task {self.task_dir}] Error stdout: {e.stdout}")
            logger.debug(f"[task {self.task_dir}] Error stderr: {e.stderr}")
            raise ChallengeTaskError(f"[task {self.task_dir}] Error applying diff: {e!s}") from e
        except Exception as e:
            logger.exception(f"[task {self.task_dir}] Error applying diff: {e!s}")
            raise ChallengeTaskError(f"[task {self.task_dir}] Error applying diff: {e!s}") from e

    def _hack_oss_fuzz_aarch64_dockerfile(self, task: ChallengeTask) -> None:
        # We find the oss-fuzz/projects/<project>/Dockerfile and make sure the
        # base image has `:manifest-arm64v8` tag
        dockerfile_path = task.get_oss_fuzz_path() / "projects" / task.project_name / "Dockerfile"
        if not dockerfile_path.exists():
            return

        dockerfile_content = dockerfile_path.read_text()

        # Regex to match FROM gcr.io/oss-fuzz-base/base-builder* [optional tag] [optional as builder]
        # Only patch base-builder variants, not base-clang or others that may not have manifest-arm64v8 tag
        def _replace_from(match: re.Match) -> str:
            image = match.group(1)
            as_clause = match.group(2) or ""
            # Always ensure tag is :manifest-arm64v8 regardless if there was a tag before
            return f"FROM {image}:manifest-arm64v8{as_clause}"

        # This regex matches FROM lines with base-builder images only
        pattern = r"^FROM\s+(gcr\.io/oss-fuzz-base/base-builder(?:[^\s:]*)?)(?::[^\s]+)?(\s+as\s+\w+)?\s*$"
        new_content = re.sub(pattern, _replace_from, dockerfile_content, flags=re.MULTILINE)

        if new_content != dockerfile_content:
            dockerfile_path.write_text(new_content)
            logger.info("Patched oss-fuzz %s/Dockerfile to use the :manifest-arm64v8 tag", task.project_name)

    def _hack_oss_fuzz_runner(self, task: ChallengeTask, architecture: str) -> None:
        """Patch OSS-Fuzz helper.py with architecture-specific and common fixes.

        Common patches (all architectures):
        - reproduce_impl: Pass architecture as keyword arg instead of err_result
        - Debug mode: Insert -debug before tag, not after
        - Tag handling: Check for existing tag before appending

        ARM64-specific patches:
        - Add :manifest-arm64v8 tags to image_name and BASE_RUNNER_IMAGE
        """
        helper_path = task.get_oss_fuzz_path() / "infra" / "helper.py"
        if not helper_path.exists():
            return

        content = helper_path.read_text()
        replaced = False

        # Common patches for all architectures

        def _replace_debug_append(match: re.Match) -> str:
            nonlocal replaced
            replaced = True
            indent = match.group(1)
            return f"{indent}image = image.replace(':', '-debug:', 1) if ':' in image else image + '-debug'"

        pattern_debug_append = r"^(\s+)image\s*\+=\s*['\"]-debug['\"]\s*$"
        content = re.sub(pattern_debug_append, _replace_debug_append, content, flags=re.MULTILINE)

        def _replace_get_base_runner_return(match: re.Match) -> str:
            nonlocal replaced
            replaced = True
            indent = match.group(1)
            return f"{indent}return image if ':' in image else f'{{image}}:{{tag}}'"

        pattern_get_base_runner = r"^(\s+)return f(['\"])\{image\}:\{tag\}\2\s*$"
        content = re.sub(pattern_get_base_runner, _replace_get_base_runner_return, content, flags=re.MULTILINE)

        def _replace_reproduce_run_function(match: re.Match) -> str:
            nonlocal replaced
            replaced = True
            indent = match.group(1)
            return f"{indent}return run_function(run_args, architecture=architecture)"

        pattern_reproduce_run = r"^(\s+)return run_function\(run_args,\s*err_result\)\s*$"
        content = re.sub(pattern_reproduce_run, _replace_reproduce_run_function, content, flags=re.MULTILINE)

        # ARM64-specific patches
        if architecture == "aarch64":

            def _replace_image_name(match: re.Match) -> str:
                nonlocal replaced
                replaced = True
                original = match.group(0)
                if "base-runner-debug" in original:
                    return f"{match.group(1)}image_name = 'base-runner-debug:manifest-arm64v8'"
                else:
                    return f"{match.group(1)}image_name = 'base-runner:manifest-arm64v8'"

            pattern_img = r"(\s*)image_name\s*=\s*['\"]base-runner(?:-debug)?['\"]"
            content = re.sub(pattern_img, _replace_image_name, content, flags=re.MULTILINE)

            def _replace_base_runner_image(match: re.Match) -> str:
                nonlocal replaced
                replaced = True
                prefix = match.group(1)
                image = match.group(2)
                suffix = match.group(3) or ""
                if ":manifest-arm64v8" not in image:
                    if ":" in image:
                        image = image.rsplit(":", 1)[0]
                    image = image + ":manifest-arm64v8"
                return f"{prefix}BASE_RUNNER_IMAGE = '{image}'{suffix}"

            pattern_base_img = (
                r"(^\s*)BASE_RUNNER_IMAGE\s*=\s*['\"](gcr\.io/oss-fuzz-base/base-runner(?:[^\s'\"]*)?)['\"](\s*)"
            )
            content = re.sub(pattern_base_img, _replace_base_runner_image, content, flags=re.MULTILINE)

        if replaced:
            helper_path.write_text(content)
            logger.info("Patched oss-fuzz helper.py for %s", architecture)

    def _hack_oss_fuzz_aarch64(self, task: ChallengeTask) -> None:
        self._hack_oss_fuzz_aarch64_dockerfile(task)
        self._hack_oss_fuzz_runner(task, "aarch64")

    @contextmanager
    def get_rw_copy(self, work_dir: PathLike | None, delete: bool = True) -> Iterator[ChallengeTask]:
        """Create a copy of this task in a new writable directory.
        Returns a context manager that yields a new ChallengeTask instance pointing to the new copy.

        Example:
            with task.get_rw_copy(work_dir) as local_task:
                local_task.build_fuzzers()

        """
        work_dir = Path(work_dir) if work_dir else Path(node_local.scratch_path())
        work_dir = work_dir / self.task_meta.task_id
        work_dir.mkdir(parents=True, exist_ok=True)

        with create_tmp_dir(self, work_dir, delete, prefix=self.task_dir.name + "-") as tmp_dir:
            # Copy the entire task directory to the temporary location
            logger.info(f"Copying task directory {self.task_dir} to {tmp_dir}")
            copyanything(self.task_dir, tmp_dir, symlinks=True)

            # Create a new ChallengeTask instance pointing to the copy
            copied_task = ChallengeTask(
                read_only_task_dir=self.read_only_task_dir,
                python_path=self.python_path,
                local_task_dir=tmp_dir,
            )
            # HACK: Apply OSS-Fuzz patches
            # For aarch64: Dockerfile + helper.py with :manifest-arm64v8 tags + common fixes
            # For other arches: helper.py with common fixes only
            if ARCHITECTURE == "aarch64":
                self._hack_oss_fuzz_aarch64(copied_task)
            else:
                self._hack_oss_fuzz_runner(copied_task, ARCHITECTURE)

            try:
                yield copied_task
            finally:
                pass

    def commit(self, suffix: str | None = None) -> None:
        """Commit the local task directory to a stable path.

        This is useful to save the task state for later use and together with
        the `get_rw_copy` context manager.
        """
        if self.local_task_dir is None:
            raise ChallengeTaskError("Challenge Task is read-only, cannot commit")

        assert isinstance(self.local_task_dir, Path)
        new_local_task_dir = None
        max_retries = self.MAX_COMMIT_RETRIES if suffix is None else 1
        for i in range(max_retries):
            suffix = suffix if suffix is not None else "-" + str(uuid.uuid4())[:16]
            new_name = f"{self.task_meta.task_id}{suffix}"
            try:
                logger.info(f"Committing task {self.local_task_dir} to {new_name}")
                new_local_task_dir = self.local_task_dir.rename(self.local_task_dir.parent / new_name)
                logger.info(f"Committed task {self.local_task_dir} to {new_name}")
                break
            except OSError as e:
                if i == max_retries - 1:
                    raise ChallengeTaskError("Failed to commit task") from e

                logger.error(
                    f"Failed to commit task {self.local_task_dir} to {new_name}. Retrying with a random suffix...",
                )
                suffix = None

        self.local_task_dir = new_local_task_dir

    @read_write_decorator
    def restore(self) -> None:
        """Restore the task from the original read-only task directory (if
        different from the local task directory).
        """
        if self.read_only_task_dir == self.local_task_dir:
            raise ChallengeTaskError("Task cannot be restored, it doesn't have a local task directory")

        assert isinstance(self.local_task_dir, Path)
        if self.local_task_dir.exists():
            logger.debug(f"Removing local task directory {self.local_task_dir}")
            self._remove_dir(self.local_task_dir)

        assert isinstance(self.read_only_task_dir, Path)
        copyanything(self.read_only_task_dir, self.local_task_dir, symlinks=True)
        logger.info(f"Restored task from {self.read_only_task_dir} to {self.local_task_dir}")

    def _remove_dir(self, path: Path) -> None:
        try:
            shutil.rmtree(path, ignore_errors=True)
        except Exception:
            logger.warning("Error removing directory %s, trying from within the container...", path)
            res = self.exec_docker_cmd(
                f"rm -rf /mnt/{path.name}",
                mount_dirs={path.parent: Path("/mnt")},
                container_image="ubuntu:24.04",
            )
            if not res.success:
                logger.error("Failed to remove directory from docker: %s", res.output)
                raise ChallengeTaskError(f"Failed to remove directory from docker: {res.output!r}")

    def get_test_sh_script(self, test_sh_path: str) -> str:
        return f"""cp {test_sh_path} $SRC/test.sh && $SRC/test.sh"""

    @read_write_decorator
    def cleanup(self) -> None:
        """Clean up a ChallengeTask local directory."""
        assert self.local_task_dir is not None

        directory = Path(self.local_task_dir)
        if not directory.exists():
            logger.warning("Directory %s does not exist, nothing to cleanup", directory)
            return

        logger.info("[task %s] Cleaning up task directory %s", self.task_meta.task_id, self.local_task_dir)
        self._remove_dir(directory)

    def get_clean_task(self, tasks_storage: Path) -> ChallengeTask:
        task_id = self.task_meta.task_id

        clean_challenge_task_dir = tasks_storage / task_id
        node_local.remote_archive_to_dir(clean_challenge_task_dir)
        return ChallengeTask(
            read_only_task_dir=clean_challenge_task_dir,
            python_path=self.python_path,
        )
