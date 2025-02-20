from pydantic_settings import BaseSettings, CliPositionalArg, CliSubCommand, CliImplicitFlag, SettingsConfigDict
from pydantic import BaseModel
from typing import Annotated
from pydantic import Field
from pathlib import Path


class ServeCommand(BaseModel):
    sleep_time: Annotated[float, Field(default=1.0, description="Sleep time between checks in seconds")]
    redis_url: Annotated[str, Field(default="redis://localhost:6379", description="Redis URL")]


class ProcessCommand(BaseModel):
    challenge_task_dir: CliPositionalArg[Path] = Field(description="Challenge Task Directory")
    task_id: CliPositionalArg[str] = Field(description="Task ID")
    vulnerability_id: CliPositionalArg[str] = Field(description="Vulnerability ID")
    harness_name: CliPositionalArg[str] = Field(description="Harness Name")
    engine: CliPositionalArg[str] = Field(description="Engine")
    sanitizer: CliPositionalArg[str] = Field(description="Sanitizer")
    crash_input_path: CliPositionalArg[str] = Field(description="Crash Input Path")
    stacktrace_path: CliPositionalArg[str] = Field(description="Stacktrace Path")


class Settings(BaseSettings):
    task_storage_dir: Annotated[Path, Field(default="/tmp/task_downloads", description="Directory for task storage")]
    scratch_dir: Annotated[Path, Field(default="/tmp/scratch", description="Directory for scratch space")]
    log_level: Annotated[str, Field(default="info", description="Log level")]
    mock_mode: CliImplicitFlag[bool] = Field(default=False, description="Mock mode")
    dev_mode: CliImplicitFlag[bool] = Field(default=False, description="Dev mode")

    serve: CliSubCommand[ServeCommand]
    process: CliSubCommand[ProcessCommand]

    model_config = SettingsConfigDict(
        env_prefix="BUTTERCUP_PATCHER_",
        env_file=".env",
        cli_parse_args=True,
        nested_model_default_partial_update=True,
        env_nested_delimiter="__",
    )
