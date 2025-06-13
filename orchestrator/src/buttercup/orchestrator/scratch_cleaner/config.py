from pydantic_settings import BaseSettings
from typing import Annotated
from pydantic import Field
from pathlib import Path


class Settings(BaseSettings):
    # Server configuration
    redis_url: Annotated[str, Field(default="redis://localhost:6379", description="Redis URL")]
    log_level: Annotated[str, Field(default="debug", description="Log level")]
    sleep_time: Annotated[float, Field(default=60.0, description="Sleep time between checks in seconds")]
    delete_old_tasks_scratch_delta_seconds: Annotated[
        int, Field(default=1800, description="Time in seconds after which to delete old task directories")
    ]
    scratch_dir: Annotated[Path, Field(default=Path("/node-local/scratch"), description="Scratch directory")]

    class Config:
        env_prefix = "BUTTERCUP_SCRATCH_CLEANER_"
        env_file = ".env"
        cli_parse_args = True
        extra = "allow"
