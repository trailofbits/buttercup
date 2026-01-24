import json
import logging
import subprocess
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
    task_id: str = Field(default="", description="Task ID")
    verbose: bool = Field(False, description="Show full stacktraces instead of truncated versions")
    filter_stop: bool = Field(False, description="Filter out submissions that are stopped")


class AddHarnessWeightSettings(BaseModel):
    msg_path: CliPositionalArg[Path] = Field(description="Path to WeightedHarness file in Protobuf text format")


class AddBuildSettings(BaseModel):
    msg_path: CliPositionalArg[Path] = Field(description="Path to BuildOutput file in Protobuf text format")


class DeleteSettings(BaseModel):
    queue_name: CliPositionalArg[str] = Field(description="Queue name (one of " + ", ".join(get_queue_names()) + ")")
    item_id: Annotated[str | None, Field(description="Item ID")] = None


class ExtractPovsSettings(BaseModel):
    output_dir: CliPositionalArg[Path] = Field(
        description="Output directory for extracted PoVs, stack traces, and patches"
    )
    task_id: str = Field(default="", description="Filter by task ID (optional)")
    passed_only: bool = Field(default=False, description="Only extract vulnerabilities with PASSED PoV result")
    namespace: str = Field(default="crs", description="Kubernetes namespace")
    pod_label: str = Field(default="app=scheduler", description="Label selector for pod to copy files from")


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
    extract_povs: CliSubCommand[ExtractPovsSettings]

    class Config:
        env_prefix = "BUTTERCUP_MSG_PUBLISHER_"
        env_file = ".env"
        cli_parse_args = True
        nested_model_default_partial_update = True
        env_nested_delimiter = "__"
        extra = "allow"


def get_pod_name(namespace: str, label: str) -> str | None:
    """Get the name of a pod matching the label selector."""
    try:
        result = subprocess.run(
            ["kubectl", "get", "pods", "-n", namespace, "-l", label, "-o", "jsonpath={.items[0].metadata.name}"],
            capture_output=True,
            text=True,
            check=True,
        )
        pod_name = result.stdout.strip()
        return pod_name if pod_name else None
    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to get pod name: {e.stderr}")
        return None


def kubectl_cp(namespace: str, pod_name: str, remote_path: str, local_path: Path) -> bool:
    """Copy a file from a pod using kubectl cp."""
    try:
        result = subprocess.run(
            ["kubectl", "cp", "-n", namespace, f"{pod_name}:{remote_path}", str(local_path)],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            logger.warning(f"kubectl cp failed for {remote_path}: {result.stderr}")
            return False
        return True
    except Exception as e:
        logger.warning(f"kubectl cp exception for {remote_path}: {e}")
        return False


def extract_povs(redis: Redis, command: ExtractPovsSettings) -> None:
    """Extract PoVs, stack traces, and patches into a directory structure.

    Directory structure:
        output_dir/
            project_name/
                task_id/
                    vuln_NNN/
                        crashes/
                            crash_001/
                                pov.bin
                                stacktrace.txt
                                tracer_stacktrace.txt
                                metadata.json
                        patches/
                            patch_001.patch
                            patch_002.patch
                        metadata.json
    """
    SUBMISSIONS_KEY = "submissions"
    raw_submissions: list = redis.lrange(SUBMISSIONS_KEY, 0, -1)
    registry = TaskRegistry(redis)

    if not raw_submissions:
        logger.info("No submissions found")
        return

    # Get pod name for kubectl cp
    pod_name = get_pod_name(command.namespace, command.pod_label)
    if not pod_name:
        logger.error(f"No pod found matching label '{command.pod_label}' in namespace '{command.namespace}'")
        return

    logger.info(f"Using pod '{pod_name}' for file extraction")

    output_dir = command.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    logger.info(f"Found {len(raw_submissions)} submissions, extracting to {output_dir}")

    vuln_counter: dict[str, int] = {}  # task_id -> vulnerability counter
    stats = {"povs_copied": 0, "povs_failed": 0}

    for i, raw in enumerate(raw_submissions):
        try:
            submission = SubmissionEntry.FromString(raw)

            if submission.stop:
                logger.debug(f"Skipping stopped submission {i}")
                continue

            if not submission.crashes:
                logger.debug(f"Skipping submission {i} with no crashes")
                continue

            # Get task info from the first crash
            first_crash = submission.crashes[0].crash.crash
            task_id = first_crash.target.task_id

            if command.task_id and task_id != command.task_id:
                logger.debug(f"Skipping submission {i} for task {task_id}")
                continue

            # Check if any crash passed (if passed_only filter is set)
            if command.passed_only:
                has_passed = any(c.result == SubmissionResult.PASSED for c in submission.crashes)
                if not has_passed:
                    logger.debug(f"Skipping submission {i} - no PASSED crashes")
                    continue

            # Get task metadata
            task = registry.get(task_id)
            project_name = task.project_name if task else "unknown"

            # Create vulnerability directory
            if task_id not in vuln_counter:
                vuln_counter[task_id] = 0
            vuln_counter[task_id] += 1
            vuln_num = vuln_counter[task_id]

            vuln_dir = output_dir / project_name / task_id / f"vuln_{vuln_num:03d}"
            crashes_dir = vuln_dir / "crashes"
            patches_dir = vuln_dir / "patches"

            crashes_dir.mkdir(parents=True, exist_ok=True)
            patches_dir.mkdir(parents=True, exist_ok=True)

            # Extract crashes
            for crash_idx, crash_with_id in enumerate(submission.crashes, start=1):
                crash = crash_with_id.crash
                crash_dir = crashes_dir / f"crash_{crash_idx:03d}"
                crash_dir.mkdir(parents=True, exist_ok=True)

                # Copy PoV file using kubectl cp
                pov_remote_path = crash.crash.crash_input_path
                pov_local_path = crash_dir / "pov.bin"

                if kubectl_cp(command.namespace, pod_name, pov_remote_path, pov_local_path):
                    stats["povs_copied"] += 1
                else:
                    stats["povs_failed"] += 1
                    # Store the path for reference
                    (crash_dir / "pov_path.txt").write_text(pov_remote_path)

                # Write stacktrace
                if crash.crash.stacktrace:
                    (crash_dir / "stacktrace.txt").write_text(crash.crash.stacktrace)

                # Write tracer stacktrace
                if crash.tracer_stacktrace:
                    (crash_dir / "tracer_stacktrace.txt").write_text(crash.tracer_stacktrace)

                # Write crash metadata
                crash_metadata = {
                    "competition_pov_id": crash_with_id.competition_pov_id,
                    "result": SubmissionResult.Name(crash_with_id.result) if crash_with_id.result else "NONE",
                    "harness_name": crash.crash.harness_name,
                    "crash_token": crash.crash.crash_token,
                    "crash_input_path": crash.crash.crash_input_path,
                    "sanitizer": crash.crash.target.sanitizer,
                    "engine": crash.crash.target.engine,
                }
                (crash_dir / "metadata.json").write_text(json.dumps(crash_metadata, indent=2))

            # Extract patches (skip empty patch trackers - these are placeholders that never received content)
            patch_num = 0
            for patch_entry in submission.patches:
                if not patch_entry.patch:
                    continue  # Skip empty patch trackers
                patch_num += 1
                patch_file = patches_dir / f"patch_{patch_num:03d}.patch"
                patch_file.write_text(patch_entry.patch)

                # Write patch metadata
                patch_metadata = {
                    "internal_patch_id": patch_entry.internal_patch_id,
                    "competition_patch_id": patch_entry.competition_patch_id,
                    "result": SubmissionResult.Name(patch_entry.result) if patch_entry.result else "NONE",
                }
                (patches_dir / f"patch_{patch_num:03d}_metadata.json").write_text(json.dumps(patch_metadata, indent=2))

            # Write vulnerability metadata
            vuln_metadata = {
                "task_id": task_id,
                "project_name": project_name,
                "num_crashes": len(submission.crashes),
                "num_patches": patch_num,  # Only count non-empty patches
                "num_bundles": len(submission.bundles),
                "patch_idx": submission.patch_idx,
                "stopped": submission.stop,
            }
            (vuln_dir / "metadata.json").write_text(json.dumps(vuln_metadata, indent=2))

            logger.info(
                f"Extracted vulnerability {vuln_num} for {project_name}/{task_id}: "
                f"{len(submission.crashes)} crashes, {patch_num} patches"
            )

        except Exception as e:
            logger.error(f"Failed to process submission {i}: {e}")
            continue

    # Print summary
    total_vulns = sum(vuln_counter.values())
    logger.info(f"Extraction complete: {total_vulns} vulnerabilities across {len(vuln_counter)} tasks")
    logger.info(f"PoV files: {stats['povs_copied']} copied, {stats['povs_failed']} failed")
    for task_id, count in vuln_counter.items():
        logger.info(f"  {task_id}: {count} vulnerabilities")


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

                if command.task_id and task_id != command.task_id:
                    logger.info(f"Skipping submission {i} for task {task_id} (not {command.task_id})")
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
    elif isinstance(command, ExtractPovsSettings):
        extract_povs(redis, command)
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
