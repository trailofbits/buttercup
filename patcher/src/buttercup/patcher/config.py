from pydantic_settings import BaseSettings, CliPositionalArg, CliSubCommand, CliImplicitFlag
from pydantic import BaseModel
from typing import Annotated
from pydantic import Field
from pathlib import Path


class ServeCommand(BaseModel):
    sleep_time: Annotated[float, Field(default=1.0, description="Sleep time between checks in seconds")]
    redis_url: Annotated[str, Field(default="redis://localhost:6379", description="Redis URL")]

    class Config:
        nested_model_default_partial_update = True
        env_nested_delimiter = "__"


class ProcessCommand(BaseModel):
    task_id: CliPositionalArg[str] = Field(description="Task ID")
    vulnerability_id: CliPositionalArg[str] = Field(description="Vulnerability ID")
    package_name: CliPositionalArg[str] = Field(description="Package Name")
    sanitizer: CliPositionalArg[str] = Field(description="Sanitizer")
    harness_path: CliPositionalArg[str] = Field(description="Harness Path")
    data_file: CliPositionalArg[str] = Field(description="Data File")
    architecture: CliPositionalArg[str] = Field(description="Architecture")

    class Config:
        nested_model_default_partial_update = True
        env_nested_delimiter = "__"


class Settings(BaseSettings):
    task_storage_dir: Annotated[Path, Field(default="/tmp/task_downloads", description="Directory for task storage")]
    log_level: Annotated[str, Field(default="info", description="Log level")]
    mock_mode: CliImplicitFlag[bool] = Field(default=False, description="Mock mode")

    serve: CliSubCommand[ServeCommand]
    process: CliSubCommand[ProcessCommand]

    class Config:
        env_prefix = "BUTTERCUP_PATCHER_"
        env_file = ".env"
        cli_parse_args = True
        nested_model_default_partial_update = True
        env_nested_delimiter = "__"
