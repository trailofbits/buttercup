from pathlib import Path
from buttercup.patcher.patcher import Patcher
from buttercup.common.datastructures.msg_pb2 import ConfirmedVulnerability, Crash, BuildOutput, TracedCrash, Task
from buttercup.common.challenge_task import ChallengeTask, TaskMeta
from buttercup.patcher.agents.common import CodeSnippetRequest
from buttercup.common.queues import RQItem
from buttercup.common.task_registry import TaskRegistry
from buttercup.patcher.agents.common import PatcherAgentState, PatchInput, PatchAttempt, PatchStatus, add_or_mod_patch
from buttercup.patcher.utils import PatchInputPoV
import pytest
from unittest.mock import patch, MagicMock
import re
import time
from redis import Redis


@pytest.fixture
def redis_client():
    res = Redis(host="localhost", port=6379, db=13)
    yield res
    res.flushdb()


@pytest.fixture
def task_dir(tmp_path: Path) -> Path:
    """Create a mock challenge task directory structure."""
    # Ensure tmp_path is absolute
    tmp_path = tmp_path.absolute()

    # Create the task directory
    task_dir = tmp_path / "test-task-id-1"
    task_dir.mkdir(parents=True, exist_ok=True)

    # Create the main directories
    oss_fuzz = task_dir / "fuzz-tooling" / "my-oss-fuzz"
    source = task_dir / "src" / "my-source"
    diffs = task_dir / "diff" / "my-diff"

    oss_fuzz.mkdir(parents=True, exist_ok=True)
    source.mkdir(parents=True, exist_ok=True)
    diffs.mkdir(parents=True, exist_ok=True)

    # Create some mock patch files
    (diffs / "patch1.diff").write_text("mock patch 1")
    (diffs / "patch2.diff").write_text("mock patch 2")

    # Create a mock helper.py file
    helper_path = oss_fuzz / "infra/helper.py"
    helper_path.parent.mkdir(parents=True, exist_ok=True)
    helper_path.write_text("import sys;\nsys.exit(0)\n")

    # Create a mock test.txt file
    (source / "test.txt").write_text("mock test content")

    TaskMeta(
        project_name="test-project-name",
        focus="test-focus",
        task_id="test-task-id-1",
        metadata={"task_id": "test-task-id-1", "round_id": "testing", "team_id": "tob"},
    ).save(task_dir)

    yield task_dir


@patch("buttercup.common.node_local.make_locally_available")
def test_vuln_to_patch_input(mock_make_locally_available, task_dir: Path, tmp_path: Path):
    # Mock make_locally_available to return the path unchanged
    mock_make_locally_available.side_effect = lambda path: Path(path)

    # Ensure all paths are absolute
    task_dir = task_dir.absolute()
    tmp_path = tmp_path.absolute()

    patcher = Patcher(
        task_storage_dir=tmp_path,
        scratch_dir=tmp_path,
        redis=None,
    )

    vuln = ConfirmedVulnerability(
        internal_patch_id="1",
        crashes=[
            TracedCrash(
                crash=Crash(
                    target=BuildOutput(
                        task_id="test-task-id-1",
                        engine="test-engine-1",
                        sanitizer="test-sanitizer-1",
                        task_dir=str(task_dir),
                    ),
                    harness_name="test-harness-name-1",
                    crash_input_path=str(tmp_path / "test-crash-input.txt"),
                    stacktrace="test-stacktrace-1",
                ),
                tracer_stacktrace="test-tracer-stacktrace-1",
            )
        ],
    )

    # Test patch generation
    patch_input = patcher._create_patch_input(vuln)

    # Verify the patch was generated
    assert patch_input is not None
    assert patch_input.task_id == "test-task-id-1"
    assert patch_input.internal_patch_id == "1"

    # Check the povs list structure
    assert len(patch_input.povs) == 1
    pov = patch_input.povs[0]
    assert pov.harness_name == "test-harness-name-1"
    assert pov.pov == tmp_path / "test-crash-input.txt"
    assert pov.sanitizer_output == "test-tracer-stacktrace-1"
    assert pov.engine == "test-engine-1"
    assert pov.sanitizer == "test-sanitizer-1"


@patch("buttercup.common.node_local.make_locally_available")
def test_vuln_to_patch_input_multiple_povs(mock_make_locally_available, task_dir: Path, tmp_path: Path):
    # Mock make_locally_available to return the path unchanged
    mock_make_locally_available.side_effect = lambda path: Path(path)

    # Ensure all paths are absolute
    task_dir = task_dir.absolute()
    tmp_path = tmp_path.absolute()

    patcher = Patcher(
        task_storage_dir=tmp_path,
        scratch_dir=tmp_path,
        redis=None,
    )

    vuln = ConfirmedVulnerability(
        internal_patch_id="1",
        crashes=[
            TracedCrash(
                crash=Crash(
                    target=BuildOutput(
                        task_id="test-task-id-1",
                        engine="test-engine-1",
                        sanitizer="test-sanitizer-1",
                        task_dir=str(task_dir),
                    ),
                    harness_name="test-harness-name-1",
                    crash_input_path=str(tmp_path / "test-crash-input-1.txt"),
                    stacktrace="test-stacktrace-1",
                ),
                tracer_stacktrace="test-tracer-stacktrace-1",
            ),
            TracedCrash(
                crash=Crash(
                    target=BuildOutput(
                        task_id="test-task-id-1",
                        engine="test-engine-2",
                        sanitizer="test-sanitizer-2",
                        task_dir=str(task_dir),
                    ),
                    harness_name="test-harness-name-2",
                    crash_input_path=str(tmp_path / "test-crash-input-2.txt"),
                    stacktrace="test-stacktrace-2",
                ),
                tracer_stacktrace="test-tracer-stacktrace-2",
            ),
        ],
    )

    # Test patch generation
    patch_input = patcher._create_patch_input(vuln)

    # Verify the patch was generated
    assert patch_input is not None
    assert patch_input.task_id == "test-task-id-1"
    assert patch_input.internal_patch_id == "1"

    # Check the povs list structure
    assert len(patch_input.povs) == 2

    # Verify first POV
    pov1 = patch_input.povs[0]
    assert pov1.harness_name == "test-harness-name-1"
    assert pov1.pov == tmp_path / "test-crash-input-1.txt"
    assert pov1.sanitizer_output == "test-tracer-stacktrace-1"
    assert pov1.engine == "test-engine-1"
    assert pov1.sanitizer == "test-sanitizer-1"

    # Verify second POV
    pov2 = patch_input.povs[1]
    assert pov2.harness_name == "test-harness-name-2"
    assert pov2.pov == tmp_path / "test-crash-input-2.txt"
    assert pov2.sanitizer_output == "test-tracer-stacktrace-2"
    assert pov2.engine == "test-engine-2"
    assert pov2.sanitizer == "test-sanitizer-2"


def test_code_snippet_request_parse_single_request():
    """Test parsing a single code snippet request."""
    msg = """
    <code_request>
    Please provide the implementation of the function 'validate_input' from file 'input_validation.c'.
    </code_request>
    """

    result = CodeSnippetRequest.parse(msg)

    assert len(result) == 1
    assert (
        result[0].request
        == "Please provide the implementation of the function 'validate_input' from file 'input_validation.c'."
    )


def test_code_snippet_request_parse_multiple_requests():
    """Test parsing multiple code snippet requests."""
    msg = """
    <code_request>
    Please provide the implementation of the function 'validate_input' from file 'input_validation.c'.
    </code_request>
    <code_request>
    Please provide the implementation of the function 'process_data' from file 'data_processor.c'.
    </code_request>
    <code_request>
    Please provide the implementation of the function 'format_output' from file 'output_formatter.c'.
    </code_request>
    """

    result = CodeSnippetRequest.parse(msg)

    assert len(result) == 3
    assert (
        result[0].request
        == "Please provide the implementation of the function 'validate_input' from file 'input_validation.c'."
    )
    assert (
        result[1].request
        == "Please provide the implementation of the function 'process_data' from file 'data_processor.c'."
    )
    assert (
        result[2].request
        == "Please provide the implementation of the function 'format_output' from file 'output_formatter.c'."
    )


def test_code_snippet_request_parse_empty_message():
    """Test parsing an empty message."""
    msg = ""

    result = CodeSnippetRequest.parse(msg)

    assert len(result) == 0


def test_code_snippet_request_parse_no_requests():
    """Test parsing a message with no code snippet requests."""
    msg = "This is a message without any code snippet requests."

    result = CodeSnippetRequest.parse(msg)

    assert len(result) == 0


def test_code_snippet_request_parse_with_whitespace():
    """Test parsing code snippet requests with various whitespace patterns."""
    msg = """
    <code_request>
    Request with leading and trailing whitespace
    </code_request>
    <code_request>Request on a single line</code_request>
    <code_request>
    Request with
    multiple
    lines
    </code_request>
    """

    result = CodeSnippetRequest.parse(msg)

    assert len(result) == 3
    assert result[0].request == "Request with leading and trailing whitespace"
    assert result[1].request == "Request on a single line"
    assert re.match(r"Request with\s*\n\s*multiple\s*\n\s*lines", result[2].request)


def test_code_snippet_request_parse_with_code_requests_wrapper():
    """Test parsing code snippet requests wrapped inside a <code_requests> tag."""
    msg = """
    <code_requests>
    <code_request>
    Please provide the implementation of the function 'validate_input' from file 'input_validation.c'.
    </code_request>
    <code_request>
    Please provide the implementation of the function 'process_data' from file 'data_processor.c'.
    </code_request>
    <code_request>
    Please provide the implementation of the function 'format_output' from file 'output_formatter.c'.
    </code_request>
    </code_requests>
    """

    result = CodeSnippetRequest.parse(msg)

    assert len(result) == 3
    assert (
        result[0].request
        == "Please provide the implementation of the function 'validate_input' from file 'input_validation.c'."
    )
    assert (
        result[1].request
        == "Please provide the implementation of the function 'process_data' from file 'data_processor.c'."
    )
    assert (
        result[2].request
        == "Please provide the implementation of the function 'format_output' from file 'output_formatter.c'."
    )


@patch("buttercup.common.node_local.make_locally_available")
def test_process_item_should_process_normal_task(
    mock_make_locally_available, redis_client, task_dir: Path, tmp_path: Path
):
    """Test that a normal task is processed correctly"""
    # Mock make_locally_available to return the path unchanged
    mock_make_locally_available.side_effect = lambda path: Path(path)

    # Ensure all paths are absolute
    task_dir = task_dir.absolute()
    tmp_path = tmp_path.absolute()

    # Setup patcher with redis
    patcher = Patcher(
        task_storage_dir=tmp_path,
        scratch_dir=tmp_path,
        redis=redis_client,
    )

    # Setup task registry with a non-expired, non-cancelled task
    registry = TaskRegistry(redis_client)
    task_id = "test-task-id-1"

    # Create a task with a future deadline
    mock_task = Task(task_id=task_id, deadline=int(time.time()) + 3600)  # Set deadline 1 hour in future
    registry.set(mock_task)

    # Create a vulnerability for processing
    vuln = ConfirmedVulnerability(
        internal_patch_id="1",
        crashes=[
            TracedCrash(
                crash=Crash(
                    target=BuildOutput(
                        task_id=task_id,
                        engine="test-engine-1",
                        sanitizer="test-sanitizer-1",
                        task_dir=str(task_dir),
                    ),
                    harness_name="test-harness-name-1",
                    crash_input_path=str(tmp_path / "test-crash-input.txt"),
                    stacktrace="test-stacktrace-1",
                ),
                tracer_stacktrace="test-tracer-stacktrace-1",
            )
        ],
    )

    # Create an RQItem with the vulnerability
    rq_item = RQItem(item_id="item-id-1", deserialized=vuln)

    # Patch the process_patch_input method to avoid actual processing
    with (
        patch.object(patcher, "process_patch_input") as mock_process,
        patch.object(patcher.patches_queue, "push") as mock_push,
        patch.object(patcher.vulnerability_queue, "ack_item") as mock_ack,
    ):
        # Configure mock to return a patch
        mock_process.return_value = MagicMock(task_id=task_id, internal_patch_id="1", patch="test-patch")

        # Process the item
        patcher.process_item(rq_item)

        # Verify processing occurred
        mock_process.assert_called_once()
        mock_push.assert_called_once()
        mock_ack.assert_called_once_with("item-id-1")


@patch("buttercup.common.node_local.make_locally_available")
def test_process_item_should_skip_tasks_marked_for_stopping(
    mock_make_locally_available, redis_client, task_dir: Path, tmp_path: Path
):
    """Test that tasks marked for stopping (expired or cancelled) are not processed"""
    # Mock make_locally_available to return the path unchanged
    mock_make_locally_available.side_effect = lambda path: Path(path)

    # Ensure all paths are absolute
    task_dir = task_dir.absolute()
    tmp_path = tmp_path.absolute()

    # Setup patcher with redis
    patcher = Patcher(
        task_storage_dir=tmp_path,
        scratch_dir=tmp_path,
        redis=redis_client,
    )

    # Create a vulnerability for processing
    task_id = "skip-task-id"
    vuln = ConfirmedVulnerability(
        internal_patch_id="1",
        crashes=[
            TracedCrash(
                crash=Crash(
                    target=BuildOutput(
                        task_id=task_id,
                        engine="test-engine-1",
                        sanitizer="test-sanitizer-1",
                        task_dir=str(task_dir),
                    ),
                    harness_name="test-harness-name-1",
                    crash_input_path=str(tmp_path / "test-crash-input.txt"),
                    stacktrace="test-stacktrace-1",
                ),
                tracer_stacktrace="test-tracer-stacktrace-1",
            )
        ],
    )

    # Create an RQItem with the vulnerability
    rq_item = RQItem(item_id="item-id-to-skip", deserialized=vuln)

    # Patch the registry's should_stop_processing method to return True
    with (
        patch.object(patcher.registry, "should_stop_processing", return_value=True),
        patch.object(patcher, "process_patch_input") as mock_process,
        patch.object(patcher.vulnerability_queue, "ack_item") as mock_ack,
    ):
        # Process the item
        patcher.process_item(rq_item)

        # Verify the task was acknowledged without processing
        mock_process.assert_not_called()  # Process method should not be called
        mock_ack.assert_called_once_with("item-id-to-skip")
        # Verify registry was called with the correct task ID
        patcher.registry.should_stop_processing.assert_called_once_with(task_id)


def test_get_successful_patch():
    """Test getting successful patches from PatcherAgentState."""
    state = PatcherAgentState(
        messages=[],
        context=PatchInput(
            challenge_task_dir=Path("/tmp"),
            task_id="test",
            internal_patch_id="1",
            povs=[
                PatchInputPoV(
                    challenge_task_dir=Path("/tmp"),
                    sanitizer="address",
                    pov=Path("/tmp/pov"),
                    pov_token="token",
                    sanitizer_output="output",
                    engine="libfuzzer",
                    harness_name="test",
                )
            ],
        ),
    )

    # Add a mix of successful and failed patches
    patches = [
        PatchAttempt(build_succeeded=True, pov_fixed=True, tests_passed=True, status=PatchStatus.SUCCESS),
        PatchAttempt(build_succeeded=False, pov_fixed=False, tests_passed=False, status=PatchStatus.BUILD_FAILED),
        PatchAttempt(build_succeeded=True, pov_fixed=True, tests_passed=True, status=PatchStatus.SUCCESS),
    ]
    state.patch_attempts = patches

    # Should get the last successful patch
    successful = state.get_successful_patch()
    assert successful == patches[2].patch


def test_get_successful_patch_with_validation_failure():
    """Test getting successful patches when validation fails."""
    state = PatcherAgentState(
        messages=[],
        context=PatchInput(
            challenge_task_dir=Path("/tmp"),
            task_id="test",
            internal_patch_id="1",
            povs=[
                PatchInputPoV(
                    challenge_task_dir=Path("/tmp"),
                    sanitizer="address",
                    pov=Path("/tmp/pov"),
                    pov_token="token",
                    sanitizer_output="output",
                    engine="libfuzzer",
                    harness_name="test",
                )
            ],
        ),
    )

    # Create patches with a good one in the middle that failed validation
    patches = [
        PatchAttempt(build_succeeded=False, pov_fixed=False, tests_passed=False, status=PatchStatus.BUILD_FAILED),
        PatchAttempt(build_succeeded=True, pov_fixed=True, tests_passed=True, status=PatchStatus.VALIDATION_FAILED),
        PatchAttempt(build_succeeded=False, pov_fixed=False, tests_passed=False, status=PatchStatus.POV_FAILED),
    ]
    state.patch_attempts = patches

    # Should still get the patch that passed build/pov/tests even though validation failed
    successful = state.get_successful_patch()
    assert successful == patches[1].patch


def test_clean_built_challenges_on_new_patch(tmp_path: Path, task_dir: Path):
    """Test that built challenges are cleaned when a new patch attempt is made."""
    state = PatcherAgentState(
        messages=[],
        context=PatchInput(
            challenge_task_dir=Path("/tmp"),
            task_id="test",
            internal_patch_id="1",
            povs=[
                PatchInputPoV(
                    challenge_task_dir=Path("/tmp"),
                    sanitizer="address",
                    pov=Path("/tmp/pov"),
                    pov_token="token",
                    sanitizer_output="output",
                    engine="libfuzzer",
                    harness_name="test",
                )
            ],
        ),
    )

    challenge_task = ChallengeTask(task_dir, local_task_dir=task_dir)

    # Create first patch attempt with a built challenge
    patch1 = PatchAttempt(
        build_succeeded=True,
        pov_fixed=True,
        tests_passed=True,
        status=PatchStatus.SUCCESS,
        built_challenges={"address": challenge_task.local_task_dir},
    )

    # Add first patch attempt
    state.patch_attempts = [patch1]

    # Create second patch attempt
    patch2 = PatchAttempt(
        build_succeeded=True,
        pov_fixed=True,
        tests_passed=True,
        status=PatchStatus.SUCCESS,
        built_challenges={"address": Path(tmp_path / "new-task")},
    )

    # Add second patch attempt through the add_patch_attempt method
    state.patch_attempts = add_or_mod_patch(state.patch_attempts, patch2)

    # Verify that the first patch's built challenges were cleaned
    assert patch1.built_challenges == {}

    # Verify that the second patch's built challenges are still present
    assert patch2.built_challenges == {"address": Path(tmp_path / "new-task")}

    # Verify that the first directory and its contents were actually deleted
    assert not challenge_task.local_task_dir.exists()
