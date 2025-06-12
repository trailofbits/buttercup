from pydantic_settings import BaseSettings
from typing import Annotated
from pydantic import Field


class Settings(BaseSettings):
    # Server configuration
    redis_url: Annotated[str, Field(default="redis://localhost:6379", description="Redis URL")]
    log_level: Annotated[str, Field(default="debug", description="Log level")]
    sleep_time: Annotated[float, Field(default=1.0, description="Sleep time between checks in seconds")]
    max_retries: Annotated[int, Field(default=10, description="Maximum number of retries for failed tasks")]

    class Config:
        env_prefix = "BUTTERCUP_POV_REPRODUCER_"
        env_file = ".env"
        cli_parse_args = True
        extra = "allow"
