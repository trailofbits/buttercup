from pydantic_settings import BaseSettings, CliPositionalArg, CliSubCommand
from pydantic import BaseModel
from typing import Annotated
from pydantic import Field
from enum import Enum
import time
import uuid


class TaskType(str, Enum):
    FULL = "full"
    DELTA = "delta"


class ProgramModelServeCommand(BaseModel):
    sleep_time: Annotated[float, Field(default=1.0, description="Sleep time between checks in seconds")]
    redis_url: Annotated[str, Field(default="redis://localhost:6379", description="Redis URL")]

    class Config:
        nested_model_default_partial_update = True
        env_nested_delimiter = "__"


class ProgramModelProcessCommand(BaseModel):
    package_name: str = Field(
        description="Package name",
        default="",
    )
    ossfuzz: str = Field(
        description="OSSFuzz directory",
        default="",
    )
    source_path: str = Field(
        description="Source path",
        default="",
    )
    task_id: str = Field(
        description="Task ID",
        default="",
    )
    build_type: TaskType = Field(
        description="Build type",
        default=TaskType.FULL,
    )

    class Config:
        nested_model_default_partial_update = True
        env_nested_delimiter = "__"


class ProgramModelSettings(BaseSettings):
    log_level: Annotated[str, Field(default="info", description="Log level")]
    serve: CliSubCommand[ProgramModelServeCommand]
    process: CliSubCommand[ProgramModelProcessCommand]

    class Config:
        env_prefix = "BUTTERCUP_PROGRAM_MODEL_"
        env_file = ".env"
        cli_parse_args = True
        nested_model_default_partial_update = True
        env_nested_delimiter = "__"
        extra = "allow"
