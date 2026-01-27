from pathlib import Path
from typing import Annotated

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="BUTTERCUP_UI_",
        env_file=".env",
        cli_parse_args=True,
        extra="allow",
    )

    # Server configuration
    redis_url: Annotated[str, Field(default="redis://localhost:6379", description="Redis URL")]
    log_level: Annotated[str, Field(default="debug", description="Log level")]
    reload: Annotated[bool, Field(default=False, description="Reload the server when code changes")]

    # Competition API configuration
    external_host: Annotated[
        str,
        Field(default="localhost", description="External host, used to construct the files URLs"),
    ]
    host: Annotated[str, Field(default="127.0.0.1", description="Host to bind the server to")]
    port: Annotated[int, Field(default=1323, description="Port to bind the server to")]

    # File server configuration
    challenges_dir: Annotated[
        Path,
        Field(default=Path("./challenges"), description="Directory containing challenge files"),
    ]

    # CRS configuration
    crs_base_url: Annotated[str, Field(default="http://localhost:8000", description="CRS API base URL")]
    crs_key_id: Annotated[str | None, Field(default=None, description="Key ID for CRS authentication")]
    crs_key_token: Annotated[str | None, Field(default=None, description="Key token for CRS authentication")]

    # Storage configuration
    storage_dir: Annotated[
        Path,
        Field(default=Path("/tmp/buttercup-storage"), description="Directory for storing tarballs"),
    ]
    run_data_dir: Annotated[
        Path,
        Field(default=Path("/tmp/buttercup-run-data"), description="Directory for storing run data artifacts"),
    ]

    # Database configuration
    database_url: Annotated[
        str,
        Field(default="sqlite:///buttercup_ui.db", description="Database URL for storing submissions"),
    ]
