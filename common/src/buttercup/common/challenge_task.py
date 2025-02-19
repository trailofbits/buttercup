from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Any, Callable
from os import PathLike
import logging
import shutil
import uuid
import subprocess
from buttercup.common.utils import create_tmp_dir, copyanything, get_diffs
from contextlib import contextmanager
from typing import Iterator

logger = logging.getLogger(__name__)


class ChallengeTaskError(Exception):
    """Base class for Challenge Task errors."""

    pass


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
        MAX_OUTPUT_LEN = 1 * 1024 * 1024  # 1 MB
        if self.command_result.output:
            output_bytes = self.command_result.output[:MAX_OUTPUT_LEN]
            output = output_bytes.decode("utf-8", errors="ignore")
            return output
        return None

    # This is inteneded to encapsulate heuristics for determining if a run caused a crash
    # Could grep for strings from sanitizers as well
    def did_crash(self) -> bool:
        return self.command_result.returncode is not None and self.command_result.returncode != 0


@dataclass
class ChallengeTask:
    """Class to manage Challenge Tasks."""

    read_only_task_dir: PathLike
    project_name: str
    python_path: PathLike = Path("python")
    local_task_dir: PathLike | None = None

    SRC_DIR = "src"
    DIFF_DIR = "diff"
    OSS_FUZZ_DIR = "fuzz-tooling"

    MAX_COMMIT_RETRIES = 3

    _helper_path: Path = field(init=False)

    def __post_init__(self) -> None:
        self.read_only_task_dir = Path(self.read_only_task_dir)
        self.local_task_dir = Path(self.local_task_dir) if self.local_task_dir else None
        self.python_path = Path(self.python_path)

        self._check_dir_exists(self.read_only_task_dir)
        if self.local_task_dir:
            self._check_dir_exists(self.local_task_dir)

        # Verify required directories exist
        for directory in [self.SRC_DIR, self.OSS_FUZZ_DIR]:
            if not (self.task_dir / directory).is_dir():
                raise ChallengeTaskError(f"Missing required directory: {self.task_dir / directory}")

        self._helper_path = Path("infra/helper.py")
        if not (self.get_oss_fuzz_path() / self._helper_path).exists():
            raise ChallengeTaskError(f"Missing required file: {self.get_oss_fuzz_path() / self._helper_path}")

        self._check_python_path()

    def _check_dir_exists(self, path: Path) -> None:
        if not path.exists():
            raise ChallengeTaskError(f"Missing required directory: {path}")

        if not path.is_dir():
            raise ChallengeTaskError(f"Required directory is not a directory: {path}")

    def _find_first_dir(self, subpath: Path) -> Path | None:
        first_elem = next((self.task_dir / subpath).iterdir(), None)
        if first_elem is None:
            return None
        return first_elem.relative_to(self.task_dir)

    def get_source_subpath(self) -> Path | None:
        # TODO: "Review task structure and Challenge Task operations" Issue #74
        return self._find_first_dir(self.SRC_DIR)

    def get_diff_subpath(self) -> Path | None:
        # TODO: "Review task structure and Challenge Task operations" Issue #74
        return self._find_first_dir(self.DIFF_DIR)

    def get_oss_fuzz_subpath(self) -> Path | None:
        # TODO: "Review task structure and Challenge Task operations" Issue #74
        return self._find_first_dir(self.OSS_FUZZ_DIR)

    def _task_dir_compose_path(self, subpath_method: Callable[[], Path | None]) -> Path | None:
        subpath = subpath_method()
        if subpath is None:
            return None
        return self.task_dir / subpath

    def get_source_path(self) -> Path | None:
        return self._task_dir_compose_path(self.get_source_subpath)

    def get_diff_path(self) -> Path | None:
        return self._task_dir_compose_path(self.get_diff_subpath)

    def get_oss_fuzz_path(self) -> Path | None:
        return self._task_dir_compose_path(self.get_oss_fuzz_subpath)

    def get_build_dir(self) -> Path | None:
        return self.get_oss_fuzz_path() / "build" / "out" / self.project_name

    def get_diffs(self) -> list[Path]:
        return get_diffs(self.get_diff_path())

    def _check_python_path(self) -> None:
        """Check if the configured python_path is available in system PATH."""
        try:
            subprocess.run([self.python_path, "--version"], check=False, capture_output=True, text=True)
        except Exception as e:
            raise ChallengeTaskError(f"Python executable couldn't be run: {self.python_path}") from e

    @property
    def task_dir(self) -> Path:
        if self.local_task_dir is None:
            return Path(self.read_only_task_dir)
        return Path(self.local_task_dir)

    @property
    def name(self) -> str:
        return self.project_name

    def read_write_decorator(func: Callable) -> Callable:
        """Decorator to check if the task is read-only."""

        def wrapper(self, *args: Any, **kwargs: Any) -> Any:
            if self.local_task_dir is None:
                raise ChallengeTaskError("Challenge Task is read-only, cannot perform this operation")
            return func(self, *args, **kwargs)

        return wrapper

    def _add_optional_arg(self, cmd: list[str], flag: str, arg: Any | None):
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

    def _log_output_line(self, current_line: bytes, new_data: bytes) -> bytes:
        current_line += new_data
        line_to_print = b""
        if b"\n" in current_line:
            line_to_print = current_line[: current_line.index(b"\n")]
            current_line = current_line[current_line.index(b"\n") + 1 :]
            logger.debug(line_to_print.decode())

        return current_line

    def _run_helper_cmd(self, cmd: list[str]) -> CommandResult:
        try:
            logger.debug(f"Running command (cwd={self.task_dir / self.get_oss_fuzz_subpath()}): {' '.join(cmd)}")
            process = subprocess.Popen(  # noqa: S603
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                cwd=self.task_dir / self.get_oss_fuzz_subpath(),
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
                    current_output_line = self._log_output_line(current_output_line, stdout_line)
                    stdout += stdout_line

                if stderr_line:
                    current_error_line = self._log_output_line(current_error_line, stderr_line)
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
            logger.error(f"Command failed (cwd={self.task_dir / self.get_oss_fuzz_subpath()}): {' '.join(cmd)}")
            return CommandResult(
                success=False,
                returncode=None,
                error=e.stderr if e.stderr else None,
                output=e.stdout if e.stdout else None,
            )
        except Exception as e:
            logger.exception(f"Command failed (cwd={self.task_dir / self.get_oss_fuzz_subpath()}): {' '.join(cmd)}")
            return CommandResult(success=False, returncode=None, error=str(e), output=None)

    @read_write_decorator
    def build_image(
        self,
        *,
        pull_latest_base_image: bool = False,
        cache: bool | None = None,
        architecture: str | None = None,
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
        architecture: str | None = None,
        engine: str | None = None,
        sanitizer: str | None = None,
        env: Dict[str, str] | None = None,
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
        cmd = self._get_helper_cmd(
            "build_fuzzers",
            self.project_name,
            str((self.task_dir / self.get_source_subpath()).absolute()) if use_source_dir else None,
            architecture=architecture,
            engine=engine,
            sanitizer=sanitizer,
            e=env,
        )

        return self._run_helper_cmd(cmd)

    @read_write_decorator
    def build_fuzzers_with_cache(
        self,
        use_source_dir: bool = True,
        *,
        architecture: str | None = None,
        engine: str | None = None,
        sanitizer: str | None = None,
        pull_latest_base_image: bool = True,
        env: Dict[str, str] | None = None,
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
        )

    @read_write_decorator
    def check_build(
        self,
        *,
        architecture: str | None = None,
        engine: str | None = None,
        sanitizer: str | None = None,
        env: Dict[str, str] | None = None,
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
        architecture: str | None = None,
        env: Dict[str, str] | None = None,
    ) -> ReproduceResult:
        logger.info(
            "Reproducing POV for project %s | fuzzer_name=%s | crash_path=%s | fuzzer_args=%s | architecture=%s | env=%s",
            self.project_name,
            fuzzer_name,
            crash_path,
            fuzzer_args,
            architecture,
            env,
        )
        cmd = self._get_helper_cmd(
            "reproduce",
            self.project_name,
            fuzzer_name,
            str(crash_path.absolute()),
            fuzzer_args,
            architecture=architecture,
            e=env,
        )

        return ReproduceResult(self._run_helper_cmd(cmd))

    @read_write_decorator
    def run_coverage(
        self,
        harness_name: str,
        corpus_dir: str,
        package_name: str,
        architecture: str | None = None,
        env: Dict[str, str] | None = None,
    ) -> CommandResult:
        logger.info(
            "Running coverage for project %s | harness_name=%s | corpus_dir=%s | package_name=%s | architecture=%s | env=%s",
            self.project_name,
            harness_name,
            corpus_dir,
            package_name,
            architecture,
            env,
        )
        args = [
            "coverage",
            "--corpus-dir",
            corpus_dir,
            "--fuzz-target",
            harness_name,
            "--no-serve",
            package_name,
        ]
        cmd = self._get_helper_cmd(*args, e=env, architecture=architecture)
        return self._run_helper_cmd(cmd)

    @read_write_decorator
    def apply_patch_diff(self, diff_file: Path | None = None) -> bool:
        """Apply the  patch diff to the source code."""
        try:
            if diff_file is None:
                # Find all .patch and .diff files in the directory
                diff_files = self.get_diffs()
                if not diff_files:
                    return False
            else:
                diff_files = [diff_file]

            for diff_file in diff_files:
                logger.info(f"[task {self.task_dir}] Applying diff file: {diff_file}")

                # Use patch command to apply the patch
                subprocess.run(
                    [
                        "patch",
                        "-p1",
                        "-d",
                        str(self.get_source_path()),
                    ],
                    input=diff_file.read_text(),
                    text=True,
                    capture_output=True,
                    check=True,
                    timeout=10,
                )

                logger.info(f"[task {self.task_dir}] Successfully applied patch {diff_file}")

            return True
        except FileNotFoundError as e:
            logger.error(f"[task {self.task_dir}] File not found: {str(e)}")
            raise ChallengeTaskError(f"[task {self.task_dir}] File not found: {str(e)}") from e
        except subprocess.CalledProcessError as e:
            logger.error(f"[task {self.task_dir}] Error applying diff: {str(e)}")
            logger.debug(f"[task {self.task_dir}] Error returncode: {e.returncode}")
            logger.debug(f"[task {self.task_dir}] Error stdout: {e.stdout}")
            logger.debug(f"[task {self.task_dir}] Error stderr: {e.stderr}")
            raise ChallengeTaskError(f"[task {self.task_dir}] Error applying diff: {str(e)}") from e
        except Exception as e:
            logger.exception(f"[task {self.task_dir}] Error applying diff: {str(e)}")
            raise ChallengeTaskError(f"[task {self.task_dir}] Error applying diff: {str(e)}") from e

    @contextmanager
    def get_rw_copy(self, work_dir: PathLike | None = None, delete: bool = True) -> Iterator[ChallengeTask]:
        """Create a copy of this task in a new writable directory.
        Returns a context manager that yields a new ChallengeTask instance pointing to the new copy.

        Example:
            with task.get_rw_copy() as local_task:
                local_task.build_fuzzers()
        """
        if self.local_task_dir is not None:
            yield self
            return

        work_dir = Path(work_dir) if work_dir else None
        with create_tmp_dir(work_dir, delete, prefix=self.task_dir.name + "-") as tmp_dir:
            # Copy the entire task directory to the temporary location
            logger.info(f"Copying task directory {self.task_dir} to {tmp_dir}")
            copyanything(self.task_dir, tmp_dir, symlinks=True)

            # Create a new ChallengeTask instance pointing to the copy
            copied_task = ChallengeTask(
                read_only_task_dir=self.read_only_task_dir,
                project_name=self.project_name,
                python_path=self.python_path,
                local_task_dir=tmp_dir,
            )

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
            suffix = suffix if suffix is not None else str(uuid.uuid4())[:16]
            new_name = f"{self.read_only_task_dir.name}-{suffix}"
            try:
                logger.info(f"Committing task {self.local_task_dir} to {new_name}")
                new_local_task_dir = self.local_task_dir.rename(self.local_task_dir.parent / new_name)
                logger.info(f"Committed task {self.local_task_dir} to {new_name}")
                break
            except OSError as e:
                if i == max_retries - 1:
                    raise ChallengeTaskError("Failed to commit task") from e

                logger.error(
                    f"Failed to commit task {self.local_task_dir} to {new_name}. Retrying with a random suffix..."
                )
                suffix = None

        self.local_task_dir = new_local_task_dir

    @read_write_decorator
    def restore(self) -> None:
        """Restore the task from the original read-only task directory (if
        different from the local task directory)."""
        if self.read_only_task_dir == self.local_task_dir:
            raise ChallengeTaskError("Task cannot be restored, it doesn't have a local task directory")

        logger.info(f"Restoring task from {self.read_only_task_dir} to {self.local_task_dir}")
        if self.local_task_dir.exists():
            logger.info(f"Removing local task directory {self.local_task_dir}")
            shutil.rmtree(self.local_task_dir)

        logger.info(f"Restoring task {self.read_only_task_dir} to {self.local_task_dir}")
        copyanything(self.read_only_task_dir, self.local_task_dir, symlinks=True)
