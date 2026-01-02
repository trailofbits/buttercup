from pathlib import Path
import subprocess
import threading
from dataclasses import dataclass
from typing import Optional, Callable, abstractmethod
import queue
import time
import uuid
import shlex

class DockerInteractiveError(Exception):
    """Base class for Challenge Task errors."""

@dataclass
class CommandResult:
    lines: list[str]
    exit_code: Optional[int] = None



CompletionFn = Callable[[list[str]], bool]

class DockerInteractive: 
    docker_cmd: list[str]
    docker_process: subprocess.Popen
    output_thread: threading.Thread
    out_q: queue.Queue[str]
    reader_thread: threading.Thread
    stop_reader: threading.Event
    container_name: str

    def __init__(self, container_image: str, mount_dirs: dict[Path, Path], start_command: list[str]):
        """Create a docker interactive session.
        """
        if container_image == "":
            raise DockerInteractiveError("Container image is required")
        
        self.container_name = f"docker_interactive_{uuid.uuid4()}"

        docker_cmd = ["docker", "run", "--privileged", "--shm-size=2g", "-i", "--name", self.container_name]
        if mount_dirs:
            for src, dst in mount_dirs.items():
                docker_cmd += ["-v", f"{src.resolve().as_posix()}:{dst.as_posix()}"]

        docker_cmd += [container_image]
        docker_cmd+= [shlex.join(start_command)]


        self.docker_cmd = docker_cmd
        self.docker_process: Optional[subprocess.Popen[str]] = None

        self.out_q: "queue.Queue[str]" = queue.Queue()
        self._reader_thread: Optional[threading.Thread] = None
        self._stop_reader = threading.Event()

    def run(self):
        """Run the docker interactive session.
        This starts the docker container, and spins up a thread to read the output from the container.
        """
        self.docker_process = subprocess.Popen(self.docker_cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
        if self.docker_process.stdout is None or self.docker_process.stdin is None:
            raise DockerInteractiveError("Failed to open pipes to docker process")

        self._reader_thread = threading.Thread(target=self._read_output_loop, daemon=True)
        self._reader_thread.start()
    
    def _read_output_loop(self):
        """Read the output from the docker container.
        """
        assert self.docker_process and self.docker_process.stdout
        for line in self.docker_process.stdout:
            if self._stop_reader.is_set():
                break
            self.out_q.put(line.rstrip("\n"))
        self.out_q.put("<EOF>") 
    def close(self) -> None:
        self._stop_reader.set()
        if self.docker_process is not None:
            try:
                self.docker_process.terminate()
            except Exception:
                pass
            self.docker_process = None 


    def send_command(self, command: str, completion: CompletionFn, timeout: float = 10.0) -> CommandResult:
        """Send a command to the docker container.
        """
        if self.docker_process is None:
            raise DockerInteractiveError("Docker process is not running, call run() first")
        self.docker_process.stdin.write(command + "\n")
        self.docker_process.stdin.flush()
        lines: list[str] = []

        start_time = time.time()
        end_time = start_time + timeout
        alive = True
        while time.time() < end_time:
            remaining_time = end_time - time.time()
            if remaining_time <= 0:
                lines.append(f"\n***timout waiting for end of output after {timeout} seconds***")
                int_lines = self.interrupt()
                lines.extend(int_lines)
                break
            try:
                line = self.out_q.get(timeout=min(remaining_time, 0.1))
            except queue.Empty:
                continue
            lines.append(line)
            if line == "<EOF>":
                break
            if completion(lines):
                break
        return CommandResult(lines=lines)

    def _docker(self, args: list[str]) -> None:
        """Run a docker command (helper for interrupt methods).
        
        Args:
            args: Docker command arguments (e.g., ["kill", "-s", "INT", "container_name"])
        """
        import subprocess
        cmd = ["docker"] + args
        subprocess.run(cmd, capture_output=True, check=False)
    
    def interrupt(self) -> list[str]:
        """Interrupt the docker process. Overwrite this with program logic, return any lines you need to explain what the interuption did.
        """
        raise DockerInteractiveError("Interruption not implemented, killing process, likely due to cmd timeout")
        return []
