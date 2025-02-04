from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Any, Callable
from os import PathLike
import logging
import subprocess
import shutil
from buttercup.common.logger import setup_logging
from buttercup.common.utils import create_tmp_dir, copyanything
from contextlib import contextmanager
from typing import Iterator


@dataclass
class CommandResult:
    success: bool
    error: bytes | None = None
    output: bytes | None = None


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

    logger: logging.Logger = field(default_factory=lambda: setup_logging(__name__))
    _helper_path: Path = field(init=False)

    def __post_init__(self) -> None:
        self.read_only_task_dir = Path(self.read_only_task_dir)
        self.local_task_dir = Path(self.local_task_dir) if self.local_task_dir else None
        self.project_name = self.project_name
        self.python_path = Path(self.python_path)

        if not self.task_dir.exists():
            raise ValueError(f"Task directory does not exist: {self.task_dir}")

        # Verify required directories exist
        for directory in [self.SRC_DIR, self.OSS_FUZZ_DIR]:
            if not (self.task_dir / directory).is_dir():
                raise ValueError(f"Missing required directory: {self.task_dir / directory}")

        self._helper_path = self.get_oss_fuzz_subpath() / "infra/helper.py"
        if not (self.task_dir / self._helper_path).exists():
            raise ValueError(f"Missing required file: {self.task_dir / self._helper_path}")

        self._check_python_path()

    def _find_first_dir(self, subpath: Path) -> Path | None:
        first_elem = next((self.task_dir / subpath).iterdir(), None)
        if first_elem is None:
            return None
        return first_elem.relative_to(self.task_dir)

    def get_source_subpath(self) -> Path | None:
        # NOTE: assume the first directory inside the `src` subdir is the correct one
        return self._find_first_dir(self.SRC_DIR)

    def get_diff_subpath(self) -> Path | None:
        # NOTE: assume the first directory inside the `diff` subdir is the correct one
        return self._find_first_dir(self.DIFF_DIR)

    def get_oss_fuzz_subpath(self) -> Path | None:
        # NOTE: assume the first directory inside the `fuzz-tooling` subdir is the correct one
        return self._find_first_dir(self.OSS_FUZZ_DIR)

    def _compose_path(self, subpath_method: Callable[[], Path | None]) -> Path | None:
        subpath = subpath_method()
        if subpath is None:
            return None
        return self.task_dir / subpath

    def get_source_path(self) -> Path | None:
        return self._compose_path(self.get_source_subpath)

    def get_diff_path(self) -> Path | None:
        return self._compose_path(self.get_diff_subpath)

    def get_oss_fuzz_path(self) -> Path | None:
        return self._compose_path(self.get_oss_fuzz_subpath)

    def _check_python_path(self) -> CommandResult:
        """Check if the configured python_path is available in system PATH."""
        try:
            result = subprocess.run([self.python_path, "--version"], check=False, capture_output=True, text=True)
            return CommandResult(
                success=result.returncode == 0,
                error=result.stderr if result.returncode != 0 else None,
                output=result.stdout,
            )
        except FileNotFoundError:
            return CommandResult(success=False, error=f"Python executable not found at: {self.python_path}")

    @property
    def task_dir(self) -> Path:
        if self.local_task_dir is None:
            return Path(self.read_only_task_dir)
        return Path(self.local_task_dir)

    def read_write_decorator(func: Callable) -> Callable:
        """Decorator to check if the task is read-only."""

        def wrapper(self, *args: Any, **kwargs: Any) -> Any:
            if self.local_task_dir is None:
                raise RuntimeError("Challenge Task is read-only, cannot perform this operation")
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
        cmd = [str(self.python_path), "infra/helper.py", helper_cmd]
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
            self.logger.debug(line_to_print.decode())

        return current_line

    def _run_helper_cmd(self, cmd: list[str]) -> CommandResult:
        try:
            self.logger.debug(f"Running command (cwd={self.task_dir / self.get_oss_fuzz_subpath()}): {' '.join(cmd)}")
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
                error=stderr,
                output=stdout,
            )
        except subprocess.CalledProcessError as e:
            self.logger.error(f"Command failed (cwd={self.task_dir / self.get_oss_fuzz_subpath()}): {' '.join(cmd)}")
            return CommandResult(
                success=False, error=e.stderr if e.stderr else None, output=e.stdout if e.stdout else None
            )
        except Exception as e:
            self.logger.exception(
                f"Command failed (cwd={self.task_dir / self.get_oss_fuzz_subpath()}): {' '.join(cmd)}"
            )
            return CommandResult(success=False, error=str(e), output=None)

    @read_write_decorator
    def build_image(
        self,
        *,
        pull_latest_base_image: bool = False,
        cache: bool | None = None,
        architecture: str | None = None,
    ) -> CommandResult:
        self.logger.info(
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
        use_cache: bool = True,
    ) -> CommandResult:
        if use_cache:
            check_build_res = self.check_build(architecture=architecture, engine=engine, sanitizer=sanitizer, env=env)
            if check_build_res.success:
                self.logger.info("Build is up to date, skipping building fuzzers")
                return CommandResult(
                    success=True,
                    error=None,
                    output=None,
                )

        self.logger.info(
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
    def check_build(
        self,
        *,
        architecture: str | None = None,
        engine: str | None = None,
        sanitizer: str | None = None,
        env: Dict[str, str] | None = None,
    ) -> CommandResult:
        self.logger.info(
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
    ) -> CommandResult:
        self.logger.info(
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

        return self._run_helper_cmd(cmd)

    @contextmanager
    def get_rw_copy(
        self, work_dir: PathLike | None = None, delete: bool = True, clean_on_failure: bool = True
    ) -> Iterator[ChallengeTask]:
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
            self.logger.info(f"Copying task directory {self.task_dir} to {tmp_dir}")
            copyanything(self.task_dir, tmp_dir, symlinks=True)

            # Create a new ChallengeTask instance pointing to the copy
            copied_task = ChallengeTask(
                read_only_task_dir=self.read_only_task_dir,
                project_name=self.project_name,
                python_path=self.python_path,
                logger=self.logger,
                local_task_dir=tmp_dir,
            )

            try:
                yield copied_task
            finally:
                # If the build failed, clean the local task directory if
                # requested, otherwise keep the `delete` behaviour for the whole
                # `work_dir``
                try:
                    if clean_on_failure:
                        self.clean_task_dir()
                except Exception:
                    self.logger.exception("Failed to clean task directory")
                    self.logger.warning("Ignoring the error, continuing...")

    def clean_task_dir(self) -> None:
        """Clean the local task directory if this is not the original task directory."""
        if self.local_task_dir is None or self.local_task_dir == self.read_only_task_dir:
            return

        shutil.rmtree(self.local_task_dir, ignore_errors=True)
