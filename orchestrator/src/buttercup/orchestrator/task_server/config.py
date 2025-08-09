from pydantic_settings import BaseSettings
from typing import Annotated
from pydantic import Field
from pydantic_settings import CliImplicitFlag


class TaskServerSettings(BaseSettings):
    # Server configuration
    redis_url: Annotated[str, Field(default="redis://localhost:6379", description="Redis URL")]
    log_level: Annotated[str, Field(default="info", description="Log level")]
    log_max_line_length: Annotated[int | None, Field(default=None, description="Log max line length")]
    host: Annotated[str, Field(default="127.0.0.1", description="Host")]
    port: Annotated[int, Field(default=8000, description="Port")]
    reload: CliImplicitFlag[bool] = Field(default=False, description="Reload source code on change")
    workers: Annotated[int, Field(default=1, description="Number of workers")]

    # Authentication configuration
    api_key_id: Annotated[str, Field(default="", description="API key ID for authentication")]
    api_token_hash: Annotated[str, Field(default="", description="Argon2id hash of the API token")]

    # Competition API configuration
    competition_api_url: Annotated[str, Field(default="http://localhost:1323", description="Competition API URL")]
    competition_api_username: Annotated[str, Field(default="", description="Competition API username")]
    competition_api_password: Annotated[str, Field(default="", description="Competition API password")]

    class Config:
        env_prefix = "BUTTERCUP_TASK_SERVER_"
        env_file = ".env"
        cli_parse_args = True
        extra = "allow"
