from pydantic_settings import (
    BaseSettings,
    CliSubCommand,
    SettingsConfigDict,
)
from pydantic import BaseModel, Field
from typing import Annotated
from pathlib import Path


class BuilderSettings(BaseModel):
    allow_pull: Annotated[bool, Field(default=True, description="Allow pull")]


class WorkerSettings(BaseModel):
    redis_url: Annotated[
        str, Field(default="redis://localhost:6379", description="Redis URL")
    ]
    sleep_time: Annotated[
        float, Field(default=1.0, description="Sleep time between checks in seconds")
    ]
    python: Annotated[str, Field(default="python", description="Python path")]


class ServeCommand(WorkerSettings, BuilderSettings):
    pass


class ProcessCommand(WorkerSettings, BuilderSettings):
    task_dir: Annotated[str, Field(description="Task directory", default=...)]
    task_id: Annotated[str, Field(description="Task ID", default=...)]


class Settings(BaseSettings):
    scratch_dir: Annotated[
        Path, Field(default="/tmp/scratch", description="Directory for scratch space")
    ]
    log_level: Annotated[str, Field(default="info", description="Log level")]
    log_max_line_length: Annotated[
        int | None, Field(default=None, description="Log max line length")
    ]

    serve: CliSubCommand[ServeCommand]
    process: CliSubCommand[ProcessCommand]

    model_config = SettingsConfigDict(
        env_prefix="BUTTERCUP_PROGRAM_MODEL_",
        env_file=".env",
        cli_parse_args=True,
        nested_model_default_partial_update=True,
        env_nested_delimiter="__",
    )
