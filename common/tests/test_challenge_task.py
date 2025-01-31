from pathlib import Path
import pytest
from unittest.mock import Mock, patch
import subprocess
from buttercup.common.challenge_task import ChallengeTask
import logging


@pytest.fixture
def task_dir(tmp_path: Path) -> Path:
    """Create a mock challenge task directory structure."""
    # Create the main directories
    oss_fuzz = tmp_path / "oss-fuzz"
    source = tmp_path / "source"
    diffs = tmp_path / "diffs"

    oss_fuzz.mkdir()
    source.mkdir()
    diffs.mkdir()

    # Create some mock patch files
    (diffs / "patch1.diff").write_text("mock patch 1")
    (diffs / "patch2.diff").write_text("mock patch 2")

    # Create a mock helper.py file
    helper_path = oss_fuzz / "infra/helper.py"
    helper_path.parent.mkdir(parents=True, exist_ok=True)
    helper_path.write_text("import sys;\nsys.exit(0)\n")

    return tmp_path

@pytest.fixture
def challenge_task_readonly(task_dir: Path) -> ChallengeTask:
    """Create a mock challenge task for testing."""
    return ChallengeTask(
        read_only_task_dir=task_dir,
        project_name="example_project",
        oss_fuzz_subpath="oss-fuzz",
        source_subpath="source",
        diffs_subpath="diffs",
    )


@pytest.fixture
def challenge_task(task_dir: Path) -> ChallengeTask:
    """Create a mock challenge task for testing."""
    return ChallengeTask(
        read_only_task_dir=task_dir,
        local_task_dir=task_dir,
        project_name="example_project",
        oss_fuzz_subpath="oss-fuzz",
        source_subpath="source",
        diffs_subpath="diffs",
    )


@pytest.fixture
def challenge_task_custom_python(task_dir: Path) -> ChallengeTask:
    """Create a mock challenge task with custom python path for testing."""
    return ChallengeTask(
        read_only_task_dir=task_dir,
        local_task_dir=task_dir,
        project_name="example_project",
        oss_fuzz_subpath="oss-fuzz",
        source_subpath="source",
        python_path="/usr/local/bin/python3",
    )


def get_mock_popen(returncode: int, stdout: list[bytes], stderr: list[bytes]):
    with patch("subprocess.Popen") as mock_popen:
        mock_process = Mock()
        mock_process.returncode = returncode

        # Create mock pipe for stdout that handles multiple readline() calls gracefully
        class MockStd:
            def __init__(self, lines: list[bytes]):
                self.lines = lines
                self.current_line = 0

            def readline(self):
                if self.current_line < len(self.lines):
                    line = self.lines[self.current_line]
                    self.current_line += 1
                    return line
                return b""  # Return empty bytes when no more lines

        mock_process.stdout = MockStd(stdout)

        # Create mock pipe for stderr
        mock_process.stderr = MockStd(stderr)

        # Setup poll and wait behavior
        mock_process.poll.side_effect = [None, None, returncode]
        mock_process.wait.return_value = returncode

        # Make Popen return our mock process
        mock_popen.return_value = mock_process
        yield mock_popen


@pytest.fixture
def mock_subprocess():
    """Mock subprocess calls for testing."""
    yield from get_mock_popen(0, [b"output line 1\n", b"output line 2\n"], [b"error line 1\n", b"error line 2\n"])


@pytest.fixture
def mock_failed_subprocess():
    """Mock subprocess calls for testing."""
    yield from get_mock_popen(1, [], [b"Build failed"])


def test_directory_structure(challenge_task: ChallengeTask):
    """Test that the challenge task correctly identifies its directory structure."""
    assert challenge_task.oss_fuzz_subpath == Path("oss-fuzz")
    assert challenge_task.source_subpath == Path("source")
    assert challenge_task.diffs_subpath == Path("diffs")

    assert (challenge_task.task_dir / challenge_task.oss_fuzz_subpath).is_dir()
    assert (challenge_task.task_dir / challenge_task.source_subpath).is_dir()
    assert (challenge_task.task_dir / challenge_task.diffs_subpath).is_dir()

def test_readonly_task(challenge_task_readonly: ChallengeTask):
    """Test that a readonly task raises an error when trying to build."""
    with pytest.raises(RuntimeError, match="Challenge Task is read-only, cannot perform this operation"):
        challenge_task_readonly.build_image()

    with pytest.raises(RuntimeError, match="Challenge Task is read-only, cannot perform this operation"):
        challenge_task_readonly.build_fuzzers(engine="libfuzzer", sanitizer="address")

    with pytest.raises(RuntimeError, match="Challenge Task is read-only, cannot perform this operation"):
        challenge_task_readonly.reproduce_pov(fuzzer_name="fuzz_target", crash_path=Path("crash-sample"))

def test_build_image(challenge_task: ChallengeTask, mock_subprocess):
    """Test building the docker image for the project."""
    result = challenge_task.build_image()

    assert result.success is True
    assert result.output is not None
    assert result.output == b"output line 1\noutput line 2\n"
    mock_subprocess.assert_called_once()

    # Verify the command and working directory
    args, kwargs = mock_subprocess.call_args
    assert args[0] == ["python", "infra/helper.py", "build_image", "--no-pull", "example_project"]
    assert kwargs["cwd"] == challenge_task.task_dir / challenge_task.oss_fuzz_subpath

    # Verify output was read
    mock_process = mock_subprocess.return_value
    assert mock_process.wait.called  # Verify we waited for process completion


def test_build_fuzzers(challenge_task: ChallengeTask, mock_subprocess):
    """Test building fuzzers with different configurations."""
    result = challenge_task.build_fuzzers(
        engine="libfuzzer",
        sanitizer="address",
    )

    assert result.success is True
    mock_subprocess.assert_called_once()
    args, kwargs = mock_subprocess.call_args
    assert args[0][:-1] == [
        "python",
        "infra/helper.py",
        "build_fuzzers",
        "--engine",
        "libfuzzer",
        "--sanitizer",
        "address",
        "example_project",
    ]
    assert args[0][-1].endswith("/source")
    assert kwargs["cwd"] == challenge_task.task_dir / challenge_task.oss_fuzz_subpath


def test_check_build(challenge_task: ChallengeTask, mock_subprocess):
    """Test checking the build status."""
    result = challenge_task.check_build(engine="libfuzzer", sanitizer="address")

    assert result.success is True
    mock_subprocess.assert_called_once()
    args, kwargs = mock_subprocess.call_args
    assert args[0] == [
        "python",
        "infra/helper.py",
        "check_build",
        "--engine",
        "libfuzzer",
        "--sanitizer",
        "address",
        "example_project",
    ]
    assert kwargs["cwd"] == challenge_task.task_dir / challenge_task.oss_fuzz_subpath


def test_reproduce_pov(challenge_task: ChallengeTask, mock_subprocess):
    """Test reproducing a proof of vulnerability."""
    pov_file = Path("crash-sample")
    result = challenge_task.reproduce_pov(
        fuzzer_name="fuzz_target",
        crash_path=pov_file,
    )

    assert result.success is True
    mock_subprocess.assert_called_once()
    args, kwargs = mock_subprocess.call_args
    assert args[0][:-1] == ["python", "infra/helper.py", "reproduce", "example_project", "fuzz_target"]
    assert args[0][-1].endswith("/crash-sample")
    assert kwargs["cwd"] == challenge_task.task_dir / challenge_task.oss_fuzz_subpath


def test_failed_build_image(challenge_task: ChallengeTask, mock_failed_subprocess):
    """Test handling failed build image operation."""
    result = challenge_task.build_image()

    assert result.success is False
    assert result.error == b"Build failed"


def test_invalid_task_dir():
    """Test handling of invalid task directory."""
    with pytest.raises(ValueError, match="Task directory does not exist"):
        ChallengeTask(
            read_only_task_dir=Path("/nonexistent"),
            project_name="example_project",
            oss_fuzz_subpath="oss-fuzz",
            source_subpath="source",
        )


def test_missing_required_dirs(tmp_path: Path):
    """Test handling of missing required directories."""
    # Create task dir without required subdirectories
    task_dir = tmp_path / "task"
    task_dir.mkdir()

    with pytest.raises(ValueError, match="Missing required directory"):
        ChallengeTask(
            read_only_task_dir=task_dir,
            project_name="example_project",
            oss_fuzz_subpath="oss-fuzz",
            source_subpath="source",
        )


def test_build_image_custom_python(challenge_task_custom_python: ChallengeTask, mock_subprocess):
    """Test building the docker image using custom python path."""
    result = challenge_task_custom_python.build_image()

    assert result.success is True
    mock_subprocess.assert_called_once()
    args, kwargs = mock_subprocess.call_args
    assert args[0] == ["/usr/local/bin/python3", "infra/helper.py", "build_image", "--no-pull", "example_project"]
    assert kwargs["cwd"] == challenge_task_custom_python.task_dir / challenge_task_custom_python.oss_fuzz_subpath


def test_build_fuzzers_custom_python(challenge_task_custom_python: ChallengeTask, mock_subprocess):
    """Test building fuzzers with custom python path."""
    result = challenge_task_custom_python.build_fuzzers(
        engine="libfuzzer",
        sanitizer="address",
    )

    assert result.success is True
    mock_subprocess.assert_called_once()
    args, kwargs = mock_subprocess.call_args
    assert args[0][:-1] == [
        "/usr/local/bin/python3",
        "infra/helper.py",
        "build_fuzzers",
        "--engine",
        "libfuzzer",
        "--sanitizer",
        "address",
        "example_project",
    ]
    assert args[0][-1].endswith("/source")
    assert kwargs["cwd"] == challenge_task_custom_python.task_dir / challenge_task_custom_python.oss_fuzz_subpath


@pytest.fixture
def libpng_oss_fuzz_task(tmp_path: Path) -> ChallengeTask:
    """Create a challenge task using a real OSS-Fuzz repository."""
    # Clone real oss-fuzz repo into temp dir
    oss_fuzz_dir = tmp_path / "oss-fuzz"
    source_dir = tmp_path / "source"
    source_dir.mkdir()

    subprocess.run(
        ["git", "clone", "--depth=1", "https://github.com/google/oss-fuzz.git", str(oss_fuzz_dir)], check=True
    )

    # Download libpng source code
    libpng_url = "https://github.com/pnggroup/libpng/archive/refs/tags/v1.6.34.tar.gz"
    libpng_tar = tmp_path / "libpng.tar.gz"

    subprocess.run(["curl", "-L", "-o", str(libpng_tar), libpng_url], check=True)

    # Extract libpng source into source directory, stripping first directory level
    subprocess.run(["tar", "--strip-components=1", "-xzf", str(libpng_tar), "-C", str(source_dir)], check=True)

    return ChallengeTask(
        read_only_task_dir=tmp_path,
        local_task_dir=tmp_path,
        project_name="libpng",
        oss_fuzz_subpath="oss-fuzz",
        source_subpath="source",
        logger=logging.getLogger(__name__),
    )


@pytest.fixture
def libpng_crash_testcase(tmp_path: Path) -> Path:
    """Download libpng crash testcase from oss-fuzz."""
    # https://issues.oss-fuzz.com/issues/42499503
    crash_url = "https://oss-fuzz.com/download?testcase_id=5112664847024128"
    crash_file = tmp_path / "crash-testcase"

    subprocess.run(["curl", "-L", "-o", str(crash_file), crash_url], check=True)

    return crash_file


@pytest.mark.integration
def test_real_build_workflow(libpng_oss_fuzz_task: ChallengeTask):
    """Test the full build workflow using actual OSS-Fuzz repository."""
    # Build the base image
    result = libpng_oss_fuzz_task.build_image(pull_latest_base_image=False)
    assert result.success is True, f"Build image failed: {result.error}"

    # Build the fuzzers
    result = libpng_oss_fuzz_task.build_fuzzers(
        engine="libfuzzer",
        sanitizer="address",
        architecture="x86_64",
    )
    assert result.success is True, f"Build fuzzers failed: {result.error}"

    # Check the build
    result = libpng_oss_fuzz_task.check_build(
        engine="libfuzzer",
        sanitizer="address",
        architecture="x86_64",
    )
    assert result.success is True, f"Check build failed: {result.error}"


@pytest.mark.integration
def test_real_reproduce_pov(libpng_oss_fuzz_task: ChallengeTask, libpng_crash_testcase: Path):
    """Test the reproduce POV workflow using actual OSS-Fuzz repository."""
    # Reproduce the POV
    libpng_oss_fuzz_task.build_image(pull_latest_base_image=False)
    libpng_oss_fuzz_task.build_fuzzers(engine="libfuzzer", sanitizer="address")
    result = libpng_oss_fuzz_task.reproduce_pov(
        fuzzer_name="libFuzzer_libpng_read_fuzzer",
        crash_path=libpng_crash_testcase,
    )
    assert result.success is False, "Reproduce POV failed"
    assert "MemorySanitizer: use-of-uninitialized-value" in result.output.decode(), (
        "MemorySanitizer error not found in error message"
    )
    assert "png_read_filter_row_paeth_multibyte_pixel" in result.output.decode(), (
        "Fuzz target name not found in error message"
    )


@pytest.mark.integration
def test_real_reproduce_pov_no_source_dir(libpng_oss_fuzz_task: ChallengeTask, libpng_crash_testcase: Path):
    """Test the reproduce POV workflow using actual OSS-Fuzz repository."""
    libpng_oss_fuzz_task.build_image(pull_latest_base_image=False)
    libpng_oss_fuzz_task.build_fuzzers(False, engine="libfuzzer", sanitizer="address")
    result = libpng_oss_fuzz_task.reproduce_pov(
        fuzzer_name="libpng_read_fuzzer",
        crash_path=libpng_crash_testcase,
    )
    assert result.success is True, "POV was triggered but it should not have been"


def test_copy_task(challenge_task: ChallengeTask, mock_subprocess):
    """Test copying a challenge task to a temporary directory."""
    # Create a test file in the source directory to verify it gets copied
    test_file = challenge_task.task_dir / challenge_task.source_subpath / "test.txt"
    test_content = "test content"
    test_file.write_text(test_content)

    with patch.object(ChallengeTask, '_check_python_path'):
        with challenge_task.copy() as local_task:
            # Verify the task directory is different
            assert local_task.task_dir != challenge_task.task_dir
            
            # Verify the file structure was copied
            assert (local_task.task_dir / local_task.source_subpath).is_dir()
            assert (local_task.task_dir / local_task.oss_fuzz_subpath).is_dir()
            assert (local_task.task_dir / local_task.diffs_subpath).is_dir()
            
            # Verify file contents were copied
            copied_file = local_task.task_dir / local_task.source_subpath / "test.txt"
            assert copied_file.exists()
            assert copied_file.read_text() == test_content
            
            # Verify we can modify the copy without affecting the original
            new_content = "modified content"
            copied_file.write_text(new_content)
            assert test_file.read_text() == test_content

            result = local_task.build_image()
            assert result.success is True
            assert result.output is not None
            assert result.output == b"output line 1\noutput line 2\n"
            mock_subprocess.assert_called_once()
        
    # Verify the temporary directory was cleaned up
    assert not local_task.task_dir.exists()
