"""HTTP client for program-model REST API."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import httpx
from pydantic import ValidationError

from buttercup.program_model.api.models import (
    ErrorResponse,
    FunctionModel,
    FunctionSearchResponse,
    HarnessInfoModel,
    HarnessSearchResponse,
    TaskInitRequest,
    TaskInitResponse,
    TypeDefinitionModel,
    TypeSearchResponse,
    TypeUsageInfoModel,
)
from buttercup.program_model.utils.common import (
    Function,
    TypeDefinition,
    TypeUsageInfo,
)

logger = logging.getLogger(__name__)


class ProgramModelClientError(Exception):
    """Exception raised by ProgramModelClient."""

    def __init__(self, message: str, status_code: Optional[int] = None, detail: Optional[str] = None):
        super().__init__(message)
        self.status_code = status_code
        self.detail = detail


class ProgramModelClient:
    """HTTP client for program-model REST API."""

    def __init__(self, base_url: str = "http://localhost:8000", timeout: float = 30.0):
        """Initialize the client.
        
        Args:
            base_url: Base URL of the program-model API server
            timeout: Request timeout in seconds
        """
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._client = httpx.Client(timeout=timeout)

    def _handle_error(self, response: httpx.Response) -> None:
        """Handle HTTP error responses."""
        try:
            error_data = response.json()
            if "error" in error_data:
                error_response = ErrorResponse.model_validate(error_data)
                raise ProgramModelClientError(
                    error_response.error,
                    status_code=response.status_code,
                    detail=error_response.detail,
                )
        except (ValidationError, ValueError):
            pass  # Fall back to generic error
        
        # Generic error handling
        response.raise_for_status()

    def initialize_task(self, task_id: str, work_dir: Path) -> TaskInitResponse:
        """Initialize a task in the program-model service."""
        try:
            request = TaskInitRequest(task_id=task_id, work_dir=str(work_dir))
            
            response = self._client.post(
                f"{self.base_url}/tasks/{task_id}/init",
                json=request.model_dump(),
            )
            
            if response.status_code != 200:
                self._handle_error(response)
            
            return TaskInitResponse.model_validate(response.json())
        except httpx.HTTPError as e:
            raise ProgramModelClientError(f"Failed to initialize task {task_id}: {e}")

    def get_functions(
        self,
        task_id: str,
        function_name: str,
        file_path: Optional[Path] = None,
        line_number: Optional[int] = None,
        fuzzy: bool = False,
        fuzzy_threshold: int = 80,
    ) -> list[Function]:
        """Get functions from the program-model service."""
        try:
            params = {
                "function_name": function_name,
                "fuzzy": fuzzy,
                "fuzzy_threshold": fuzzy_threshold,
            }
            if file_path:
                params["file_path"] = str(file_path)
            if line_number:
                params["line_number"] = line_number
            
            response = self._client.get(
                f"{self.base_url}/tasks/{task_id}/functions",
                params=params,
            )
            
            if response.status_code != 200:
                self._handle_error(response)
            
            search_response = FunctionSearchResponse.model_validate(response.json())
            return [func.to_domain() for func in search_response.functions]
        except httpx.HTTPError as e:
            raise ProgramModelClientError(f"Failed to get functions: {e}")

    def get_callers(
        self,
        task_id: str,
        function_name: str,
        file_path: Optional[Path] = None,
    ) -> list[Function]:
        """Get callers of a function."""
        try:
            params = {}
            if file_path:
                params["file_path"] = str(file_path)
            
            response = self._client.get(
                f"{self.base_url}/tasks/{task_id}/functions/{function_name}/callers",
                params=params,
            )
            
            if response.status_code != 200:
                self._handle_error(response)
            
            search_response = FunctionSearchResponse.model_validate(response.json())
            return [func.to_domain() for func in search_response.functions]
        except httpx.HTTPError as e:
            raise ProgramModelClientError(f"Failed to get callers: {e}")

    def get_callees(
        self,
        task_id: str,
        function_name: str,
        file_path: Optional[Path] = None,
        line_number: Optional[int] = None,
    ) -> list[Function]:
        """Get callees of a function."""
        try:
            params = {}
            if file_path:
                params["file_path"] = str(file_path)
            if line_number:
                params["line_number"] = line_number
            
            response = self._client.get(
                f"{self.base_url}/tasks/{task_id}/functions/{function_name}/callees",
                params=params,
            )
            
            if response.status_code != 200:
                self._handle_error(response)
            
            search_response = FunctionSearchResponse.model_validate(response.json())
            return [func.to_domain() for func in search_response.functions]
        except httpx.HTTPError as e:
            raise ProgramModelClientError(f"Failed to get callees: {e}")

    def get_types(
        self,
        task_id: str,
        type_name: str,
        file_path: Optional[Path] = None,
        function_name: Optional[str] = None,
        fuzzy: bool = False,
        fuzzy_threshold: int = 80,
    ) -> list[TypeDefinition]:
        """Get types from the program-model service."""
        try:
            params = {
                "type_name": type_name,
                "fuzzy": fuzzy,
                "fuzzy_threshold": fuzzy_threshold,
            }
            if file_path:
                params["file_path"] = str(file_path)
            if function_name:
                params["function_name"] = function_name
            
            response = self._client.get(
                f"{self.base_url}/tasks/{task_id}/types",
                params=params,
            )
            
            if response.status_code != 200:
                self._handle_error(response)
            
            search_response = TypeSearchResponse.model_validate(response.json())
            return [type_def.to_domain() for type_def in search_response.types]
        except httpx.HTTPError as e:
            raise ProgramModelClientError(f"Failed to get types: {e}")

    def get_type_calls(
        self,
        task_id: str,
        type_name: str,
        file_path: Optional[Path] = None,
    ) -> list[TypeUsageInfo]:
        """Get type calls from the program-model service."""
        try:
            params = {}
            if file_path:
                params["file_path"] = str(file_path)
            
            response = self._client.get(
                f"{self.base_url}/tasks/{task_id}/types/{type_name}/calls",
                params=params,
            )
            
            if response.status_code != 200:
                self._handle_error(response)
            
            usage_models = [TypeUsageInfoModel.model_validate(item) for item in response.json()]
            return [usage.to_domain() for usage in usage_models]
        except httpx.HTTPError as e:
            raise ProgramModelClientError(f"Failed to get type calls: {e}")

    def find_libfuzzer_harnesses(self, task_id: str) -> list[Path]:
        """Find libfuzzer harnesses."""
        try:
            response = self._client.get(f"{self.base_url}/tasks/{task_id}/harnesses/libfuzzer")
            
            if response.status_code != 200:
                self._handle_error(response)
            
            search_response = HarnessSearchResponse.model_validate(response.json())
            return [Path(harness) for harness in search_response.harnesses]
        except httpx.HTTPError as e:
            raise ProgramModelClientError(f"Failed to find libfuzzer harnesses: {e}")

    def find_jazzer_harnesses(self, task_id: str) -> list[Path]:
        """Find jazzer harnesses."""
        try:
            response = self._client.get(f"{self.base_url}/tasks/{task_id}/harnesses/jazzer")
            
            if response.status_code != 200:
                self._handle_error(response)
            
            search_response = HarnessSearchResponse.model_validate(response.json())
            return [Path(harness) for harness in search_response.harnesses]
        except httpx.HTTPError as e:
            raise ProgramModelClientError(f"Failed to find jazzer harnesses: {e}")

    def get_harness_source(self, task_id: str, harness_name: str) -> Optional[dict]:
        """Get harness source code."""
        try:
            response = self._client.get(
                f"{self.base_url}/tasks/{task_id}/harnesses/{harness_name}/source"
            )
            
            if response.status_code == 404:
                return None
            elif response.status_code != 200:
                self._handle_error(response)
            
            harness_info = HarnessInfoModel.model_validate(response.json())
            return {
                "file_path": Path(harness_info.file_path),
                "code": harness_info.code,
                "harness_name": harness_info.harness_name,
            }
        except httpx.HTTPError as e:
            raise ProgramModelClientError(f"Failed to get harness source: {e}")

    def cleanup_task(self, task_id: str) -> None:
        """Clean up a task."""
        try:
            response = self._client.delete(f"{self.base_url}/tasks/{task_id}")
            
            if response.status_code != 200:
                self._handle_error(response)
        except httpx.HTTPError as e:
            raise ProgramModelClientError(f"Failed to cleanup task: {e}")

    def close(self) -> None:
        """Close the HTTP client."""
        self._client.close()

    def __enter__(self) -> ProgramModelClient:
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()