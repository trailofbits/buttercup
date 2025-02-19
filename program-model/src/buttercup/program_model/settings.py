from pydantic_settings import BaseSettings, CliSubCommand
from pydantic import BaseModel, Field
from typing import Annotated


class Config:
    cli_parse_args = True
    nested_model_default_partial_update = True
    env_nested_delimiter = "__"
    extra = "allow"
    env_prefix = "BUTTERCUP_PROGRAM_MODEL_"


class ButtercupBaseSettings(BaseSettings):
    class Config:
        cli_parse_args = True
        nested_model_default_partial_update = True
        env_nested_delimiter = "__"
        extra = "allow"


class BuilderSettings(BaseModel):
    allow_pull: Annotated[bool, Field(default=True, description="Allow pull")]
    base_image_url: Annotated[
        str, Field(default="gcr.io/oss-fuzz", description="Base image URL")
    ]


class WorkerSettings(BaseModel):
    redis_url: Annotated[
        str, Field(default="redis://127.0.0.1:6379", description="Redis URL")
    ]
    sleep_time: Annotated[
        float, Field(default=1.0, description="Sleep time between checks in seconds")
    ]
    wdir: Annotated[str, Field(default=..., description="Working directory")]
    python: Annotated[str, Field(default="python", description="Python path")]


class IndexerSettings(BaseModel):
    kythe_dir: Annotated[
        str, Field(default="scripts/gzs/kythe", description="Kythe directory")
    ]
    script_dir: Annotated[str, Field(default="scripts", description="Script directory")]


class ProgramModelServeCommand(WorkerSettings, IndexerSettings, BuilderSettings):
    pass


class ProgramModelProcessCommand(WorkerSettings, IndexerSettings, BuilderSettings):
    build_type: Annotated[str, Field(description="Build type", default=...)]
    package_name: Annotated[str, Field(description="Package name", default=...)]
    sanitizer: Annotated[str, Field(description="Sanitizer", default=...)]
    task_dir: Annotated[str, Field(description="Task directory", default=...)]
    task_id: Annotated[str, Field(description="Task ID", default=...)]


class ProgramModelSettings(ButtercupBaseSettings):
    log_level: Annotated[str, Field(default="info", description="Log level")]
    serve: CliSubCommand[ProgramModelServeCommand]
    process: CliSubCommand[ProgramModelProcessCommand]
    graphdb_url: Annotated[
        str,
        Field(description="Graph database URL", default="ws://graphdb:8182/gremlin"),
    ]
