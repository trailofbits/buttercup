import json
import logging
import os
import signal
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from buttercup.common.types import FuzzConfiguration

logger = logging.getLogger(__name__)


@dataclass
class Crash:
    input_path: str
    stacktrace: str
    reproduce_args: list[str]
    crash_time: float


@dataclass
class FuzzResult:
    """Result from a fuzzing operation"""

    logs: str
    command: str
    crashes: list[Crash]
    stats: dict
    time_executed: float
    timed_out: bool


@dataclass
class Conf:
    # in seconds
    timeout: int
    runner_path: Path


@dataclass
class RunnerProxy:
    conf: Conf
    _timeout: int = field(init=False, default=5)

    def _kill_process(self, process: subprocess.Popen) -> None:
        try:
            process.kill()
            try:
                process.wait(timeout=self._timeout)
            except subprocess.TimeoutExpired:
                logger.error("Process did not terminate after kill within 5 seconds")
        except Exception as e:
            logger.error(f"Error killing process: {e}")

    def _kill_process_group(self, process: subprocess.Popen) -> None:
        # Kill the entire process group
        try:
            if os.name != "nt":  # Unix-like systems
                # Kill the process group
                os.killpg(os.getpgid(process.pid), signal.SIGTERM)
                # Wait a bit for graceful termination
                try:
                    process.wait(timeout=self._timeout)
                except subprocess.TimeoutExpired:
                    # Force kill if graceful termination failed
                    os.killpg(os.getpgid(process.pid), signal.SIGKILL)
                    try:
                        process.wait(timeout=self._timeout)
                    except subprocess.TimeoutExpired:
                        logger.error("Process did not terminate after kill within 5 seconds")
            else:  # Windows
                self._kill_process(process)
        except (ProcessLookupError, OSError) as e:
            logger.warning(f"Error killing process group: {e}")
            self._kill_process(process)

    def _run_subprocess_task(self, cmd: list[str], timeout: int, task_type: str) -> dict[str, Any]:
        """Run subprocess task and return result"""
        # Enforce a timeout of runner_timeout + 5 minutes (in seconds)
        subprocess_timeout = timeout + 300

        try:
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True,
            )

            try:
                stdout, stderr = process.communicate(timeout=subprocess_timeout)

                # Log the return code with interpretation
                returncode = process.returncode
                if returncode != 0:
                    # Interpret common exit codes
                    if returncode > 128:
                        signal_num = returncode - 128
                        try:
                            signal_name = signal.Signals(signal_num).name
                        except ValueError:
                            signal_name = f"signal {signal_num}"
                        logger.warning(
                            f"{task_type} process terminated by {signal_name} "
                            f"(exit code {returncode} = 128 + {signal_num})"
                        )
                    elif returncode == 1:
                        logger.warning(f"{task_type} process exited with code 1 (general error)")
                    elif returncode == 77:
                        logger.warning(f"{task_type} process exited with code 77 (libFuzzer: no corpus)")
                    elif returncode == 124:
                        logger.warning(f"{task_type} process exited with code 124 (timeout)")
                    else:
                        logger.warning(f"{task_type} process exited with code {returncode}")

                    error_msg = stderr.decode("utf-8") if stderr else "Unknown subprocess error"
                    logger.error(f"{task_type} task failed: {error_msg}")
                    return {
                        "status": "failed",
                        "error": f"Task failed (exit code {returncode}): {error_msg}",
                    }
                else:
                    logger.debug(f"{task_type} process exited successfully (code 0)")
            except subprocess.TimeoutExpired:
                logger.error(f"{task_type} task timed out after {subprocess_timeout} seconds")
                if process.poll() is None:
                    self._kill_process_group(process)

                return {
                    "status": "failed",
                    "error": f"Task timed out after {subprocess_timeout} seconds",
                }

            # Parse the JSON output from the subprocess
            try:
                output_str = stdout.decode("utf-8").strip()
                logger.debug(f"Subprocess output: {output_str}")

                return json.loads(output_str)
            except json.JSONDecodeError as parse_error:
                logger.error(f"Failed to parse JSON output for task {task_type}: {parse_error}")
                logger.error(f"Raw output: {output_str}")
                return {
                    "status": "failed",
                    "error": f"Failed to parse JSON output: {parse_error}",
                }
            except Exception as parse_error:
                logger.error(f"Failed to parse subprocess output for task {task_type}: {parse_error}")
                return {
                    "status": "failed",
                    "error": f"Failed to parse output: {parse_error}",
                }
        except Exception as e:
            logger.error(f"Failed to start subprocess for task {task_type}: {e}")
            return {
                "status": "failed",
                "error": f"Failed to start subprocess: {e}",
            }

    def run_fuzzer(self, conf: FuzzConfiguration) -> FuzzResult:
        """Run fuzzer via HTTP server and wait for completion"""

        try:
            logger.info(f"Starting fuzzer task {conf.engine} | {conf.sanitizer} | {conf.target_path}")
            runner_timeout = self.conf.timeout if self.conf.timeout else 1000

            cmd = [
                str(self.conf.runner_path),
                "--timeout",
                str(runner_timeout),
                "--corpusdir",
                str(conf.corpus_dir),
                "--engine",
                conf.engine,
                "--sanitizer",
                conf.sanitizer,
                str(conf.target_path),
                "fuzz",
            ]

            result = self._run_subprocess_task(cmd, runner_timeout, "fuzz")
        except Exception as e:
            logger.exception(f"Fuzzer task {conf.engine} | {conf.sanitizer} | {conf.target_path} failed: {str(e)}")
            result = {
                "status": "failed",
                "error": str(e),
            }

        return self._dict_to_fuzz_result(result)

    def merge_corpus(self, conf: FuzzConfiguration, output_dir: str) -> None:
        """Merge corpus via HTTP server and wait for completion"""
        try:
            logger.info(f"Starting merge corpus task {conf.engine} | {conf.sanitizer} | {conf.target_path}")
            runner_timeout = self.conf.timeout if self.conf.timeout else 1000

            cmd = [
                str(self.conf.runner_path),
                "--timeout",
                str(runner_timeout),
                "--corpusdir",
                str(conf.corpus_dir),
                "--engine",
                conf.engine,
                "--sanitizer",
                conf.sanitizer,
                str(conf.target_path),
                "merge",
                "--output-dir",
                str(output_dir),
            ]

            self._run_subprocess_task(cmd, runner_timeout, "merge")
        except Exception as e:
            logger.exception(
                f"Merge corpus task {conf.engine} | {conf.sanitizer} | {conf.target_path} failed: {str(e)}"
            )

    def _dict_to_fuzz_result(self, result_dict: dict[str, Any]) -> FuzzResult:
        """Convert dictionary result back to FuzzResult object"""
        # Handle both "logs" and "error" keys for backward compatibility
        logs = result_dict.get("logs", result_dict.get("error", ""))
        stats = result_dict.get("stats", {})
        crashes = result_dict.get("crashes", [])

        # Log detailed stats for debugging harness issues
        logger.info(
            f"Fuzzer result: num_crashes={len(crashes)}, "
            f"timed_out={result_dict.get('timed_out', False)}, "
            f"time_executed={result_dict.get('time_executed', 0.0):.2f}s"
        )
        if stats:
            oom_count = stats.get("oom_count", 0)
            timeout_count = stats.get("timeout_count", 0)
            crash_count = stats.get("crash_count", 0)
            startup_crash_count = stats.get("startup_crash_count", 0)

            if oom_count > 0:
                logger.warning(f"Fuzzer detected OOM: oom_count={oom_count}")
            if timeout_count > 0:
                logger.warning(f"Fuzzer detected timeouts: timeout_count={timeout_count}")
            if startup_crash_count > 0:
                logger.warning(f"Fuzzer detected startup crashes: startup_crash_count={startup_crash_count}")

            logger.info(
                f"Fuzzer stats summary: crash_count={crash_count}, oom_count={oom_count}, "
                f"timeout_count={timeout_count}, startup_crash_count={startup_crash_count}, "
                f"edge_coverage={stats.get('edge_coverage', 0)}/{stats.get('edges_total', 0)}"
            )

        return FuzzResult(
            logs=logs,
            crashes=[
                Crash(
                    input_path=crash.get("input_path", ""),
                    stacktrace=crash.get("stacktrace", ""),
                    reproduce_args=crash.get("reproduce_args", []),
                    crash_time=crash.get("crash_time", 0.0),
                )
                for crash in crashes
            ],
            stats=stats,
            time_executed=result_dict.get("time_executed", 0.0),
            timed_out=result_dict.get("timed_out", False),
            command=result_dict.get("command", ""),
        )
