from pydantic_settings import BaseSettings, CliSubCommand
from pydantic import BaseModel
from typing import Annotated
from pydantic import Field
from pathlib import Path


class ServeCommand(BaseSettings):
    sleep_time: Annotated[float, Field(default=1.0, description="Sleep time between checks in seconds")]
    redis_url: Annotated[str, Field(default="redis://localhost:6379", description="Redis URL")]
    competition_api_url: Annotated[str, Field(default="http://competition-api:8080", description="Competition API URL")]
    competition_api_key_id: Annotated[str, Field(default="api_key_id", description="Competition API username")]
    competition_api_key_token: Annotated[str, Field(default="api_key_token", description="Competition API password")]
    competition_api_cycle_time: Annotated[
        float, Field(default=10.0, description="Min seconds between competition api interactions")
    ]
    patch_submission_retry_limit: Annotated[
        int, Field(default=60, description="Number of retries for errored patch submissions.")
    ]
    patch_requests_per_vulnerability: Annotated[
        int, Field(default=1, description="Number of patch requests per vulnerability")
    ]
    concurrent_patch_requests_per_task: Annotated[
        int, Field(default=12, description="Number of concurrent patch requests per task")
    ]

    class Config:
        nested_model_default_partial_update = True
        env_nested_delimiter = "__"


class ProcessReadyTaskCommand(BaseModel):
    task_id: Annotated[str, Field(description="Task ID")]
    task_type: Annotated[str, Field(description="Task type")]
    task_status: Annotated[str, Field(description="Task status")]

    class Config:
        nested_model_default_partial_update = True
        env_nested_delimiter = "__"


class ProcessBuildOutputCommand(BaseModel):
    package_name: Annotated[str, Field(description="Package name")]
    engine: Annotated[str, Field(description="Engine")]
    sanitizer: Annotated[str, Field(description="Sanitizer")]
    output_ossfuzz_path: Annotated[str, Field(description="Output ossfuzz path")]
    source_path: Annotated[str, Field(description="Source path")]

    class Config:
        nested_model_default_partial_update = True
        env_nested_delimiter = "__"


class Settings(BaseSettings):
    tasks_storage_dir: Annotated[Path, Field(default="/tmp/task_downloads", description="Directory for Tasks storage")]
    scratch_dir: Annotated[Path, Field(default="/tmp/crs_scratch", description="Directory for CRS scratch")]
    log_level: Annotated[str, Field(default="info", description="Log level")]
    log_max_line_length: Annotated[int | None, Field(default=None, description="Log max line length")]

    serve: CliSubCommand[ServeCommand]
    process_ready_task: CliSubCommand[ProcessReadyTaskCommand]
    process_build_output: CliSubCommand[ProcessBuildOutputCommand]

    class Config:
        env_prefix = "BUTTERCUP_SCHEDULER_"
        env_file = ".env"
        cli_parse_args = True
        nested_model_default_partial_update = True
        env_nested_delimiter = "__"
        extra = "allow"
