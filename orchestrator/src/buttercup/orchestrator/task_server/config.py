from pydantic_settings import BaseSettings
from typing import Annotated
from pydantic import Field
from pydantic_settings import CliImplicitFlag


class TaskServerSettings(BaseSettings):
    redis_url: Annotated[str, Field(default="redis://localhost:6379", description="Redis URL")]
    log_level: Annotated[str, Field(default="info", description="Log level")]
    host: Annotated[str, Field(default="127.0.0.1", description="Host")]
    port: Annotated[int, Field(default=8000, description="Port")]
    reload: CliImplicitFlag[bool] = Field(default=False, description="Reload source code on change")
    workers: Annotated[int, Field(default=1, description="Number of workers")]

    class Config:
        env_prefix = "BUTTERCUP_TASK_SERVER_"
        env_file = ".env"
        cli_parse_args = True
        extra = "allow"
