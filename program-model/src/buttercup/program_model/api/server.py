"""FastAPI server for program-model REST API."""

from __future__ import annotations

import logging
import shutil
import os
import tarfile
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import (
    FastAPI,
    HTTPException,
    Query,
    Path as FastAPIPath,
    Request,
)
from starlette.background import BackgroundTask
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse

from buttercup.common.challenge_task import ChallengeTask
from buttercup.program_model.api.models import (
    ErrorResponse,
    FunctionModel,
    FunctionSearchResponse,
    TaskInitRequest,
    TaskInitResponse,
    TypeDefinitionModel,
    TypeSearchResponse,
    TypeUsageInfoModel,
)
from buttercup.program_model.codequery import CodeQueryPersistent

logger = logging.getLogger(__name__)

app = FastAPI(
    title="Buttercup Program Model API",
    description="REST API for program model operations including function/type analysis and harness discovery",
    version="0.0.1",
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure as needed for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global storage for CodeQuery instances
_codequery_instances: Dict[str, CodeQueryPersistent] = {}


@app.middleware("http")
async def log_requests(request: Request, call_next: Any) -> Any:
    """Log all incoming requests for debugging."""
    logger.info("=== INCOMING REQUEST ===")
    logger.info("Method: %s", request.method)
    logger.info("URL: %s", request.url)
    logger.info("Headers: %s", dict(request.headers))

    # Log request body for POST requests
    if request.method == "POST":
        try:
            body = await request.body()
            logger.info("Request body: %s", body.decode() if body else "None")
        except Exception as e:
            logger.error("Failed to read request body: %s", e)

    response = await call_next(request)

    logger.info("=== RESPONSE ===")
    logger.info("Status code: %s", response.status_code)
    logger.info("=== END REQUEST ===")

    return response


@app.on_event("startup")
async def startup_event() -> None:
    """Verify that all required dependencies are available on startup."""
    logger.info("Starting Buttercup Program Model API Server")

    # Check for required commands
    required_commands = ["cscope", "ctags", "cqmakedb", "cqsearch"]
    missing_commands = []

    for command in required_commands:
        if shutil.which(command) is None:
            missing_commands.append(command)
        else:
            logger.info("Found %s at: %s", command, shutil.which(command))

    if missing_commands:
        logger.error("Missing required commands: %s", ", ".join(missing_commands))
        raise RuntimeError(f"Missing required commands: {', '.join(missing_commands)}")

    # Check environment
    logger.info("Current working directory: %s", Path.cwd())
    logger.info("Docker socket available: %s", Path("/var/run/docker.sock").exists())

    # Check if we can access common directories
    common_dirs = ["/crs_scratch", "/tasks_storage", "/node_data"]
    for dir_path in common_dirs:
        path = Path(dir_path)
        if path.exists():
            logger.info(
                "Directory %s exists and is %s",
                dir_path,
                "writable" if os.access(path, os.W_OK) else "read-only",
            )
        else:
            logger.warning("Directory %s does not exist", dir_path)

    logger.info("All required dependencies are available")


def get_codequery(task_id: str) -> CodeQueryPersistent:
    """Get or create a CodeQuery instance for a task."""
    if task_id not in _codequery_instances:
        raise HTTPException(
            status_code=404,
            detail=f"Task {task_id} not initialized. Call /tasks/{task_id}/init first.",
        )
    return _codequery_instances[task_id]


@app.exception_handler(Exception)
async def general_exception_handler(request: Any, exc: Exception) -> JSONResponse:
    """Handle general exceptions."""
    logger.exception(
        "Unhandled exception in %s %s: %s", request.method, request.url, exc
    )

    # Provide more detailed error information
    error_detail = str(exc)
    if hasattr(exc, "__traceback__"):
        import traceback

        error_detail += (
            f"\nTraceback:\n{''.join(traceback.format_tb(exc.__traceback__))}"
        )

    return JSONResponse(
        status_code=500,
        content=ErrorResponse(
            error="Internal server error",
            detail=error_detail,
            code="INTERNAL_ERROR",
        ).model_dump(),
    )


@app.get("/")
async def root() -> dict[str, str]:
    """Root endpoint for debugging."""
    return {
        "message": "Buttercup Program Model API",
        "version": "0.0.1",
        "status": "running",
    }


@app.get("/health")
async def health_check() -> dict[str, str]:
    """Health check endpoint."""
    return {
        "message": "Healthy",
        "status": "ok",
    }


@app.post("/tasks/{task_id}/init", response_model=TaskInitResponse)
async def initialize_task(
    request: TaskInitRequest,
    task_id: str = FastAPIPath(..., description="Task ID"),
) -> TaskInitResponse:
    """Initialize a CodeQuery instance for a task."""
    try:
        task_dir = Path(request.task_dir)
        work_dir = Path(request.work_dir)

        logger.info("=== TASK INITIALIZATION START ===")
        logger.info("task_id: %s", task_id)
        logger.info("Received task initialization request:")
        logger.info("  request.task_dir: %s", task_dir)
        logger.info("  request.work_dir: %s", work_dir)

        # Validate request parameters
        if not task_dir or not work_dir:
            logger.error(
                "Invalid request parameters: task_dir=%s, work_dir=%s",
                task_dir,
                work_dir,
            )
            raise HTTPException(
                status_code=400,
                detail="Invalid request parameters: task_dir and work_dir are required",
            )

        if not task_dir.exists():
            logger.error(
                "Task directory does not exist: task_dir=%s",
                task_dir,
            )
            raise HTTPException(
                status_code=400,
                detail="Task directory does not exist",
            )
        if not work_dir.exists():
            logger.error(
                "Work directory does not exist: work_dir=%s",
                work_dir,
            )
            raise HTTPException(
                status_code=400,
                detail="Work directory does not exist",
            )

        logger.info("Creating ChallengeTask...")
        try:
            challenge_task = ChallengeTask(read_only_task_dir=task_dir)
            logger.info("ChallengeTask initialized successfully")
        except Exception as e:
            logger.exception("Failed to initialize ChallengeTask: %s", e)
            raise HTTPException(
                status_code=500,
                detail=f"Failed to initialize ChallengeTask: {str(e)}",
            )

        # Initialize CodeQuery
        logger.info("Creating CodeQueryPersistent...")
        try:
            codequery = CodeQueryPersistent(
                challenge_task, work_dir=Path(request.work_dir)
            )
            logger.info("CodeQuery initialized successfully")
        except Exception as e:
            logger.exception("Failed to initialize CodeQuery: %s", e)
            raise HTTPException(
                status_code=500,
                detail=f"Failed to initialize CodeQuery: {str(e)}",
            )

        _codequery_instances[task_id] = codequery

        logger.info("Successfully initialized task %s", task_id)
        logger.info("=== TASK INITIALIZATION COMPLETE ===")
        return TaskInitResponse(
            task_id=task_id,
            status="initialized",
            message="Task initialized successfully",
        )
    except HTTPException:
        # Re-raise HTTPExceptions as-is (like the 400 error for missing task_dir)
        logger.error("=== TASK INITIALIZATION FAILED (HTTPException) ===")
        raise
    except Exception as e:
        logger.exception("=== TASK INITIALIZATION FAILED (Unexpected Exception) ===")
        logger.exception("Failed to initialize task %s: %s", task_id, e)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to initialize task: {str(e)}",
        )


@app.get("/tasks/{task_id}/functions", response_model=FunctionSearchResponse)
async def search_functions(
    task_id: str = FastAPIPath(..., description="Task ID"),
    function_name: str = Query(..., description="Function name to search for"),
    file_path: Optional[str] = Query(
        None, description="Optional file path to search within"
    ),
    line_number: Optional[int] = Query(
        None, description="Optional line number to search around"
    ),
    fuzzy: bool = Query(False, description="Enable fuzzy matching"),
    fuzzy_threshold: int = Query(80, description="Fuzzy matching threshold (0-100)"),
) -> FunctionSearchResponse:
    """Search for functions in the codebase."""
    try:
        codequery = get_codequery(task_id)

        functions = codequery.get_functions(
            function_name=function_name,
            file_path=Path(file_path) if file_path else None,
            line_number=line_number,
            fuzzy=fuzzy,
            fuzzy_threshold=fuzzy_threshold,
        )

        return FunctionSearchResponse(
            functions=[FunctionModel.from_domain(func) for func in functions],
            total_count=len(functions),
        )
    except HTTPException:
        # Re-raise HTTPExceptions as-is
        raise
    except Exception as e:
        logger.exception("Failed to search functions: %s", e)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to search functions: {str(e)}",
        )


@app.get(
    "/tasks/{task_id}/functions/{function_name}/callers",
    response_model=FunctionSearchResponse,
)
async def get_function_callers(
    task_id: str = FastAPIPath(..., description="Task ID"),
    function_name: str = FastAPIPath(..., description="Function name"),
    file_path: Optional[str] = Query(
        None, description="Optional file path of the function"
    ),
) -> FunctionSearchResponse:
    """Get callers of a function."""
    try:
        codequery = get_codequery(task_id)

        # If file_path is provided, get the specific function first
        if file_path:
            functions = codequery.get_functions(function_name, Path(file_path))
            if not functions:
                raise HTTPException(
                    status_code=404,
                    detail=f"Function {function_name} not found in {file_path}",
                )
            callers = codequery.get_callers(functions[0])
        else:
            callers = codequery.get_callers(function_name)

        return FunctionSearchResponse(
            functions=[FunctionModel.from_domain(func) for func in callers],
            total_count=len(callers),
        )
    except HTTPException:
        # Re-raise HTTPExceptions as-is
        raise
    except Exception as e:
        logger.exception("Failed to get function callers: %s", e)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get function callers: {str(e)}",
        )


@app.get(
    "/tasks/{task_id}/functions/{function_name}/callees",
    response_model=FunctionSearchResponse,
)
async def get_function_callees(
    task_id: str = FastAPIPath(..., description="Task ID"),
    function_name: str = FastAPIPath(..., description="Function name"),
    file_path: Optional[str] = Query(
        None, description="Optional file path of the function"
    ),
    line_number: Optional[int] = Query(
        None, description="Optional line number of the function"
    ),
) -> FunctionSearchResponse:
    """Get callees of a function."""
    try:
        codequery = get_codequery(task_id)

        # If file_path is provided, get the specific function first
        if file_path:
            functions = codequery.get_functions(
                function_name, Path(file_path), line_number
            )
            if not functions:
                raise HTTPException(
                    status_code=404,
                    detail=f"Function {function_name} not found in {file_path}",
                )
            callees = codequery.get_callees(functions[0])
        else:
            callees = codequery.get_callees(
                function_name, Path(file_path) if file_path else None, line_number
            )

        return FunctionSearchResponse(
            functions=[FunctionModel.from_domain(func) for func in callees],
            total_count=len(callees),
        )
    except HTTPException:
        # Re-raise HTTPExceptions as-is
        raise
    except Exception as e:
        logger.exception("Failed to get function callees: %s", e)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get function callees: {str(e)}",
        )


@app.get("/tasks/{task_id}/types", response_model=TypeSearchResponse)
async def search_types(
    task_id: str = FastAPIPath(..., description="Task ID"),
    type_name: str = Query(..., description="Type name to search for"),
    file_path: Optional[str] = Query(
        None, description="Optional file path to search within"
    ),
    function_name: Optional[str] = Query(
        None, description="Optional function name to search within"
    ),
    fuzzy: bool = Query(False, description="Enable fuzzy matching"),
    fuzzy_threshold: int = Query(80, description="Fuzzy matching threshold (0-100)"),
) -> TypeSearchResponse:
    """Search for types in the codebase."""
    try:
        codequery = get_codequery(task_id)

        types = codequery.get_types(
            type_name=type_name,
            file_path=Path(file_path) if file_path else None,
            function_name=function_name,
            fuzzy=fuzzy,
            fuzzy_threshold=fuzzy_threshold,
        )

        return TypeSearchResponse(
            types=[TypeDefinitionModel.from_domain(type_def) for type_def in types],
            total_count=len(types),
        )
    except HTTPException:
        # Re-raise HTTPExceptions as-is
        raise
    except Exception as e:
        logger.exception("Failed to search types: %s", e)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to search types: {str(e)}",
        )


@app.get(
    "/tasks/{task_id}/types/{type_name}/calls", response_model=list[TypeUsageInfoModel]
)
async def get_type_calls(
    task_id: str = FastAPIPath(..., description="Task ID"),
    type_name: str = FastAPIPath(..., description="Type name"),
    file_path: Optional[str] = Query(
        None, description="Optional file path of the type"
    ),
) -> list[TypeUsageInfoModel]:
    """Get usage locations of a type."""
    try:
        codequery = get_codequery(task_id)

        # First get the type definition
        types = codequery.get_types(
            type_name=type_name,
            file_path=Path(file_path) if file_path else None,
        )

        if not types:
            raise HTTPException(
                status_code=404,
                detail=f"Type {type_name} not found",
            )

        # Get calls for the first type found
        type_calls = codequery.get_type_calls(types[0])

        return [TypeUsageInfoModel.from_domain(usage) for usage in type_calls]
    except HTTPException:
        # Re-raise HTTPExceptions as-is
        raise
    except Exception as e:
        logger.exception("Failed to get type calls: %s", e)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get type calls: {str(e)}",
        )


@app.delete("/tasks/{task_id}")
async def cleanup_task(
    task_id: str = FastAPIPath(..., description="Task ID to cleanup"),
) -> dict[str, str]:
    """Clean up a task and its associated resources."""
    try:
        if task_id in _codequery_instances:
            del _codequery_instances[task_id]
            logger.info("Cleaned up task %s", task_id)

        return {"status": "cleaned_up", "task_id": task_id}
    except HTTPException:
        # Re-raise HTTPExceptions as-is
        raise
    except Exception as e:
        logger.exception("Failed to cleanup task %s: %s", task_id, e)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to cleanup task: {str(e)}",
        )


async def cleanup_file(filepath: Path) -> None:
    """A function to clean up a file."""
    if filepath.exists():
        filepath.unlink()


@app.get("/tasks/{task_id}/container-src-dir")
async def download_container_src_dir(
    task_id: str = FastAPIPath(..., description="Task ID"),
) -> FileResponse:
    """Download the container source directory as a tar.gz archive."""
    try:
        codequery = get_codequery(task_id)

        # Get the container_src_dir path
        container_src_dir = codequery._get_container_src_dir()

        if not container_src_dir.exists():
            raise HTTPException(
                status_code=404,
                detail=f"Container source directory does not exist for task {task_id}",
            )

        # Create a temporary tar.gz file
        with tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False) as tmp_file:
            with tarfile.open(tmp_file.name, "w:gz") as tar:
                tar.add(container_src_dir, arcname="container_src_dir")

            # Return the file as a download
            background_task = BackgroundTask(cleanup_file, filepath=Path(tmp_file.name))
            return FileResponse(
                path=tmp_file.name,
                filename=f"container_src_dir_{task_id}.tar.gz",
                media_type="application/gzip",
                background=background_task,  # Clean up after download
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(
            "Failed to download container source directory for task %s: %s", task_id, e
        )
        raise HTTPException(
            status_code=500,
            detail=f"Failed to download container source directory: {str(e)}",
        )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
