from buttercup.common.logger import setup_package_logger
from buttercup.common.maps import (
    BuildMap,
    HarnessWeights,
)
from buttercup.common.datastructures.msg_pb2 import BuildOutput, BuildType, WeightedHarness, SubmissionEntry
from buttercup.common.queues import QueueFactory, QueueNames, ReliableQueue
from uuid import uuid4
from redis import Redis
from pydantic_settings import BaseSettings, CliSubCommand, CliPositionalArg, get_subcommand
from pydantic import BaseModel
from typing import Annotated
from pydantic import Field
from pathlib import Path
from google.protobuf.text_format import Parse
import logging

logger = logging.getLogger(__name__)


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


def get_queue_names():
    return [f"'{queue_name.value}'" for queue_name in QueueNames]


def get_build_types():
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


def main():
    settings = Settings()
    setup_package_logger("util-cli", __name__, settings.log_level)

    redis = Redis.from_url(settings.redis_url, decode_responses=False)
    command = get_subcommand(settings)
    if isinstance(command, SendSettings):
        try:
            queue = QueueFactory(redis).create(command.queue_name)
        except Exception as e:
            logger.exception(f"Failed to create queue: {e}")
            return

        msg_builder = queue.msg_builder
        logger.info(f"Reading {msg_builder().__class__.__name__} message from file '{command.msg_path}'")
        msg = Parse(command.msg_path.read_text(), msg_builder())
        logger.info(f"Pushing message to queue '{command.queue_name}': {msg}")
        queue.push(msg)
    elif isinstance(command, ReadSettings):
        tmp_queue = QueueFactory(redis).create(command.queue_name)
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
        raw_submissions = redis.lrange(SUBMISSIONS_KEY, 0, -1)

        if not raw_submissions:
            logger.info("No submissions found")
            return

        logger.info(f"Found {len(raw_submissions)} submissions:")
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

                print(f"--- Submission {i} ---")
                print(submission)
                print()
            except Exception as e:
                logger.error(f"Failed to parse submission {i}: {e}")

        logger.info("Done")
    elif isinstance(command, ListSettings):
        print("Available queues:")
        print("\n".join([f"- {name}" for name in get_queue_names()]))


if __name__ == "__main__":
    main()
