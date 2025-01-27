BUTTERCUP_TASK_CANCELLATION_REDIS_URL
from pydantic_settings import BaseSettings
from typing import Annotated
from pydantic import Field
from pydantic_settings import CliImplicitFlag


class TaskCancellationSettings(BaseSettings):
    redis_url: Annotated[str, Field(default="redis://localhost:6379", description="Redis URL")]
    log_level: Annotated[str, Field(default="info", description="Log level")]

    class Config:
        env_prefix = "BUTTERCUP_TASK_CANCELLATION_"
        env_file = ".env"
        cli_parse_args = True
        extra = "allow"
