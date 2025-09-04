from typing import Annotated

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ServerSettings(BaseSettings):
    host: Annotated[str, Field(default="0.0.0.0")]
    port: Annotated[int, Field(default=8000)]
    timeout: Annotated[int, Field(default=1000)]  # in seconds
    log_level: Annotated[str, Field(default="info")]
    reload: Annotated[bool, Field(default=False)]
    workers: Annotated[int, Field(default=1)]

    model_config = SettingsConfigDict(
        env_prefix="BUTTERCUP_FUZZER_RUNNER_",
        env_file=".env",
        cli_parse_args=True,
        nested_model_default_partial_update=True,
        env_nested_delimiter="__",
        extra="allow",
    )
