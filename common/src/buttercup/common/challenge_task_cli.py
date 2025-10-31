from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from pydantic import BaseModel
from pydantic_settings import BaseSettings, CliImplicitFlag, CliSubCommand, get_subcommand

from buttercup.common.challenge_task import ChallengeTask, CommandResult, ReproduceResult
from buttercup.common.constants import ARCHITECTURE
from buttercup.common.logger import setup_package_logger


class BuildImageCommand(BaseModel):
    pull_latest_base_image: bool = False
    cache: bool | None = None
    architecture: str = ARCHITECTURE


class ApplyPatchCommand(BaseModel):
    diff_file: Path | None = None


class BuildFuzzersCommand(BaseModel):
    architecture: str = ARCHITECTURE
    engine: str | None = None
    sanitizer: str | None = None
    env: dict[str, str] | None = None
    use_cache: bool = True


class CheckBuildCommand(BaseModel):
    architecture: str = ARCHITECTURE
    engine: str | None = None
    sanitizer: str | None = None
    env: dict[str, str] | None = None


class ReproducePovCommand(BaseModel):
    fuzzer_name: str
    crash_path: Path
    fuzzer_args: list[str] | None = None
    architecture: str = ARCHITECTURE
    env: dict[str, str] | None = None


class Settings(BaseSettings):
    task_dir: Path
    python_path: Path = Path("python")
    rw: CliImplicitFlag[bool] = False

    apply_patch: CliSubCommand[ApplyPatchCommand]
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


def handle_subcommand(task: ChallengeTask, subcommand: BaseModel | None) -> CommandResult | ReproduceResult:
    if isinstance(subcommand, BuildImageCommand):
        return task.build_image(
            pull_latest_base_image=subcommand.pull_latest_base_image,
            cache=subcommand.cache,
            architecture=subcommand.architecture,
        )
    if isinstance(subcommand, BuildFuzzersCommand):
        if subcommand.use_cache:
            return task.build_fuzzers_with_cache(
                architecture=subcommand.architecture,
                engine=subcommand.engine,
                sanitizer=subcommand.sanitizer,
                env=subcommand.env,
            )
        return task.build_fuzzers(
            architecture=subcommand.architecture,
            engine=subcommand.engine,
            sanitizer=subcommand.sanitizer,
            env=subcommand.env,
        )
    if isinstance(subcommand, CheckBuildCommand):
        return task.check_build(
            architecture=subcommand.architecture,
            engine=subcommand.engine,
            sanitizer=subcommand.sanitizer,
            env=subcommand.env,
        )
    if isinstance(subcommand, ReproducePovCommand):
        return task.reproduce_pov(
            fuzzer_name=subcommand.fuzzer_name,
            crash_path=subcommand.crash_path,
            fuzzer_args=subcommand.fuzzer_args,
            architecture=subcommand.architecture,
            env=subcommand.env,
        ).command_result
    if isinstance(subcommand, ApplyPatchCommand):
        return CommandResult(success=task.apply_patch_diff(diff_file=subcommand.diff_file))
    raise ValueError(f"Unknown subcommand: {subcommand}")


@contextmanager
def get_task_copy(task: ChallengeTask, use_copy: bool = False) -> Iterator[ChallengeTask]:
    if use_copy:
        with task.get_rw_copy(None, delete=False) as task_copy:
            yield task_copy
    else:
        yield task


def main() -> None:
    settings = Settings()
    setup_package_logger("challenge-task-cli", __name__, "DEBUG")
    if settings.rw:
        task = ChallengeTask(
            read_only_task_dir=settings.task_dir,
            python_path=settings.python_path,
            local_task_dir=settings.task_dir,
        )
    else:
        task = ChallengeTask(
            read_only_task_dir=settings.task_dir,
            python_path=settings.python_path,
        )

    subcommand = get_subcommand(settings)
    with get_task_copy(task, not settings.rw) as rw_task:
        result = handle_subcommand(rw_task, subcommand)

    if isinstance(result, ReproduceResult):
        result = result.command_result

    print("Command result:", result.success)


if __name__ == "__main__":
    main()
