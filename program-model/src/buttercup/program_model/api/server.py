"""FastAPI server for program-model REST API."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import FastAPI, HTTPException, Query, Path as FastAPIPath
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

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
    logger.exception("Unhandled exception: %s", exc)
    return JSONResponse(
        status_code=500,
        content=ErrorResponse(
            error="Internal server error",
            detail=str(exc),
            code="INTERNAL_ERROR",
        ).model_dump(),
    )


@app.get("/health")
async def health_check() -> dict[str, str]:
    """Health check endpoint."""
    return {"status": "healthy"}


@app.post("/tasks/{task_id}/init", response_model=TaskInitResponse)
async def initialize_task(
    request: TaskInitRequest,
    task_id: str = FastAPIPath(..., description="Task ID to initialize"),
) -> TaskInitResponse:
    """Initialize a CodeQuery instance for a task."""
    try:
        logger.info("Initializing task %s with work_dir %s", task_id, request.work_dir)

        # Create challenge task from task_id
        # This assumes the task is available in the work directory
        task_dir = Path(request.work_dir) / task_id
        if not task_dir.exists():
            raise HTTPException(
                status_code=400,
                detail=f"Task directory {task_dir} does not exist",
            )

        challenge_task = ChallengeTask(task_dir)
        work_dir = Path(request.work_dir)

        # Initialize CodeQuery
        codequery = CodeQueryPersistent(challenge_task, work_dir=work_dir)
        _codequery_instances[task_id] = codequery

        logger.info("Successfully initialized task %s", task_id)
        return TaskInitResponse(
            task_id=task_id,
            status="initialized",
            message="Task initialized successfully",
        )
    except HTTPException:
        # Re-raise HTTPExceptions as-is (like the 400 error for missing task_dir)
        raise
    except Exception as e:
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


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
