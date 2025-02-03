from pydantic_settings import BaseSettings, CliSubCommand, get_subcommand, CliImplicitFlag
from pydantic import BaseModel
from buttercup.common.challenge_task import ChallengeTask
from buttercup.common.logger import setup_logging
from pathlib import Path
from typing import Dict


class BuildImageCommand(BaseModel):
    pull_latest_base_image: bool = False
    cache: bool | None = None
    architecture: str | None = None


class BuildFuzzersCommand(BaseModel):
    architecture: str | None = None
    engine: str | None = None
    sanitizer: str | None = None
    env: Dict[str, str] | None = None
    use_cache: bool = True


class CheckBuildCommand(BaseModel):
    architecture: str | None = None
    engine: str | None = None
    sanitizer: str | None = None
    env: Dict[str, str] | None = None


class ReproducePovCommand(BaseModel):
    fuzzer_name: str
    crash_path: Path
    fuzzer_args: list[str] | None = None
    architecture: str | None = None
    env: Dict[str, str] | None = None


class Settings(BaseSettings):
    task_dir: Path
    project_name: str
    python_path: Path = Path("python")
    rw: CliImplicitFlag[bool] = False

    build_image: CliSubCommand[BuildImageCommand]
    build_fuzzers: CliSubCommand[BuildFuzzersCommand]
    check_build: CliSubCommand[CheckBuildCommand]
    reproduce_pov: CliSubCommand[ReproducePovCommand]

    class Config:
        env_prefix = "BUTTERCUP_CHALLENGE_TASK_"
        env_file = ".env"
        cli_parse_args = True
        nested_model_default_partial_update = True
        env_nested_delimiter = "__"
        extra = "allow"


def main():
    settings = Settings()
    logger = setup_logging(__name__, "DEBUG")
    task = ChallengeTask(
        read_only_task_dir=settings.task_dir,
        project_name=settings.project_name,
        python_path=settings.python_path,
        local_task_dir=settings.task_dir if settings.rw else None,
        logger=logger,
    )

    subcommand = get_subcommand(settings)
    if isinstance(subcommand, BuildImageCommand):
        result = task.build_image(
            pull_latest_base_image=subcommand.pull_latest_base_image,
            cache=subcommand.cache,
            architecture=subcommand.architecture,
        )
    elif isinstance(subcommand, BuildFuzzersCommand):
        result = task.build_fuzzers(
            architecture=subcommand.architecture,
            engine=subcommand.engine,
            sanitizer=subcommand.sanitizer,
            env=subcommand.env,
            use_cache=subcommand.use_cache,
        )
    elif isinstance(subcommand, CheckBuildCommand):
        result = task.check_build(
            architecture=subcommand.architecture,
            engine=subcommand.engine,
            sanitizer=subcommand.sanitizer,
            env=subcommand.env,
        )
    elif isinstance(subcommand, ReproducePovCommand):
        result = task.reproduce_pov(
            fuzzer_name=subcommand.fuzzer_name,
            crash_path=subcommand.crash_path,
            fuzzer_args=subcommand.fuzzer_args,
            architecture=subcommand.architecture,
            env=subcommand.env,
        )

    print("Command result:", result.success)


if __name__ == "__main__":
    main()
