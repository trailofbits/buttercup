import logging
import queue
import subprocess
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


class DockerInteractiveError(Exception):
    """Base class for Challenge Task errors."""


@dataclass
class CommandResult:
    lines: list[str]
    exit_code: int | None = None


CompletionFn = Callable[[list[str]], bool]


class DockerInteractive:
    docker_cmd: list[str]
    docker_process: subprocess.Popen[str] | None
    output_thread: threading.Thread
    out_q: queue.Queue[str]
    reader_thread: threading.Thread
    stop_reader: threading.Event
    container_name: str
    global_timeout: float

    def __init__(
        self,
        container_image: str,
        mount_dirs: dict[Path, Path],
        start_command: list[str],
        global_timeout: float = 600.0,
    ):
        """Create a docker interactive session."""
        if container_image == "":
            raise DockerInteractiveError("Container image is required")

        self.container_name = f"docker_interactive_{uuid.uuid4()}"
        logger.info(
            "Initializing DockerInteractive session: container=%s, timeout=%.1fs", container_image, global_timeout
        )

        docker_cmd = ["docker", "run", "--privileged", "--shm-size=2g", "-i", "--name", self.container_name]
        if mount_dirs:
            for src, dst in mount_dirs.items():
                docker_cmd += ["-v", f"{src.resolve().as_posix()}:{dst.as_posix()}"]
                logger.debug("Mounting %s -> %s", src, dst)

        docker_cmd += [container_image]
        # Extend with command arguments directly (don't join into a single string)
        docker_cmd.extend(start_command)
        logger.debug("Docker command: %s", " ".join(docker_cmd))

        self.docker_cmd = docker_cmd
        self.docker_process: subprocess.Popen[str] | None = None

        self.out_q: queue.Queue[str] = queue.Queue()
        self._reader_thread: threading.Thread | None = None
        self._stop_reader = threading.Event()
        self.global_timeout = global_timeout
        self._session_start_time: float | None = None

    def run(self) -> None:
        """Run the docker interactive session.
        This starts the docker container, and spins up a thread to read the output from the container.
        """
        logger.info("Starting Docker interactive session: container_name=%s", self.container_name)
        self.docker_process = subprocess.Popen(
            self.docker_cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        if self.docker_process.stdout is None or self.docker_process.stdin is None:
            logger.error("Failed to open pipes to docker process")
            raise DockerInteractiveError("Failed to open pipes to docker process")

        self._session_start_time = time.time()
        logger.debug("Session started at %s, timeout=%.1fs", self._session_start_time, self.global_timeout)
        self._reader_thread = threading.Thread(target=self._read_output_loop, daemon=True)
        self._reader_thread.start()
        logger.debug("Started output reader thread")
        self._timeout_thread = threading.Thread(target=self._check_timeout, daemon=True)
        self._timeout_thread.start()
        logger.debug("Started timeout checker thread")

    def _read_output_loop(self) -> None:
        """Read the output from the docker container."""
        logger.debug("Output reader thread started")
        assert self.docker_process and self.docker_process.stdout
        line_count = 0
        try:
            for line in self.docker_process.stdout:
                if self._stop_reader.is_set():
                    logger.debug("Output reader thread stopping (stop flag set), read %d lines", line_count)
                    break
                self.out_q.put(line.rstrip("\n"))
                logger.debug("Read line: %s", line.rstrip("\n"))
                line_count += 1
        except Exception as e:
            logger.warning("Error reading from docker process stdout: %s", e)
        finally:
            # Check if process has exited
            if self.docker_process:
                returncode = self.docker_process.poll()
                if returncode is not None:
                    logger.warning(
                        "Docker process exited with returncode=%d (read %d lines before exit)", returncode, line_count
                    )
                else:
                    logger.debug(
                        "Output reader thread finished, read %d lines total (process still running)", line_count
                    )
            else:
                logger.debug("Output reader thread finished, read %d lines total (process is None)", line_count)
            self.out_q.put("<EOF>")

    def _check_timeout(self) -> None:
        """Check if the global timeout has been exceeded. Should be run in a thread."""
        logger.debug("Timeout checker thread started")
        if self._session_start_time is None:
            logger.warning("Timeout checker started but session_start_time is None")
            return
        elapsed_time = time.time() - self._session_start_time
        while elapsed_time < self.global_timeout:
            time.sleep(1)
            elapsed_time = time.time() - self._session_start_time
        logger.warning("Global timeout exceeded: elapsed=%.1fs, limit=%.1fs", elapsed_time, self.global_timeout)
        self.out_q.put(
            f"*** Global timeout exceeded after {elapsed_time:.1f} seconds (limit: {self.global_timeout:.1f}s) ***"
        )
        self._stop_reader.set()
        self.close()

    def close(self) -> None:
        logger.info("Closing Docker interactive session: container_name=%s", self.container_name)
        self._stop_reader.set()
        if self.docker_process is not None:
            try:
                logger.debug("Terminating docker process")
                self.docker_process.terminate()
            except Exception as e:
                logger.warning("Error terminating docker process: %s", e)
            self.docker_process = None
        logger.debug("Docker interactive session closed")

    def send_command(self, command: str, completion: CompletionFn, timeout: float = 10.0) -> CommandResult:
        """Send a command to the docker container."""
        if self.docker_process is None:
            logger.error("Attempted to send command but docker process is not running")
            raise DockerInteractiveError("Docker process is not running, call run() first")

        # Check if process has exited
        returncode = self.docker_process.poll()
        if returncode is not None:
            logger.error(
                "Docker process has already exited with returncode=%d, cannot send command: %s", returncode, command
            )
            raise DockerInteractiveError(f"Docker process has exited (returncode={returncode}), cannot send command")

        if self.docker_process.stdin is None:
            logger.error("Docker process stdin is None, cannot send command: %s", command)
            raise DockerInteractiveError("Docker process stdin is not available, cannot send command")

        logger.debug("Sending command: %s (timeout=%.1fs)", command, timeout)
        try:
            self.docker_process.stdin.write(command + "\n")
            self.docker_process.stdin.flush()
        except BrokenPipeError as e:
            logger.error("Broken pipe when sending command (process likely exited): %s", command)
            raise DockerInteractiveError(f"Broken pipe - docker process has exited, cannot send command: {e}") from e
        lines: list[str] = []

        start_time = time.time()
        end_time = start_time + timeout
        # Use a smaller polling interval for faster synchronization (10ms instead of 100ms)
        poll_interval = 0.0005
        while time.time() < end_time:
            remaining_time = end_time - time.time()
            if remaining_time <= 0:
                logger.warning("Command timeout after %.1fs: %s", timeout, command)
                lines.append(f"\n***timout waiting for end of output after {timeout} seconds***")
                int_lines = self.interrupt()
                lines.extend(int_lines)
                break
            try:
                line = self.out_q.get(timeout=min(remaining_time, poll_interval))
            except queue.Empty:
                continue
            lines.append(line)
            if line == "<EOF>":
                logger.debug("Received EOF, command completed: %s", command)
                break
            if completion(lines):
                logger.debug("Completion function returned True, command completed: %s", command)
                break

        elapsed = time.time() - start_time
        logger.debug("Command completed: %s (elapsed=%.2fs, lines=%d)", command, elapsed, len(lines))
        return CommandResult(lines=lines)

    def _docker(self, args: list[str]) -> None:
        """Run a docker command (helper for interrupt methods).

        Args:
            args: Docker command arguments (e.g., ["kill", "-s", "INT", "container_name"])
        """
        import subprocess

        cmd = ["docker"] + args
        logger.debug("Executing docker command: %s", " ".join(cmd))
        result = subprocess.run(cmd, capture_output=True, check=False)
        if result.returncode != 0:
            logger.warning("Docker command failed (returncode=%d): %s", result.returncode, " ".join(cmd))

    def interrupt(self) -> list[str]:
        """Interrupt the docker process. Overwrite this with program logic,
        return any lines you need to explain what the interuption did."""
        raise DockerInteractiveError("Interruption not implemented, killing process, likely due to cmd timeout")
