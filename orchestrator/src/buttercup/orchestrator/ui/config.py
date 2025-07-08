from pydantic_settings import BaseSettings
from typing import Annotated, Optional
from pydantic import Field
from pathlib import Path


class Settings(BaseSettings):
    # Server configuration
    redis_url: Annotated[str, Field(default="redis://localhost:6379", description="Redis URL")]
    log_level: Annotated[str, Field(default="debug", description="Log level")]
    reload: Annotated[bool, Field(default=False, description="Reload the server when code changes")]

    # Competition API configuration
    host: Annotated[str, Field(default="0.0.0.0", description="Host to bind the server to")]
    port: Annotated[int, Field(default=1323, description="Port to bind the server to")]

    # File server configuration
    challenges_dir: Annotated[
        Path, Field(default=Path("./challenges"), description="Directory containing challenge files")
    ]

    # Database configuration (for future use)
    database_url: Annotated[Optional[str], Field(default=None, description="Database URL for storing submissions")]

    class Config:
        env_prefix = "BUTTERCUP_UI_"
        env_file = ".env"
        cli_parse_args = True
        extra = "allow"
