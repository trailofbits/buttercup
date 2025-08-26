import asyncio
import uuid
from pathlib import Path
from typing import Any

from clusterfuzz.fuzz.engine import FuzzResult
from fastapi import BackgroundTasks, FastAPI, HTTPException
from pydantic import BaseModel, Field

from buttercup.common.logger import setup_package_logger
from buttercup.common.types import FuzzConfiguration
from buttercup.fuzzer_runner.runner import Conf, Runner
from buttercup.fuzzer_runner.settings import ServerSettings

server_settings = ServerSettings()
logger = setup_package_logger("fuzzer-runner", __name__, server_settings.log_level)

# Global state
app = FastAPI(
    title="Buttercup Fuzzer Runner API",
    description="HTTP API for running fuzzers and merging corpus",
    version="0.1.0",
)
active_tasks: dict[str, dict[str, Any]] = {}


class FuzzRequest(BaseModel):
    corpus_dir: str = Field(..., description="Path to the corpus directory")
    target_path: str = Field(..., description="Path to the target binary")
    engine: str = Field(..., description="Fuzzing engine to use")
    sanitizer: str = Field(..., description="Sanitizer to use")
    timeout: int | None = Field(None, description="Timeout in seconds (overrides server default)")


class MergeCorpusRequest(BaseModel):
    corpus_dir: str = Field(..., description="Path to the corpus directory")
    target_path: str = Field(..., description="Path to the target binary")
    engine: str = Field(..., description="Fuzzing engine to use")
    sanitizer: str = Field(..., description="Sanitizer to use")
    output_dir: str = Field(..., description="Output directory for merged corpus")
    timeout: int | None = Field(None, description="Timeout in seconds (overrides server default)")


class FuzzResponse(BaseModel):
    task_id: str = Field(..., description="Unique task identifier")
    status: str = Field(..., description="Task status")
    result: dict[str, Any] | None = Field(None, description="Fuzzing result if completed")
    error: str | None = Field(None, description="Error message if failed")


class MergeCorpusResponse(BaseModel):
    task_id: str = Field(..., description="Unique task identifier")
    status: str = Field(..., description="Task status")
    error: str | None = Field(None, description="Error message if failed")


class HealthResponse(BaseModel):
    status: str = Field(..., description="Server health status")
    version: str = Field(..., description="Server version")


@app.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """Health check endpoint"""
    return HealthResponse(status="healthy", version="0.1.0")


@app.post("/fuzz", response_model=FuzzResponse)
async def run_fuzzer(request: FuzzRequest, background_tasks: BackgroundTasks) -> FuzzResponse:
    """Run a fuzzer with the given configuration"""
    task_id = str(uuid.uuid4())

    # Validate paths
    if not Path(request.corpus_dir).exists():
        raise HTTPException(status_code=400, detail=f"Corpus directory does not exist: {request.corpus_dir}")

    if not Path(request.target_path).exists():
        raise HTTPException(status_code=400, detail=f"Target path does not exist: {request.target_path}")

    # Create fuzz configuration
    fuzz_conf = FuzzConfiguration(
        corpus_dir=request.corpus_dir,
        target_path=request.target_path,
        engine=request.engine,
        sanitizer=request.sanitizer,
    )

    # Store task info
    active_tasks[task_id] = {
        "type": "fuzz",
        "status": "running",
        "config": fuzz_conf,
        "timeout": request.timeout or (server_settings.timeout if server_settings else 1000),
    }

    # Run fuzzer in background
    background_tasks.add_task(_run_fuzzer_task, task_id, fuzz_conf, request.timeout)

    return FuzzResponse(task_id=task_id, status="running")


@app.post("/merge-corpus", response_model=MergeCorpusResponse)
async def merge_corpus(request: MergeCorpusRequest, background_tasks: BackgroundTasks) -> MergeCorpusResponse:
    """Merge corpus with the given configuration"""
    task_id = str(uuid.uuid4())

    # Validate paths
    if not Path(request.corpus_dir).exists():
        raise HTTPException(status_code=400, detail=f"Corpus directory does not exist: {request.corpus_dir}")

    if not Path(request.target_path).exists():
        raise HTTPException(status_code=400, detail=f"Target path does not exist: {request.target_path}")

    # Create output directory if it doesn't exist
    output_path = Path(request.output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    # Create fuzz configuration
    fuzz_conf = FuzzConfiguration(
        corpus_dir=request.corpus_dir,
        target_path=request.target_path,
        engine=request.engine,
        sanitizer=request.sanitizer,
    )

    # Store task info
    active_tasks[task_id] = {
        "type": "merge_corpus",
        "status": "running",
        "config": fuzz_conf,
        "output_dir": request.output_dir,
        "timeout": request.timeout or (server_settings.timeout if server_settings else 1000),
    }

    # Run merge in background
    background_tasks.add_task(_run_merge_task, task_id, fuzz_conf, request.output_dir, request.timeout)

    return MergeCorpusResponse(task_id=task_id, status="running")


@app.get("/tasks/{task_id}", response_model=dict[str, Any])
async def get_task_status(task_id: str) -> dict[str, Any]:
    """Get the status of a running or completed task"""
    if task_id not in active_tasks:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")

    task_info = active_tasks[task_id]
    return {
        "task_id": task_id,
        "type": task_info["type"],
        "status": task_info["status"],
        "result": task_info.get("result"),
        "error": task_info.get("error"),
    }


@app.get("/tasks", response_model=dict[str, Any])
async def list_tasks() -> dict[str, Any]:
    """List all active and completed tasks"""
    return {
        "tasks": {
            task_id: {
                "type": task_info["type"],
                "status": task_info["status"],
                "result": task_info.get("result"),
                "error": task_info.get("error"),
            }
            for task_id, task_info in active_tasks.items()
        }
    }


async def _run_fuzzer_task(task_id: str, fuzz_conf: FuzzConfiguration, timeout: int | None) -> None:
    """Run fuzzer task in background"""
    try:
        logger.info(f"Starting fuzzer task {task_id}")

        # Create runner with custom timeout if provided
        runner_timeout = timeout or (server_settings.timeout if server_settings else 1000)
        runner = Runner(Conf(runner_timeout))

        # Run fuzzer in a separate thread to avoid blocking the server
        result: FuzzResult = await asyncio.to_thread(runner.run_fuzzer, fuzz_conf)

        # Convert result to dict for JSON serialization
        result_dict = {
            "logs": result.logs,
            "command": result.command,
            "crashes": [
                {
                    "input_path": crash.input_path,
                    "stacktrace": crash.stacktrace,
                    "reproduce_args": crash.reproduce_args,
                    "crash_time": crash.crash_time,
                }
                for crash in result.crashes
            ],
            "stats": result.stats,
            "time_executed": result.time_executed,
            "timed_out": result.timed_out,
        }

        # Update task status
        active_tasks[task_id]["status"] = "completed"
        active_tasks[task_id]["result"] = result_dict

        logger.info(f"Fuzzer task {task_id} completed successfully")

    except Exception as e:
        logger.exception(f"Fuzzer task {task_id} failed: {str(e)}")
        active_tasks[task_id]["status"] = "failed"
        active_tasks[task_id]["error"] = str(e)


async def _run_merge_task(task_id: str, fuzz_conf: FuzzConfiguration, output_dir: str, timeout: int | None) -> None:
    """Run merge corpus task in background"""
    try:
        logger.info(f"Starting merge corpus task {task_id}")

        # Create runner with custom timeout if provided
        runner_timeout = timeout or (server_settings.timeout if server_settings else 1000)
        runner = Runner(Conf(runner_timeout))

        # Run merge in a separate thread to avoid blocking the server
        await asyncio.to_thread(runner.merge_corpus, fuzz_conf, output_dir)

        # Update task status
        active_tasks[task_id]["status"] = "completed"

        logger.info(f"Merge corpus task {task_id} completed successfully")

    except Exception as e:
        logger.error(f"Merge corpus task {task_id} failed: {str(e)}")
        active_tasks[task_id]["status"] = "failed"
        active_tasks[task_id]["error"] = str(e)
