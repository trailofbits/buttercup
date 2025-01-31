from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Any
import logging
import subprocess
from buttercup.common.logger import setup_logging


@dataclass
class CommandResult:
    success: bool
    error: bytes | None = None
    output: bytes | None = None


@dataclass
class ChallengeTask:
    """Class to manage Challenge Tasks."""

    task_dir: Path | str
    project_name: str
    oss_fuzz_subpath: Path | str
    source_subpath: Path | str
    diffs_subpath: Path | str | None = None
    python_path: Path | str = Path("python")

    logger: logging.Logger = field(default_factory=lambda: setup_logging(__name__))
    _helper_path: Path = field(init=False)

    def __post_init__(self) -> None:
        self.task_dir = Path(self.task_dir)
        self.oss_fuzz_subpath = Path(self.oss_fuzz_subpath)
        self.source_subpath = Path(self.source_subpath)
        self.diffs_subpath = Path(self.diffs_subpath) if self.diffs_subpath else None
        self.python_path = Path(self.python_path)

        if not self.task_dir.exists():
            raise ValueError(f"Task directory does not exist: {self.task_dir}")

        # Verify required directories exist
        for directory in [self.oss_fuzz_subpath, self.source_subpath]:
            if not (self.task_dir / directory).is_dir():
                raise ValueError(f"Missing required directory: {self.task_dir / directory}")

        self._helper_path = self.oss_fuzz_subpath / "infra/helper.py"
        if not (self.task_dir / self._helper_path).exists():
            raise ValueError(f"Missing required file: {self.task_dir / self._helper_path}")

        self._check_python_path()

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
            self.logger.debug(f"Running command (cwd={self.task_dir / self.oss_fuzz_subpath}): {' '.join(cmd)}")
            process = subprocess.Popen(  # noqa: S603
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                cwd=self.task_dir / self.oss_fuzz_subpath,
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
            self.logger.error(f"Command failed (cwd={self.task_dir / self.oss_fuzz_subpath}): {' '.join(cmd)}")
            return CommandResult(
                success=False, error=e.stderr if e.stderr else None, output=e.stdout if e.stdout else None
            )
        except Exception as e:
            self.logger.exception(f"Command failed (cwd={self.task_dir / self.oss_fuzz_subpath}): {' '.join(cmd)}")
            return CommandResult(success=False, error=str(e), output=None)

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

    def build_fuzzers(
        self,
        use_source_dir: bool = True,
        *,
        architecture: str | None = None,
        engine: str | None = None,
        sanitizer: str | None = None,
        env: Dict[str, str] | None = None,
    ) -> CommandResult:
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
            str((self.task_dir / self.source_subpath).absolute()) if use_source_dir else None,
            architecture=architecture,
            engine=engine,
            sanitizer=sanitizer,
            e=env,
        )

        return self._run_helper_cmd(cmd)

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


def main():
    from pydantic_settings import BaseSettings, CliSubCommand, get_subcommand
    from pydantic import BaseModel

    class BuildImageCommand(BaseModel):
        pull_latest_base_image: bool = False
        cache: bool | None = None
        architecture: str | None = None

    class BuildFuzzersCommand(BaseModel):
        architecture: str | None = None
        engine: str | None = None
        sanitizer: str | None = None
        env: Dict[str, str] | None = None

    class CheckBuildCommand(BaseModel):
        architecture: str | None = None
        engine: str | None = None
        sanitizer: str | None = None
        env: Dict[str, str] | None = None

    class ReproducePovCommand(BaseModel):
        fuzzer_name: str
        crash_path: Path
        fuzzer_args: list[str] | None = None
        architecture: str | None = None
        env: Dict[str, str] | None = None

    class Settings(BaseSettings):
        task_dir: Path
        project_name: str
        oss_fuzz_subpath: Path = Path("fuzz-tooling")
        source_subpath: Path = Path("source")
        diffs_subpath: Path | None = None
        python_path: Path = Path("python")

        build_image: CliSubCommand[BuildImageCommand]
        build_fuzzers: CliSubCommand[BuildFuzzersCommand]
        check_build: CliSubCommand[CheckBuildCommand]
        reproduce_pov: CliSubCommand[ReproducePovCommand]

        class Config:
            env_prefix = "BUTTERCUP_CHALLENGE_TASK_"
            env_file = ".env"
            cli_parse_args = True
            nested_model_default_partial_update = True
            env_nested_delimiter = "__"
            extra = "allow"

    settings = Settings()
    logger = setup_logging(__name__, "DEBUG")
    task = ChallengeTask(
        task_dir=settings.task_dir,
        project_name=settings.project_name,
        oss_fuzz_subpath=settings.oss_fuzz_subpath,
        source_subpath=settings.source_subpath,
        diffs_subpath=settings.diffs_subpath,
        python_path=settings.python_path,
        logger=logger,
    )

    subcommand = get_subcommand(settings)
    if isinstance(subcommand, BuildImageCommand):
        result = task.build_image(
            pull_latest_base_image=subcommand.pull_latest_base_image,
            cache=subcommand.cache,
            architecture=subcommand.architecture,
        )
    elif isinstance(subcommand, BuildFuzzersCommand):
        result = task.build_fuzzers(
            architecture=subcommand.architecture,
            engine=subcommand.engine,
            sanitizer=subcommand.sanitizer,
            env=subcommand.env,
        )
    elif isinstance(subcommand, CheckBuildCommand):
        result = task.check_build(
            architecture=subcommand.architecture,
            engine=subcommand.engine,
            sanitizer=subcommand.sanitizer,
            env=subcommand.env,
        )
    elif isinstance(subcommand, ReproducePovCommand):
        result = task.reproduce_pov(
            fuzzer_name=subcommand.fuzzer_name,
            crash_path=subcommand.crash_path,
            fuzzer_args=subcommand.fuzzer_args,
            architecture=subcommand.architecture,
            env=subcommand.env,
        )

    print("Command result:", result.success)
