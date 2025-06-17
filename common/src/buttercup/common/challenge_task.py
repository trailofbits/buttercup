from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Any, Callable
from os import PathLike
import contextlib
import logging
import shlex
import os
from contextlib import contextmanager
import tempfile
import shutil
import uuid
import subprocess
import re
from buttercup.common.task_meta import TaskMeta
from buttercup.common.utils import copyanything, get_diffs
from typing import Iterator
import buttercup.common.node_local as node_local
from packaging.version import Version

logger = logging.getLogger(__name__)


@contextmanager
def create_tmp_dir(
    challenge: ChallengeTask, work_dir: Path | None, delete: bool = True, prefix: str | None = None
) -> Iterator[Path]:
    """Create a temporary directory inside a working dir and either keep or
    delete it after use."""
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

    pass


FAILURE_ERR_RESULT = 55


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

    def did_run(self) -> bool:
        """Determine if the fuzzer at least ran"""
        return bool(
            (self.command_result.output and b"INFO: Seed: " in self.command_result.output)
            or (self.command_result.error and b"INFO: Seed: " in self.command_result.error)
        )

    # This is intended to encapsulate heuristics for determining if a run caused a crash
    # Could grep for strings from sanitizers as well
    def did_crash(self) -> bool:
        """Determine if a crash occurred

        Conditions:
         - Nonzero return code
         - Fuzzer ran (assumes libfuzzer or Jazzer)
        """
        return bool(self.did_run() and self.command_result.returncode not in [None, 0, FAILURE_ERR_RESULT])


@dataclass
class ChallengeTask:
    """Class to manage Challenge Tasks."""

    read_only_task_dir: PathLike
    task_meta: TaskMeta = field(init=False)
    python_path: PathLike = Path("python")
    local_task_dir: PathLike | None = None

    SRC_DIR = "src"
    DIFF_DIR = "diff"
    OSS_FUZZ_DIR = "fuzz-tooling"

    OSS_FUZZ_CONTAINER_ORG: str = field(default_factory=lambda: os.getenv("OSS_FUZZ_CONTAINER_ORG", "gcr.io/oss-fuzz"))

    MAX_COMMIT_RETRIES = 3

    WORKDIR_REGEX = re.compile(r"\s*WORKDIR\s*([^\s]+)")

    _helper_path: Path = field(init=False)
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
        if not (self.get_oss_fuzz_path() / self._helper_path).exists():
            raise ChallengeTaskError(f"Missing required file: {self.get_oss_fuzz_path() / self._helper_path}")

        self._check_python_path()

    def _local_ro_dir(self, path: Path) -> Path:
        """Return the local path to the read-only task directory.

        If the path doesn't exist, it will be downloaded from the remote storage"""
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

    def _find_first_dir(self, subpath: Path) -> Path | None:
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

    def is_delta_mode(self) -> bool:
        return len(self.get_diffs()) > 0

    def _check_python_path(self) -> None:
        """Check if the configured python_path is available in system PATH."""
        try:
            subprocess.run([self.python_path, "--version"], check=False, capture_output=True, text=True)
        except Exception as e:
            raise ChallengeTaskError(f"Python executable couldn't be run: {self.python_path}") from e

    def _workdir_from_lines(self, lines: list[str], default=Path("/src")) -> Path:
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

    def workdir_from_dockerfile(self) -> Path:
        """Parses WORKDIR from the Dockerfile for the given project."""
        # NOTE: This is extracted and adapted from the OSS-Fuzz repository
        # https://github.com/google/oss-fuzz/blob/3beb664440843f159e38ef66eb68a7cbd2704dad/infra/helper.py#L704
        default_workdir = Path("/src") / self.project_name
        try:
            with open(self.get_oss_fuzz_path() / "projects" / self.project_name / "Dockerfile") as file_handle:
                lines = file_handle.readlines()

            return self._workdir_from_lines(lines, default=default_workdir)
        except FileNotFoundError:
            return default_workdir

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
        self, cmd: list[str], cwd: Path | None = None, log: bool = True, env_helper: Dict[str, str] | None = None
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

    def _run_helper_cmd(self, cmd: list[str], env_helper: Dict[str, str] | None = None) -> CommandResult:
        return self._run_cmd(cmd, cwd=self.task_dir / self.get_oss_fuzz_subpath(), env_helper=env_helper)

    def _get_base_runner_version(self) -> Version | None:
        """The base-runner image tag is hardcoded in infra/helper.py."""
        grep_cmd = ["grep", "BASE_IMAGE_TAG =", str(self._helper_path)]
        try:
            result = self._run_helper_cmd(grep_cmd)
        except Exception as e:
            logger.exception(f"[task {self.task_dir}] Error grep'ing for base-runner version: {str(e)}")
            return None
        if not result.success:
            return None

        m = re.search(r"BASE_IMAGE_TAG = '([^']+)'", result.output.decode("utf-8"))
        if not m:
            return None

        try:
            base_runner_str = m.group(1).strip(":v")
            return Version(base_runner_str)
        except Exception as e:
            logger.exception(f"[task {self.task_dir}] Error parsing base-runner version: {str(e)}")
            return None

    def container_image(self) -> str:
        return f"{self.OSS_FUZZ_CONTAINER_ORG}/{self.project_name}"

    def container_src_dir(self) -> str:
        """
        Name of the src directory in the container (e.g. /src/FreeRDP -> FreeRDP).
        This assumes that the src directory is the same as the workdir.
        """
        return self.workdir_from_dockerfile().parts[-1]

    @read_write_decorator
    def exec_docker_cmd(
        self,
        cmd: list[str],
        mount_dirs: dict[Path, Path] | None = None,
        container_image: str | None = None,
        always_build_image: bool = False,
    ) -> CommandResult:
        """Execute a command inside a docker container. If not specified, the
        docker container is the oss-fuzz one."""
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
                    raise ChallengeTaskError(f"Failed to build image: {res.error}")

                self._image_built = True

            container_image = self.container_image()
            if mount_dirs is None:
                mount_dirs = {}
            mount_dirs.update({self.get_source_path(): self.workdir_from_dockerfile()})

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
        env_helper: Dict[str, str] | None = None,
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
            kwargs["mount_path"] = Path(f"/src/{self.focus}")

        cmd = self._get_helper_cmd(
            "build_fuzzers",
            self.project_name,
            str((self.task_dir / self.get_source_subpath()).absolute()) if use_source_dir else None,
            **kwargs,
        )

        return self._run_helper_cmd(cmd, env_helper=env_helper)

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
        env_helper: Dict[str, str] | None = None,
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
        architecture: str | None = None,
        engine: str | None = None,
        sanitizer: str | None = None,
        pull_latest_base_image: bool = True,
        env: Dict[str, str] | None = None,
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
        kwargs = {
            "architecture": architecture,
            "e": env,
        }
        if "aixcc" in self.OSS_FUZZ_CONTAINER_ORG:
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
        architecture: str | None = None,
        engine: str | None = None,
        sanitizer: str | None = None,
        env: Dict[str, str] | None = None,
    ) -> CommandResult:
        logger.info(
            "Running fuzzer for project %s | harness_name=%s | fuzzer_args=%s | corpus_dir=%s | architecture=%s | engine=%s | sanitizer=%s | env=%s",
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
        architecture: str | None = None,
        env: Dict[str, str] | None = None,
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

        if self.local_task_dir.exists():
            logger.debug(f"Removing local task directory {self.local_task_dir}")
            self._remove_dir(self.local_task_dir)

        copyanything(self.read_only_task_dir, self.local_task_dir, symlinks=True)
        logger.info(f"Restored task from {self.read_only_task_dir} to {self.local_task_dir}")

    def _remove_dir(self, path: Path) -> None:
        try:
            shutil.rmtree(path)
        except Exception:
            logger.warning("Error removing directory %s, trying from within the container...", path)
            res = self.exec_docker_cmd(
                ["rm", "-rf", f"/mnt/{path.name}"],
                mount_dirs={path.parent: Path("/mnt")},
                container_image="ubuntu:24.04",
            )
            if not res.success:
                logger.error("Failed to remove directory from docker: %s", res.output)
                raise ChallengeTaskError(f"Failed to remove directory from docker: {res.output}")

    def get_test_sh_script(self, test_sh_path: str) -> str:
        return f"""cp {test_sh_path} $SRC/test.sh && $SRC/test.sh"""

    @read_write_decorator
    def cleanup(self, directory: Path | None = None) -> None:
        """Clean up a ChallengeTask local directory."""
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
