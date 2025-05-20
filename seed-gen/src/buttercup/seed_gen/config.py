from pathlib import Path
from typing import Annotated

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, CliSubCommand


class ServerCommand(BaseModel):
    redis_url: Annotated[str, Field(default="redis://127.0.0.1:6379", description="Redis URL")]
    wdir: Annotated[Path, Field(description="Working directory")]
    corpus_root: Annotated[Path | None, Field(default=None, description="Corpus root directory")]
    sleep_time: Annotated[int, Field(default=5, description="Sleep between runs (seconds)")]
    crash_dir_count_limit: Annotated[
        int | None,
        Field(
            default=None,
            description="Maximum number of crashes in the crash dir for a single token",
        ),
    ]


class Settings(BaseSettings):
    log_level: Annotated[str, Field(default="info", description="Log level")]

    server: CliSubCommand[ServerCommand]

    model_config = {
        "env_prefix": "BUTTERCUP_SEED_GEN_",
        "env_file": ".env",
        "cli_parse_args": True,
        "nested_model_default_partial_update": True,
        "env_nested_delimiter": "__",
        "extra": "allow",
    }
