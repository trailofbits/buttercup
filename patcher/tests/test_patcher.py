from pathlib import Path
from buttercup.patcher.patcher import Patcher
from buttercup.common.datastructures.msg_pb2 import ConfirmedVulnerability, Crash, BuildOutput, TracedCrash
from buttercup.patcher.agents.common import CodeSnippetRequest
import pytest
import re


@pytest.fixture
def tasks_dir(tmp_path: Path) -> Path:
    """Create a mock challenge task directory structure."""
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

    yield tmp_path


def test_vuln_to_patch_input(tasks_dir: Path, tmp_path: Path):
    patcher = Patcher(
        task_storage_dir=tasks_dir,
        scratch_dir=tmp_path,
        redis=None,
    )

    vuln = ConfirmedVulnerability(
        vuln_id="test-vuln-1",
        crash=TracedCrash(
            crash=Crash(
                target=BuildOutput(
                    task_id="test-task-id-1",
                    engine="test-engine-1",
                    sanitizer="test-sanitizer-1",
                    task_dir=str(tasks_dir / "test-task-id-1"),
                ),
                harness_name="test-harness-name-1",
                crash_input_path="test-crash-input-path-1",
                stacktrace="test-stacktrace-1",
            ),
            tracer_stacktrace="test-tracer-stacktrace-1",
        ),
    )

    # Test patch generation
    patch_input = patcher._create_patch_input(vuln)

    # Verify the patch was generated
    assert patch_input is not None
    assert patch_input.task_id == "test-task-id-1"
    assert patch_input.vulnerability_id == "test-vuln-1"
    assert patch_input.harness_name == "test-harness-name-1"
    assert patch_input.pov == Path("test-crash-input-path-1")
    assert patch_input.sanitizer_output == "test-tracer-stacktrace-1"
    assert patch_input.engine == "test-engine-1"
    assert patch_input.sanitizer == "test-sanitizer-1"


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
