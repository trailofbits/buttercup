"""Pydantic models for REST API requests and responses."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

from buttercup.program_model.utils.common import (
    Function,
    FunctionBody,
    TypeDefinition,
    TypeDefinitionType,
    TypeUsageInfo,
)


class FunctionBodyModel(BaseModel):
    """API model for function body."""

    body: str = Field(..., description="Body of the function")
    start_line: int = Field(..., description="Start line of the function in the file (1-based)")
    end_line: int = Field(..., description="End line of the function in the file (1-based)")

    @classmethod
    def from_domain(cls, func_body: FunctionBody) -> FunctionBodyModel:
        """Convert domain model to API model."""
        return cls(
            body=func_body.body,
            start_line=func_body.start_line,
            end_line=func_body.end_line,
        )

    def to_domain(self) -> FunctionBody:
        """Convert API model to domain model."""
        return FunctionBody(
            body=self.body,
            start_line=self.start_line,
            end_line=self.end_line,
        )


class FunctionModel(BaseModel):
    """API model for function."""

    name: str = Field(..., description="Name of the function")
    file_path: str = Field(..., description="Path to the file containing the function")
    bodies: list[FunctionBodyModel] = Field(
        default_factory=list, description="List of function bodies"
    )

    @classmethod
    def from_domain(cls, func: Function) -> FunctionModel:
        """Convert domain model to API model."""
        return cls(
            name=func.name,
            file_path=str(func.file_path),
            bodies=[FunctionBodyModel.from_domain(body) for body in func.bodies],
        )

    def to_domain(self) -> Function:
        """Convert API model to domain model."""
        return Function(
            name=self.name,
            file_path=Path(self.file_path),
            bodies=[body.to_domain() for body in self.bodies],
        )


class TypeDefinitionModel(BaseModel):
    """API model for type definition."""

    name: str = Field(..., description="Name of the type")
    type: TypeDefinitionType = Field(..., description="Type of the type")
    definition: str = Field(..., description="Definition of the type")
    definition_line: int = Field(..., description="Line number of the definition (1-based)")
    file_path: str = Field(..., description="Path to the file containing the type definition")

    @classmethod
    def from_domain(cls, type_def: TypeDefinition) -> TypeDefinitionModel:
        """Convert domain model to API model."""
        return cls(
            name=type_def.name,
            type=type_def.type,
            definition=type_def.definition,
            definition_line=type_def.definition_line,
            file_path=str(type_def.file_path),
        )

    def to_domain(self) -> TypeDefinition:
        """Convert API model to domain model."""
        return TypeDefinition(
            name=self.name,
            type=self.type,
            definition=self.definition,
            definition_line=self.definition_line,
            file_path=Path(self.file_path),
        )


class TypeUsageInfoModel(BaseModel):
    """API model for type usage information."""

    name: str = Field(..., description="Name of the type being used")
    file_path: str = Field(..., description="Path to the file containing the type usage")
    line_number: int = Field(..., description="Line number of the type usage (1-based)")

    @classmethod
    def from_domain(cls, type_usage: TypeUsageInfo) -> TypeUsageInfoModel:
        """Convert domain model to API model."""
        return cls(
            name=type_usage.name,
            file_path=str(type_usage.file_path),
            line_number=type_usage.line_number,
        )

    def to_domain(self) -> TypeUsageInfo:
        """Convert API model to domain model."""
        return TypeUsageInfo(
            name=self.name,
            file_path=Path(self.file_path),
            line_number=self.line_number,
        )


class HarnessInfoModel(BaseModel):
    """API model for harness information."""

    file_path: str = Field(..., description="Path to the harness file")
    code: str = Field(..., description="Harness source code")
    harness_name: str = Field(..., description="Name of the harness")


class FunctionSearchRequest(BaseModel):
    """Request model for function search."""

    function_name: str = Field(..., description="Name of the function to search for")
    file_path: Optional[str] = Field(None, description="Optional file path to search within")
    line_number: Optional[int] = Field(None, description="Optional line number to search around")
    fuzzy: bool = Field(False, description="Enable fuzzy matching")
    fuzzy_threshold: int = Field(80, description="Fuzzy matching threshold (0-100)")


class FunctionSearchResponse(BaseModel):
    """Response model for function search."""

    functions: list[FunctionModel] = Field(..., description="List of matching functions")
    total_count: int = Field(..., description="Total number of functions found")


class TypeSearchRequest(BaseModel):
    """Request model for type search."""

    type_name: str = Field(..., description="Name of the type to search for")
    file_path: Optional[str] = Field(None, description="Optional file path to search within")
    function_name: Optional[str] = Field(None, description="Optional function name to search within")
    fuzzy: bool = Field(False, description="Enable fuzzy matching")
    fuzzy_threshold: int = Field(80, description="Fuzzy matching threshold (0-100)")


class TypeSearchResponse(BaseModel):
    """Response model for type search."""

    types: list[TypeDefinitionModel] = Field(..., description="List of matching types")
    total_count: int = Field(..., description="Total number of types found")


class HarnessSearchResponse(BaseModel):
    """Response model for harness search."""

    harnesses: list[str] = Field(..., description="List of harness file paths")
    total_count: int = Field(..., description="Total number of harnesses found")


class TaskInitRequest(BaseModel):
    """Request model for task initialization."""

    task_id: str = Field(..., description="ID of the task to initialize")
    work_dir: str = Field(..., description="Working directory for the task")


class TaskInitResponse(BaseModel):
    """Response model for task initialization."""

    task_id: str = Field(..., description="ID of the initialized task")
    status: str = Field(..., description="Initialization status")
    message: str = Field(..., description="Status message")


class ErrorResponse(BaseModel):
    """Error response model."""

    error: str = Field(..., description="Error message")
    detail: Optional[str] = Field(None, description="Additional error details")
    code: Optional[str] = Field(None, description="Error code")