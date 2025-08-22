import logging
from pathlib import Path
from typing import Annotated
from uuid import uuid4

from google.protobuf.text_format import Parse
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, CliPositionalArg, CliSubCommand, get_subcommand
from redis import Redis

from buttercup.common.datastructures.msg_pb2 import (
    BuildOutput,
    BuildType,
    SubmissionEntry,
    SubmissionResult,
    WeightedHarness,
)
from buttercup.common.logger import setup_package_logger
from buttercup.common.maps import (
    BuildMap,
    HarnessWeights,
)
from buttercup.common.queues import QueueFactory, QueueNames, ReliableQueue
from buttercup.common.task_registry import TaskRegistry

logger = logging.getLogger(__name__)

TaskId = str


class TaskResult(BaseModel):
    task_id: TaskId
    project_name: str
    mode: str
    n_vulnerabilities: int = 0
    n_patches: int = 0
    n_bundles: int = 0
    patched_vulnerabilities: list[str] = []
    non_patched_vulnerabilities: list[str] = []


def truncate_stacktraces(submission: SubmissionEntry, max_length: int = 80) -> SubmissionEntry:
    """Create a copy of the submission with truncated stacktraces for display purposes."""
    # Create a new submission and copy the fields manually to ensure proper truncation
    from google.protobuf import text_format

    # Serialize to text and then parse back to create a proper copy
    submission_text = text_format.MessageToString(submission)
    truncated_submission = SubmissionEntry()
    text_format.Parse(submission_text, truncated_submission)

    # Now truncate the stacktraces and crash token
    for crash_with_id in truncated_submission.crashes:
        crash = crash_with_id.crash
        if crash.crash.stacktrace and len(crash.crash.stacktrace) > max_length:
            crash.crash.stacktrace = crash.crash.stacktrace[:max_length] + "... (truncated)"

        if crash.tracer_stacktrace and len(crash.tracer_stacktrace) > max_length:
            crash.tracer_stacktrace = crash.tracer_stacktrace[:max_length] + "... (truncated)"

        if crash.crash.crash_token and len(crash.crash.crash_token) > max_length:
            crash.crash.crash_token = crash.crash.crash_token[:max_length] + "... (truncated)"

    return truncated_submission


def get_queue_names() -> list[str]:
    return [f"'{queue_name.value}'" for queue_name in QueueNames]


def get_build_types() -> list[str]:
    return [f"'{build_type} ({BuildType.Name(build_type)})'" for build_type in BuildType.values()]


class SendSettings(BaseModel):
    queue_name: CliPositionalArg[str] = Field(description="Queue name (one of " + ", ".join(get_queue_names()) + ")")
    msg_path: CliPositionalArg[Path] = Field(description="Path to message file in Protobuf text format")


class ReadSettings(BaseModel):
    queue_name: CliPositionalArg[str] = Field(description="Queue name (one of " + ", ".join(get_queue_names()) + ")")
    group_name: Annotated[str | None, Field(description="Group name")] = None


class ListSettings(BaseModel):
    pass


class ReadHarnessWeightSettings(BaseModel):
    pass


class ReadBuildsSettings(BaseModel):
    task_id: CliPositionalArg[str] = Field(description="Task ID")
    build_type: CliPositionalArg[str] = Field(description="Build type (one of " + ", ".join(get_build_types()) + ")")


class ReadSubmissionsSettings(BaseModel):
    verbose: bool = Field(False, description="Show full stacktraces instead of truncated versions")
    filter_stop: bool = Field(False, description="Filter out submissions that are stopped")


class AddHarnessWeightSettings(BaseModel):
    msg_path: CliPositionalArg[Path] = Field(description="Path to WeightedHarness file in Protobuf text format")


class AddBuildSettings(BaseModel):
    msg_path: CliPositionalArg[Path] = Field(description="Path to BuildOutput file in Protobuf text format")


class DeleteSettings(BaseModel):
    queue_name: CliPositionalArg[str] = Field(description="Queue name (one of " + ", ".join(get_queue_names()) + ")")
    item_id: Annotated[str | None, Field(description="Item ID")] = None


class Settings(BaseSettings):
    redis_url: Annotated[str, Field(default="redis://localhost:6379", description="Redis URL")]
    log_level: Annotated[str, Field(default="info", description="Log level")]
    send_queue: CliSubCommand[SendSettings]
    read_queue: CliSubCommand[ReadSettings]
    list_queues: CliSubCommand[ListSettings]
    delete_queue: CliSubCommand[DeleteSettings]
    add_harness: CliSubCommand[AddHarnessWeightSettings]
    add_build: CliSubCommand[AddBuildSettings]
    read_harnesses: CliSubCommand[ReadHarnessWeightSettings]
    read_builds: CliSubCommand[ReadBuildsSettings]
    read_submissions: CliSubCommand[ReadSubmissionsSettings]

    class Config:
        env_prefix = "BUTTERCUP_MSG_PUBLISHER_"
        env_file = ".env"
        cli_parse_args = True
        nested_model_default_partial_update = True
        env_nested_delimiter = "__"
        extra = "allow"


def handle_subcommand(redis: Redis, command: BaseModel | None) -> None:
    if command is None:
        return

    if isinstance(command, SendSettings):
        try:
            queue_name = QueueNames(command.queue_name)
            queue: ReliableQueue = QueueFactory(redis).create(queue_name)
        except Exception as e:
            logger.exception(f"Failed to create queue: {e}")
            return

        msg_builder = queue.msg_builder
        logger.info(f"Reading {msg_builder().__class__.__name__} message from file '{command.msg_path}'")
        msg = Parse(command.msg_path.read_text(), msg_builder())
        logger.info(f"Pushing message to queue '{command.queue_name}': {msg}")
        queue.push(msg)
    elif isinstance(command, ReadSettings):
        queue_name = QueueNames(command.queue_name)
        tmp_queue: ReliableQueue = QueueFactory(redis).create(queue_name)
        queue = ReliableQueue(
            redis,
            command.queue_name,
            tmp_queue.msg_builder,
            group_name="msg_publisher" + str(uuid4()) if command.group_name is None else command.group_name,
        )

        while True:
            item = queue.pop()
            if item is None:
                break

            print(item)
            print()

        logger.info("Done")
    elif isinstance(command, DeleteSettings):
        if command.item_id is None:
            redis.delete(command.queue_name)
            logger.info(f"Deleted all items from queue '{command.queue_name}'")
        else:
            redis.xdel(command.queue_name, command.item_id)
            logger.info(f"Deleted item {command.item_id} from queue '{command.queue_name}'")
    elif isinstance(command, AddHarnessWeightSettings):
        msg = Parse(command.msg_path.read_text(), WeightedHarness())
        HarnessWeights(redis).push_harness(msg)
        logger.info(f"Added harness weight for {msg.package_name} | {msg.harness_name} | {msg.task_id}")
    elif isinstance(command, AddBuildSettings):
        msg = Parse(command.msg_path.read_text(), BuildOutput())
        BuildMap(redis).add_build(msg)
        logger.info(f"Added build for {msg.task_id} | {BuildType.Name(msg.build_type)} | {msg.sanitizer}")
    elif isinstance(command, ReadHarnessWeightSettings):
        for harness in HarnessWeights(redis).list_harnesses():
            print(harness)
        logger.info("Done")
    elif isinstance(command, ReadBuildsSettings):
        # NOTE(boyan): we get the build type from the enum name and not value. This allows
        # the CLI interface to use "FUZZER", "COVERAGE", etc, in the command line instead of
        # the real int values that are meaningless.
        build_type = BuildType.Value(command.build_type)
        for build in BuildMap(redis).get_builds(command.task_id, build_type):
            print(build)
        logger.info("Done")
    elif isinstance(command, ReadSubmissionsSettings):
        # Read submissions from Redis using the same key as the Submissions class
        SUBMISSIONS_KEY = "submissions"
        raw_submissions: list = redis.lrange(SUBMISSIONS_KEY, 0, -1)
        registry = TaskRegistry(redis)

        if not raw_submissions:
            logger.info("No submissions found")
            return

        logger.info(f"Found {len(raw_submissions)} submissions:")
        result: dict[TaskId, TaskResult] = {}
        for i, raw in enumerate(raw_submissions):
            try:
                submission = SubmissionEntry.FromString(raw)
                # Apply stacktrace truncation unless verbose mode is enabled
                if not command.verbose:
                    submission = truncate_stacktraces(submission)

                if command.filter_stop:
                    if submission.stop:
                        logger.info(f"Skipping stopped submission {i}")
                        continue

                task_id = submission.crashes[0].crash.crash.target.task_id
                task = registry.get(task_id)
                if task is None:
                    logger.error(f"Task {task_id} not found in registry")
                    continue

                if task_id not in result:
                    result[task_id] = TaskResult(
                        task_id=task_id,
                        project_name=task.project_name,
                        mode=str(task.task_type),
                    )
                c = next((c for c in submission.crashes if c.result == SubmissionResult.PASSED), None)
                if c:
                    result[task_id].n_vulnerabilities += 1

                p = next((p for p in submission.patches if p.result == SubmissionResult.PASSED), None)
                if p:
                    result[task_id].n_patches += 1
                    assert c is not None
                    result[task_id].patched_vulnerabilities.append(c.competition_pov_id)
                elif c:
                    result[task_id].non_patched_vulnerabilities.append(c.competition_pov_id)

                b = next((b for b in submission.bundles), None)
                if b:
                    result[task_id].n_bundles += 1

                print(f"--- Submission {i} ---")
                print(submission)
                print()
            except Exception as e:
                logger.error(f"Failed to parse submission {i}: {e}")

        print()
        print()
        print()
        print("Summary:")

        total_vulnerabilities = sum(task_result.n_vulnerabilities for task_result in result.values())
        total_patches = sum(task_result.n_patches for task_result in result.values())
        total_task_vuln = sum(1 for tr in result.values() if tr.n_vulnerabilities > 0)
        print(f"Total vulnerabilities across all tasks: {total_vulnerabilities}")
        print(f"Total patches across all tasks: {total_patches}")
        print(f"N of at least 1 vuln in a challenge: {total_task_vuln}")
        print()

        for task_id, task_result in result.items():
            print(f"Task {task_id}:")
            print(f"  Project: {task_result.project_name}")
            print(f"  Mode: {task_result.mode}")
            print(f"  N vulnerabilities: {task_result.n_vulnerabilities}")
            print(f"  N patches: {task_result.n_patches}")
            print(f"  N bundles: {task_result.n_bundles}")
            print(f"  Patched vulnerabilities: {task_result.patched_vulnerabilities}")
            print(f"  Non-patched vulnerabilities: {task_result.non_patched_vulnerabilities}")
            print()

        print()
        print()
        print()
        print("Non-patched vulnerabilities across all tasks:")
        all_non_patched: list[tuple[str, str, str]] = []
        for task_id, task_result in result.items():
            all_non_patched.extend(
                (task_result.project_name, task_result.task_id, vuln_id)
                for vuln_id in task_result.non_patched_vulnerabilities
            )

        if all_non_patched:
            for project_name, task_id, vuln_id in all_non_patched:
                print(f"  {project_name} | {task_id} | {vuln_id}")
        else:
            print("  None")

        print()
        logger.info("Done")
    elif isinstance(command, ListSettings):
        print("Available queues:")
        print("\n".join([f"- {name}" for name in get_queue_names()]))


def main() -> None:
    settings = Settings()
    setup_package_logger("util-cli", __name__, settings.log_level)

    redis = Redis.from_url(settings.redis_url, decode_responses=False)
    command = get_subcommand(settings)
    handle_subcommand(redis, command)


if __name__ == "__main__":
    main()
