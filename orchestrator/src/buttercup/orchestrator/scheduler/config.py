from pydantic_settings import BaseSettings, CliSubCommand, CliImplicitFlag
from pydantic import BaseModel
from typing import Annotated
from pydantic import Field
from pathlib import Path


class ServeCommand(BaseModel):
    sleep_time: Annotated[float, Field(default=1.0, description="Sleep time between checks in seconds")]
    redis_url: Annotated[str, Field(default="redis://localhost:6379", description="Redis URL")]
    mock_mode: CliImplicitFlag[bool] = Field(default=False, description="Mock mode")

    class Config:
        nested_model_default_partial_update = True
        env_nested_delimiter = "__"


class ProcessCommand(BaseModel):
    pass

    class Config:
        nested_model_default_partial_update = True
        env_nested_delimiter = "__"


class Settings(BaseSettings):
    download_dir: Annotated[Path, Field(default="/tmp/task_downloads", description="Directory for downloaded files")]
    log_level: Annotated[str, Field(default="info", description="Log level")]
    serve: CliSubCommand[ServeCommand]
    process: CliSubCommand[ProcessCommand]

    class Config:
        env_prefix = "BUTTERCUP_SCHEDULER_"
        env_file = ".env"
        cli_parse_args = True
        nested_model_default_partial_update = True
        env_nested_delimiter = "__"
        extra = "allow"
