from pydantic_settings import (
    BaseSettings,
)
from typing import Annotated
import tempfile
from pydantic import Field
from pathlib import Path


class Settings(BaseSettings):
    timeout: Annotated[int, Field(description="Timeout")]
    wdir: Annotated[Path, Field(default_factory=tempfile.mkdtemp, description="Working directory")]
    redis_url: Annotated[str, Field(default="redis://127.0.0.1:6379", description="Redis URL")]
    timer: Annotated[int, Field(default=1000, description="Timer in milliseconds")]
    log_level: Annotated[str, Field(default="info", description="Log level")]

    class Config:
        env_prefix = "BUTTERCUP_FUZZER_"
        env_file = ".env"
        cli_parse_args = True
        nested_model_default_partial_update = True
        env_nested_delimiter = "__"
        extra = "allow"
