from pydantic_settings import BaseSettings, CliPositionalArg, CliSubCommand
from pydantic import BaseModel
from typing import Annotated
from pydantic import Field
from pathlib import Path
from enum import Enum
import time
import uuid


class DownloaderServeCommand(BaseModel):
    sleep_time: Annotated[float, Field(default=1.0, description="Sleep time between checks in seconds")]
    redis_url: Annotated[str, Field(default="redis://localhost:6379", description="Redis URL")]

    class Config:
        nested_model_default_partial_update = True
        env_nested_delimiter = "__"


class TaskType(str, Enum):
    FULL = "full"
    DELTA = "delta"


class SourceType(str, Enum):
    REPO = "repo"
    FUZZ_TOOLING = "fuzz_tooling"
    DIFF = "diff"


class SourceDetail(BaseModel):
    source_type: SourceType
    url: str


class DownloaderProcessCommand(BaseModel):
    task_id: CliPositionalArg[str] = Field(description="Task ID")
    task_type: TaskType = Field(
        description="Task type",
        default=TaskType.FULL,
    )
    repo_url: list[str] = Field(description="Repo URL")
    fuzz_tooling_url: list[str] = Field(description="Fuzz tooling URL", default_factory=list)
    diff_url: list[str] = Field(description="Diff URL", default_factory=list)
    message_id: str = Field(description="Message ID", default_factory=lambda: str(uuid.uuid4()))
    message_time: int = Field(description="Message time", default_factory=lambda: int(time.time()))
    project_name: str = Field(description="Project name")
    focus: str = Field(description="Focus")

    class Config:
        nested_model_default_partial_update = True
        env_nested_delimiter = "__"


class DownloaderSettings(BaseSettings):
    download_dir: Annotated[Path, Field(default="/tmp/task_downloads", description="Directory for downloaded files")]
    log_level: Annotated[str, Field(default="info", description="Log level")]
    log_max_line_length: Annotated[int | None, Field(default=None, description="Log max line length")]
    serve: CliSubCommand[DownloaderServeCommand]
    process: CliSubCommand[DownloaderProcessCommand]

    class Config:
        env_prefix = "BUTTERCUP_DOWNLOADER_"
        env_file = ".env"
        cli_parse_args = True
        nested_model_default_partial_update = True
        env_nested_delimiter = "__"
        extra = "allow"
