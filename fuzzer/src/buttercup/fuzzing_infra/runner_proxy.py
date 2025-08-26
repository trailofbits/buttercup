import logging
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

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
    server_url: str = "http://localhost:8000"
    poll_interval: float = 1.0  # seconds between status checks
    timeout_buffer: float = 60.0  # extra time buffer beyond the fuzzer timeout


@dataclass
class RunnerProxy:
    conf: Conf
    client: httpx.Client = field(init=False)

    def __post_init__(self) -> None:
        self.client = httpx.Client(timeout=30.0)

    def run_fuzzer(self, conf: FuzzConfiguration) -> FuzzResult:
        """Run fuzzer via HTTP server and wait for completion"""
        logger.info(f"Starting fuzzer via HTTP server: {conf.engine} | {conf.sanitizer} | {conf.target_path}")

        # Prepare request payload
        payload = {
            "corpus_dir": conf.corpus_dir,
            "target_path": conf.target_path,
            "engine": conf.engine,
            "sanitizer": conf.sanitizer,
            "timeout": self.conf.timeout,
        }

        try:
            # Start fuzzer task
            response = self.client.post(f"{self.conf.server_url}/fuzz", json=payload)
            response.raise_for_status()

            task_data = response.json()
            task_id = task_data["task_id"]
            logger.info(f"Started fuzzer task: {task_id}")

            # Poll for completion
            result = self._wait_for_task_completion(task_id, "fuzz")

            # Convert result back to FuzzResult
            return self._dict_to_fuzz_result(result)
        except Exception as e:
            logger.error(f"Error during fuzzer execution: {e}")
            return FuzzResult(
                logs="",
                command="",
                crashes=[],
                stats={},
                time_executed=0.0,
                timed_out=False,
            )

    def merge_corpus(self, conf: FuzzConfiguration, output_dir: str) -> None:
        """Merge corpus via HTTP server and wait for completion"""
        logger.info(f"Starting corpus merge via HTTP server: {conf.engine} | {conf.sanitizer} | {conf.target_path}")

        # Prepare request payload
        payload = {
            "corpus_dir": conf.corpus_dir,
            "target_path": conf.target_path,
            "engine": conf.engine,
            "sanitizer": conf.sanitizer,
            "output_dir": output_dir,
            "timeout": self.conf.timeout,
        }

        try:
            # Start merge task
            response = self.client.post(f"{self.conf.server_url}/merge-corpus", json=payload)
            response.raise_for_status()

            task_data = response.json()
            task_id = task_data["task_id"]
            logger.info(f"Started merge task: {task_id}")

            # Poll for completion
            self._wait_for_task_completion(task_id, "merge_corpus")

        except Exception as e:
            logger.error(f"Error during corpus merge: {e}")
            return

    def _wait_for_task_completion(self, task_id: str, task_type: str) -> dict[str, Any]:
        """Wait for a task to complete and return the result"""
        logger.info(f"Waiting for {task_type} task {task_id} to complete...")

        # Calculate maximum wait time (fuzzer timeout + buffer)
        max_wait_time = self.conf.timeout + self.conf.timeout_buffer
        start_time = time.time()

        while True:
            # Check if we've exceeded the maximum wait time
            elapsed_time = time.time() - start_time
            if elapsed_time > max_wait_time:
                error_msg = f"Task {task_id} timed out after {elapsed_time:.1f} seconds (max: {max_wait_time:.1f}s)"
                logger.error(error_msg)
                raise RuntimeError(f"Task timeout: {error_msg}")

            try:
                # Check task status
                response = self.client.get(f"{self.conf.server_url}/tasks/{task_id}")
                response.raise_for_status()

                task_info: dict[str, Any] = response.json()
                status = task_info["status"]

                if status == "completed":
                    logger.info(f"Task {task_id} completed successfully after {elapsed_time:.1f} seconds")
                    return task_info.get("result", {})  # type: ignore[no-any-return]
                elif status == "failed":
                    error_msg = task_info.get("error", "Unknown error")
                    logger.error(f"Task {task_id} failed after {elapsed_time:.1f} seconds: {error_msg}")
                    raise RuntimeError(f"Task failed: {error_msg}")
                elif status == "running":
                    logger.debug(f"Task {task_id} still running after {elapsed_time:.1f}s, waiting...")
                    time.sleep(self.conf.poll_interval)
                else:
                    raise RuntimeError(f"Unknown task status: {status}")

            except httpx.HTTPError:
                logger.exception(f"HTTP error checking task status after {elapsed_time:.1f}s")
                continue
            except Exception as e:
                logger.error(f"Error checking task status after {elapsed_time:.1f}s: {e}")
                raise

    def _dict_to_fuzz_result(self, result_dict: dict[str, Any]) -> FuzzResult:
        """Convert dictionary result back to FuzzResult object"""
        return FuzzResult(
            logs=result_dict.get("logs", ""),
            crashes=[
                Crash(
                    input_path=crash.get("input_path", ""),
                    stacktrace=crash.get("stacktrace", ""),
                    reproduce_args=crash.get("reproduce_args", []),
                    crash_time=crash.get("crash_time", 0.0),
                )
                for crash in result_dict.get("crashes", [])
            ],
            stats=result_dict.get("stats", {}),
            time_executed=result_dict.get("time_executed", 0.0),
            timed_out=result_dict.get("timed_out", False),
            command=result_dict.get("command", ""),
        )

    def __del__(self) -> None:
        """Cleanup HTTP client"""
        if hasattr(self, "client"):
            self.client.close()
