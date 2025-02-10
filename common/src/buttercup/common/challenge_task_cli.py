from pydantic_settings import BaseSettings, CliSubCommand, get_subcommand, CliImplicitFlag
from pydantic import BaseModel
from buttercup.common.challenge_task import ChallengeTask
from buttercup.common.logger import setup_package_logger
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


def handle_subcommand(task: ChallengeTask, subcommand: BaseModel):
    if isinstance(subcommand, BuildImageCommand):
        return task.build_image(
            pull_latest_base_image=subcommand.pull_latest_base_image,
            cache=subcommand.cache,
            architecture=subcommand.architecture,
        )
    elif isinstance(subcommand, BuildFuzzersCommand):
        if subcommand.use_cache:
            return task.build_fuzzers_with_cache(
                architecture=subcommand.architecture,
                engine=subcommand.engine,
                sanitizer=subcommand.sanitizer,
                env=subcommand.env,
            )
        else:
            return task.build_fuzzers(
                architecture=subcommand.architecture,
                engine=subcommand.engine,
                sanitizer=subcommand.sanitizer,
                env=subcommand.env,
            )
    elif isinstance(subcommand, CheckBuildCommand):
        return task.check_build(
            architecture=subcommand.architecture,
            engine=subcommand.engine,
            sanitizer=subcommand.sanitizer,
            env=subcommand.env,
        )
    elif isinstance(subcommand, ReproducePovCommand):
        return task.reproduce_pov(
            fuzzer_name=subcommand.fuzzer_name,
            crash_path=subcommand.crash_path,
            fuzzer_args=subcommand.fuzzer_args,
            architecture=subcommand.architecture,
            env=subcommand.env,
        )
    else:
        raise ValueError(f"Unknown subcommand: {subcommand}")


def main():
    settings = Settings()
    logger = setup_package_logger(__name__, "DEBUG")
    if settings.rw:
        task = ChallengeTask(
            read_only_task_dir=settings.task_dir,
            project_name=settings.project_name,
            python_path=settings.python_path,
            local_task_dir=settings.task_dir,
            logger=logger,
        )
    else:
        task = ChallengeTask(
            read_only_task_dir=settings.task_dir,
            project_name=settings.project_name,
            python_path=settings.python_path,
            logger=logger,
        )

    subcommand = get_subcommand(settings)
    with task.get_rw_copy(delete=False) as rw_task:
        result = handle_subcommand(rw_task, subcommand)

    print("Command result:", result.success)


if __name__ == "__main__":
    main()
