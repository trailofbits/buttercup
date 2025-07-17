"""REST-based implementation of CodeQuery interface."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

from buttercup.common.challenge_task import ChallengeTask
from buttercup.program_model.client import ProgramModelClient, ProgramModelClientError
from buttercup.program_model.utils.common import Function, TypeDefinition, TypeUsageInfo

logger = logging.getLogger(__name__)


class CodeQueryRest:
    """REST-based implementation of CodeQuery interface.

    This class provides the same interface as CodeQuery but uses the REST API
    to communicate with the program-model service.
    """

    def __init__(self, challenge: ChallengeTask, base_url: Optional[str] = None):
        """Initialize the REST-based CodeQuery.

        Args:
            challenge: The challenge task
            base_url: Base URL of the program-model API server (defaults to env var or localhost)
        """
        self.challenge = challenge

        # Get base URL from environment or use default
        if base_url is None:
            base_url = os.getenv("PROGRAM_MODEL_API_URL", "http://localhost:8000")

        self.client = ProgramModelClient(base_url=base_url)

    @property
    def task_id(self) -> str:
        """Get the task ID from the challenge task."""
        return str(self.challenge.task_meta.task_id)

    def get_functions(
        self,
        function_name: str,
        file_path: Path | None = None,
        line_number: int | None = None,
        fuzzy: bool | None = False,
        fuzzy_threshold: int = 80,
        print_output: bool = True,
    ) -> list[Function]:
        """Get the definition(s) of a function in the codebase."""
        try:
            return self.client.get_functions(
                task_id=self.task_id,
                function_name=function_name,
                file_path=file_path,
                line_number=line_number,
                fuzzy=fuzzy or False,
                fuzzy_threshold=fuzzy_threshold,
            )
        except ProgramModelClientError as e:
            if print_output:
                logger.error("Failed to get functions: %s", e)
            return []

    def get_callers(
        self,
        function: Function | str,
        file_path: Path | None = None,
    ) -> list[Function]:
        """Get the callers of a function."""
        try:
            if isinstance(function, Function):
                function_name = function.name
                if file_path is None:
                    file_path = function.file_path
            else:
                function_name = function

            return self.client.get_callers(
                task_id=self.task_id,
                function_name=function_name,
                file_path=file_path,
            )
        except ProgramModelClientError as e:
            logger.error("Failed to get callers: %s", e)
            return []

    def get_callees(
        self,
        function: Function | str,
        file_path: Path | None = None,
        line_number: int | None = None,
    ) -> list[Function]:
        """Get the callees of a function."""
        try:
            if isinstance(function, Function):
                function_name = function.name
                if file_path is None:
                    file_path = function.file_path
            else:
                function_name = function

            return self.client.get_callees(
                task_id=self.task_id,
                function_name=function_name,
                file_path=file_path,
                line_number=line_number,
            )
        except ProgramModelClientError as e:
            logger.error("Failed to get callees: %s", e)
            return []

    def get_types(
        self,
        type_name: str,
        file_path: Path | None = None,
        function_name: str | None = None,
        fuzzy: bool | None = False,
        fuzzy_threshold: int = 80,
    ) -> list[TypeDefinition]:
        """Get type definitions."""
        try:
            return self.client.get_types(
                task_id=self.task_id,
                type_name=type_name,
                file_path=file_path,
                function_name=function_name,
                fuzzy=fuzzy or False,
                fuzzy_threshold=fuzzy_threshold,
            )
        except ProgramModelClientError as e:
            logger.error("Failed to get types: %s", e)
            return []

    def get_type_calls(self, type_definition: TypeDefinition) -> list[TypeUsageInfo]:
        """Get the calls to a type definition."""
        try:
            return self.client.get_type_calls(
                task_id=self.task_id,
                type_name=type_definition.name,
                file_path=type_definition.file_path,
            )
        except ProgramModelClientError as e:
            logger.error("Failed to get type calls: %s", e)
            return []

    def _get_container_src_dir(self) -> Path:
        """Get the container source directory (compatibility method)."""
        return Path(self.challenge.task_dir / "container_src_dir")

    def __repr__(self) -> str:
        return f"CodeQueryRest(challenge={self.challenge})"


class CodeQueryPersistentRest(CodeQueryRest):
    """REST-based implementation of CodeQueryPersistent interface.

    This class mimics the CodeQueryPersistent interface but uses REST API calls.
    """

    def __init__(
        self, challenge: ChallengeTask, work_dir: Path, base_url: Optional[str] = None
    ):
        """Initialize the persistent REST-based CodeQuery.

        Args:
            challenge: The challenge task
            work_dir: Working directory for the task
            base_url: Base URL of the program-model API server
        """
        super().__init__(challenge, base_url)
        self.work_dir = work_dir

        # Initialize the task in the remote service
        try:
            response = self.client.initialize_task(challenge, work_dir)
            logger.info(
                "Initialized task %s: %s", challenge.task_meta.task_id, response.message
            )

        except ProgramModelClientError as e:
            logger.error(
                "Failed to initialize task %s: %s", challenge.task_meta.task_id, e
            )
            raise e

    def __del__(self) -> None:
        """Clean up the task when the object is destroyed."""
        try:
            if hasattr(self, "client") and hasattr(self, "challenge"):
                self.client.cleanup_task(self.challenge.task_meta.task_id)
        except Exception:
            pass  # Ignore cleanup errors
