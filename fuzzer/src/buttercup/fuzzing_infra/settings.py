from pydantic_settings import BaseSettings
from pydantic import Field
from typing import Annotated


class Config:
    cli_parse_args = True
    nested_model_default_partial_update = True
    env_nested_delimiter = "__"
    extra = "allow"
    env_prefix = "BUTTERCUP_FUZZER_"


class ButtercupBaseSettings(BaseSettings):
    class Config:
        cli_parse_args = True
        nested_model_default_partial_update = True
        env_nested_delimiter = "__"
        extra = "allow"


class BuilderSettings(ButtercupBaseSettings):
    allow_pull: Annotated[bool, Field(default=True)]
    base_image_url: Annotated[str, Field(default="gcr.io/oss-fuzz")]


class WorkerSettings(ButtercupBaseSettings):
    redis_url: Annotated[str, Field(default="redis://127.0.0.1:6379")]
    timer: Annotated[int, Field(default=1000)]
    wdir: Annotated[str, Field(default=...)]
    python: Annotated[str, Field(default="python")]
    log_level: Annotated[str, Field(default="INFO")]


class FuzzerBotSettings(WorkerSettings):
    timeout: Annotated[int, Field(default="")]


class CoverageBotSettings(WorkerSettings, BuilderSettings):
    llvm_cov_tool: Annotated[str, Field(default="llvm-cov")]


class BuilderBotSettings(WorkerSettings, BuilderSettings):
    allow_caching: Annotated[bool, Field(default=False)]
