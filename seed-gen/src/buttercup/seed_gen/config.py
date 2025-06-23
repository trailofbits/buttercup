from pathlib import Path
from typing import Annotated

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, CliSubCommand


class ServerCommand(BaseModel):
    redis_url: Annotated[str, Field(default="redis://127.0.0.1:6379", description="Redis URL")]
    corpus_root: Annotated[Path | None, Field(default=None, description="Corpus root directory")]
    sleep_time: Annotated[int, Field(default=5, description="Sleep between runs (seconds)")]
    crash_dir_count_limit: Annotated[
        int | None,
        Field(
            default=None,
            description="Maximum number of crashes in the crash dir for a single token",
        ),
    ]
    max_corpus_seed_size: Annotated[
        int,
        Field(
            default=64 * 1024,  # 64 KiB
            description="Maximum size in bytes for seeds to be copied to corpus",
        ),
    ]
    max_pov_size: Annotated[
        int,
        Field(
            default=2 * 1024 * 1024,  # 2 MiB
            description="Maximum size in bytes for crash files to be submitted",
        ),
    ]


class ProcessCommand(BaseModel):
    challenge_task_dir: Annotated[Path, Field(description="Challenge task directory")]
    harness_name: Annotated[str, Field(description="Harness name")]
    package_name: Annotated[str, Field(description="Package name")]
    task_type: Annotated[
        str, Field(description="Task type (seed-init, seed-explore, vuln-discovery)")
    ]
    target_function: Annotated[
        str | None, Field(default=None, description="Target function for seed-explore")
    ]
    target_function_paths: Annotated[
        list[Path] | None, Field(default=None, description="Target function paths for seed-explore")
    ]
    output_dir: Annotated[Path, Field(description="Output directory for generated seeds")]

    build_output: Annotated[
        dict | None, Field(default=None, description="Build output for vuln-discovery task")
    ]


class Settings(BaseSettings):
    log_level: Annotated[str, Field(default="info", description="Log level")]
    log_max_line_length: Annotated[
        int | None, Field(default=None, description="Log max line length")
    ]
    wdir: Annotated[Path, Field(description="Working directory")]

    server: CliSubCommand[ServerCommand]
    process: CliSubCommand[ProcessCommand]

    model_config = {
        "env_prefix": "BUTTERCUP_SEED_GEN_",
        "env_file": ".env",
        "cli_parse_args": True,
        "nested_model_default_partial_update": True,
        "env_nested_delimiter": "__",
        "extra": "allow",
    }
