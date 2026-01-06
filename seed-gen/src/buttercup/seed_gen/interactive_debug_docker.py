from buttercup.common.docker_interactive import DockerInteractive, CommandResult
import re
from pathlib import Path
import signal
import time
import queue
import subprocess
from typing import Callable
import tempfile

_MI_STOP_RE = re.compile(r"^\*stopped\b")  # MI async stop record
_MI_RESULT_RE = re.compile(r"^\d+\^(done|error|running)\b")

class InteractiveGDBDockerError(Exception):
    """Base class for InteractiveGDBDocker errors."""
_tok_prefix = re.compile(r"^\d+(?=[\^*+=~@&])")  # digits before a MI record marker

def strip_tok_prefix(line: str) -> str:
    return _tok_prefix.sub("", line)

from typing import Callable
import re

def mi_completion(token: int) -> Callable[[list[str]], bool]:
    # Tokened result record for *this* command.
    result_pat = re.compile(rf"^{token}\^(done|error|running)\b")
    stopped_pat = re.compile(r"^\*stopped\b")

    # GDB prompt in MI appears via console stream records:
    #   ~"(gdb) \n"
    #   ~"> \n"          (during 'commands' / define / etc.)
    prompt_pat = re.compile(r'^[~@&]"(?:\(gdb\)|>)')  # starts with (gdb) or > in a quoted stream

    saw_running = False
    saw_stopped = False

    def done(lines: list[str]) -> bool:
        nonlocal saw_running, saw_stopped

        for ln in lines:
            m = result_pat.match(ln)
            if m:
                kind = m.group(1)
                if kind in ("done", "error"):
                    # For non-running commands, the result record is enough.
                    return True
                if kind == "running":
                    saw_running = True
                    # keep reading until stop+prompt

            if saw_running and stopped_pat.match(ln):
                saw_stopped = True
                # don't return yet; prints can still follow

            # After a stop, wait until we see the prompt, which indicates GDB is ready.
            if saw_running and saw_stopped and prompt_pat.match(ln):
                return True

        return False

    return done


class InteractiveGDBDocker(DockerInteractive):
    def __init__(self, container_image: str, mount_dirs: dict[Path, Path], binary_path: str, input_path: str, global_timeout: float = 600.0, scratchpad_dir: Path = None):
        
        # Ensure scratchpad_dir is mounted as /scratchpad if provided and not already present
        if scratchpad_dir is not None:
            scratchpad_mountpoint = Path("/scratchpad")
            need_mount = True
            for host_path, cont_path in mount_dirs.items():
                # Compare normalized mount points
                if Path(cont_path).resolve() == scratchpad_mountpoint:
                    need_mount = False
                    break
            if need_mount:
                mount_dirs = dict(mount_dirs)  # copy to not mutate caller's dict
                mount_dirs[scratchpad_dir] = scratchpad_mountpoint
        super().__init__(
            container_image,
            mount_dirs,
            start_command=["gdb", "-q", "--interpreter=mi2", "--args", binary_path, input_path],
            global_timeout=global_timeout,
        )
        self.scratchpad_dir = scratchpad_dir
        self._tok = 1
    
    def unescape_mi(self, s: str) -> str:
        return (s.replace(r"\n", "\n")
                .replace(r"\t", "\t")
                .replace(r"\\", "\\")
                .replace(r"\"", '"'))
    def mi(self, mi_cmd: str, timeout: float = 10.0) -> CommandResult:
        tok = self._tok
        self._tok += 1
        full = f"{tok}{mi_cmd}"
        return self.send_command(full, completion=mi_completion(tok), timeout=timeout)

    def console(self, cmd: str, timeout: float = 10.0) -> CommandResult:
        esc = cmd.replace("\\", "\\\\").replace('"', '\\"')
        cmd_result = self.mi(f'-interpreter-exec console "{esc}"', timeout=timeout)
        newlines = []
        for line in cmd_result.lines:
            line = strip_tok_prefix(line)
            if (line.startswith('~"') or line.startswith('@"') or line.startswith('&"')) and line.endswith('"'):
                line = self.unescape_mi(line[2:-1])  # decode C escapes
            elif line.startswith("~"):
                newlines.append(self.unescape_mi(line))
            elif line.startswith("@"):
                newlines.append("inferior output: " + self.unescape_mi(line))
            elif line.startswith("*"):
                newlines.append(self.unescape_mi(line))
            elif not line[:1] in "^~@*&=":
                newlines.append("runtime output: " + self.unescape_mi(line))
                

        cmd_result.lines = newlines
        return cmd_result

    def process_commands(self, commands: list[str]) -> list[str]:

        if self.scratchpad_dir is not None:
            # Write commands to a file in the scratchpad (host path)
            scratchpad = Path(self.scratchpad_dir)
            cmd_gdb_path = scratchpad / "cmdset.gdb"
            with open(cmd_gdb_path, "w") as f:
                for cmd in commands:
                    f.write(cmd)
                    if not cmd.endswith("\n"):
                        f.write("\n")

            # Source the file using the CONTAINER path
            # The scratchpad is always mounted at /scratchpad in the container
            container_script_path = "/scratchpad/cmdset.gdb"
            cmd_result = self.console(f'source {container_script_path}')

            return cmd_result.lines
        else:
            cmd_result = []
            for cmd in commands:
                cmd_result.append(self.console(cmd))
            return cmd_result
        
    def interrupt(self) -> list[str]:
        """
        Best-effort interrupt for a GDB session running in a docker container.

        Goal (in order):
        1) Stop the inferior (Ctrl-C semantics) while keeping gdb alive.
        2) If we can't regain control, kill the inferior (keep gdb if possible).
        3) If we still can't recover, tear down the whole container/session.

        Returns log lines + any drained output.
        """
        if self.docker_process is None:
            return ["(interrupt) no process running"]

        out: list[str] = []

        def host_alive() -> bool:
            return self.docker_process is not None and self.docker_process.poll() is None

        # Container name is the best handle (docker kill hits container even if host client is wedged)
        cname = self.container_name

        def saw(prefix: str, lines: list[str]) -> bool:
            return any(l.startswith(prefix) for l in lines)

        def drain_for(seconds: float, max_lines: int = 200) -> list[str]:
            """Drain output for up to `seconds` or until max_lines reached."""
            lines: list[str] = []
            deadline = time.time() + seconds
            while time.time() < deadline and len(lines) < max_lines:
                try:
                    line = self.out_q.get(timeout=0.05)
                except queue.Empty:
                    continue
                lines.append(line)
                if line == "<EOF>":
                    break
            return lines

        def wait_for_stop(timeout: float = 1.0) -> list[str]:
            """
            Drain output until we see an MI stop indicator or timeout.
            In MI mode, stopping typically emits '*stopped,...'.
            If the inferior exits, you may see '=thread-group-exited,...'.
            """
            lines: list[str] = []
            deadline = time.time() + timeout
            while time.time() < deadline:
                try:
                    line = self.out_q.get(timeout=0.1)
                except queue.Empty:
                    continue
                lines.append(line)
                if line == "<EOF>":
                    break
                if line.startswith("*stopped") or line.startswith("=thread-group-exited"):
                    break
            return lines

        def write_stdin(s: str) -> None:
            if self.docker_process is None or self.docker_process.stdin is None:
                raise InteractiveGDBDockerError("stdin not available, process is not running")
            self.docker_process.stdin.write(s)
            self.docker_process.stdin.flush()

        def docker_sig(sig: str) -> None:
            # self._docker expects args like ["kill", "-s", "INT", cname]
            if cname:
                self._docker(["kill", "-s", sig, cname])
            else:
                # Fallback: signal host docker client process
                if sig == "INT":
                    self.docker_process.send_signal(signal.SIGINT)
                elif sig == "TERM":
                    self.docker_process.terminate()
                elif sig == "KILL":
                    self.docker_process.kill()

        # --- Phase 1: Try to stop the inferior without tearing anything down ---

        # 1A) MI-native interrupt (best if running MI2)
        try:
            out.append("(interrupt) trying MI: -exec-interrupt (stop inferior)")
            write_stdin("-exec-interrupt\n")
        except Exception as e:
            out.append(f"(interrupt) MI -exec-interrupt write failed: {e!r}")

        out.extend(wait_for_stop(timeout=0.8))
        if saw("*stopped", out) or saw("=thread-group-exited", out):
            out.append("(interrupt) success: inferior stopped/exited (MI stop record seen)")
            return out

        # 1B) SIGINT (Ctrl-C equivalent)
        try:
            if cname:
                out.append(f"(interrupt) sending SIGINT to container {cname}")
            else:
                out.append("(interrupt) sending SIGINT to host docker client process")
            docker_sig("INT")
        except Exception as e:
            out.append(f"(interrupt) SIGINT failed: {e!r}")

        out.extend(wait_for_stop(timeout=1.2))
        if saw("*stopped", out) or saw("=thread-group-exited", out):
            out.append("(interrupt) success: inferior stopped/exited after SIGINT")
            return out

        # If gdb died as a side effect, we're done (container will exit with it).
        if not host_alive():
            out.append("(interrupt) session exited unexpectedly during interrupt attempts")
            return out

        # --- Phase 2: Kill the inferior (keep gdb if possible) ---

        # MI/console "kill" is the usual way to kill the inferior while keeping gdb alive.
        # (MI has -exec-abort too, but console kill is widely supported.)
        try:
            out.append('(interrupt) trying to kill inferior: -interpreter-exec console "kill"')
            write_stdin('-interpreter-exec console "kill"\n')
        except Exception as e:
            out.append(f"(interrupt) kill-inferior write failed: {e!r}")

        # After killing, you may see =thread-group-exited, or a *stopped.
        out.extend(wait_for_stop(timeout=1.0))
        if saw("=thread-group-exited", out) or saw("*stopped", out):
            out.append("(interrupt) recovered: inferior killed/stopped; gdb should still be alive")
            return out

        # --- Phase 3: Escalate to tearing down the whole container/session ---
        # If we can't get a stop record and kill didn't work, it's likely wedged.
        # Since you said: if it has to exit gdb, may as well kill the container too,
        # we hard-reset the container now.

        if cname:
            out.append(f"(interrupt) hard reset: docker rm -f {cname}")
            try:
                self._docker(["rm", "-f", cname])
            except Exception as e:
                out.append(f"(interrupt) docker rm -f failed: {e!r}")
            out.extend(drain_for(0.8))
            return out

 