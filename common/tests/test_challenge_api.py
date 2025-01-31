from pathlib import Path
import pytest
from typing import List, Dict, Any
from unittest.mock import Mock, patch, MagicMock

from buttercup.common.challenge_task import ChallengeTask

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
    
    return tmp_path

@pytest.fixture
def challenge_task(task_dir: Path) -> ChallengeTask:
    """Create a mock challenge task for testing."""
    return ChallengeTask(task_dir=task_dir, project_name="example_project")

@pytest.fixture
def challenge_task_custom_python(task_dir: Path) -> ChallengeTask:
    """Create a mock challenge task with custom python path for testing."""
    return ChallengeTask(task_dir=task_dir, project_name="example_project", python_path="/usr/local/bin/python3")

@pytest.fixture
def mock_subprocess():
    """Mock subprocess calls for testing."""
    with patch("subprocess.run") as mock_run:
        mock_run.return_value.returncode = 0
        yield mock_run

def test_directory_structure(challenge_task: ChallengeTask):
    """Test that the challenge task correctly identifies its directory structure."""
    assert challenge_task.oss_fuzz_dir == challenge_task.task_dir / "oss-fuzz"
    assert challenge_task.source_dir == challenge_task.task_dir / "source"
    assert challenge_task.diffs_dir == challenge_task.task_dir / "diffs"
    
    assert challenge_task.oss_fuzz_dir.is_dir()
    assert challenge_task.source_dir.is_dir()
    assert challenge_task.diffs_dir.is_dir()

def test_build_image(challenge_task: ChallengeTask, mock_subprocess):
    """Test building the docker image for the project."""
    result = challenge_task.build_image()
    
    assert result.success is True
    mock_subprocess.assert_called_once_with(
        ["python3", "infra/helper.py", "build_image", "example_project"],
        cwd=challenge_task.oss_fuzz_dir,
        check=False,
        capture_output=True,
        text=True
    )

def test_build_fuzzers(challenge_task: ChallengeTask, mock_subprocess):
    """Test building fuzzers with different configurations."""
    result = challenge_task.build_fuzzers(
        engine="libfuzzer",
        sanitizer="address",
    )
    
    assert result.success is True
    mock_subprocess.assert_called_once_with(
        [
            "python3",
            "infra/helper.py",
            "build_fuzzers",
            "--engine", "libfuzzer",
            "--sanitizer", "address",
            "example_project",
        ],
        cwd=challenge_task.oss_fuzz_dir,
        env={"PYTHON_VERSION": "3.11"},
        check=False,
        capture_output=True,
        text=True
    )

def test_check_build(challenge_task: ChallengeTask, mock_subprocess):
    """Test checking the build status."""
    result = challenge_task.check_build(
        engine="libfuzzer",
        sanitizer="address"
    )
    
    assert result.success is True
    mock_subprocess.assert_called_once_with(
        [
            "python3",
            "infra/helper.py",
            "check_build",
            "--engine", "libfuzzer",
            "--sanitizer", "address",
            "example_project",
        ],
        cwd=challenge_task.oss_fuzz_dir,
        check=False,
        capture_output=True,
        text=True
    )

def test_reproduce_pov(challenge_task: ChallengeTask, mock_subprocess):
    """Test reproducing a proof of vulnerability."""
    pov_file = Path("crash-sample")
    target = "fuzz_target"
    
    result = challenge_task.reproduce_pov(
        pov_file=pov_file,
        target=target,
        engine="libfuzzer",
        sanitizer="address"
    )
    
    assert result.success is True
    mock_subprocess.assert_called_once_with(
        [
            "python3",
            "infra/helper.py",
            "reproduce",
            "--engine", "libfuzzer",
            "--sanitizer", "address",
            "example_project",
            target,
            str(pov_file)
        ],
        cwd=challenge_task.oss_fuzz_dir,
        check=False,
        capture_output=True,
        text=True
    )

def test_get_language(challenge_task: ChallengeTask):
    """Test getting the challenge task language."""
    assert challenge_task.language == "c"

def test_failed_build_image(challenge_task: ChallengeTask, mock_subprocess):
    """Test handling failed build image operation."""
    mock_subprocess.return_value.returncode = 1
    mock_subprocess.return_value.stderr = "Build failed"
    
    result = challenge_task.build_image()
    
    assert result.success is False
    assert result.error == "Build failed"

def test_invalid_engine(challenge_task: ChallengeTask):
    """Test handling invalid fuzzing engine."""
    with pytest.raises(ValueError, match="Invalid engine"):
        challenge_task.build_fuzzers(engine="invalid_engine", sanitizer="address")

def test_invalid_sanitizer(challenge_task: ChallengeTask):
    """Test handling invalid sanitizer."""
    with pytest.raises(ValueError, match="Invalid sanitizer"):
        challenge_task.build_fuzzers(engine="libfuzzer", sanitizer="invalid_sanitizer")

def test_invalid_task_dir():
    """Test handling of invalid task directory."""
    with pytest.raises(ValueError, match="Task directory does not exist"):
        ChallengeTask(
            task_dir=Path("/nonexistent"),
            source_repo="example/repo",
            language="c++"
        )

def test_missing_required_dirs(tmp_path: Path):
    """Test handling of missing required directories."""
    # Create task dir without required subdirectories
    task_dir = tmp_path / "task"
    task_dir.mkdir()
    
    with pytest.raises(ValueError, match="Missing required directory"):
        ChallengeTask(
            task_dir=task_dir,
            source_repo="example_project",
        )

def test_build_image_custom_python(challenge_task_custom_python: ChallengeTask, mock_subprocess):
    """Test building the docker image using custom python path."""
    result = challenge_task_custom_python.build_image()
    
    assert result.success is True
    mock_subprocess.assert_called_once_with(
        ["/usr/local/bin/python3", "infra/helper.py", "build_image", "example_project"],
        cwd=challenge_task_custom_python.oss_fuzz_dir,
        check=False,
        capture_output=True,
        text=True
    )

def test_build_fuzzers_custom_python(challenge_task_custom_python: ChallengeTask, mock_subprocess):
    """Test building fuzzers with custom python path."""
    result = challenge_task_custom_python.build_fuzzers(
        engine="libfuzzer",
        sanitizer="address",
    )
    
    assert result.success is True
    mock_subprocess.assert_called_once_with(
        [
            "/usr/local/bin/python3",
            "infra/helper.py",
            "build_fuzzers",
            "--engine", "libfuzzer",
            "--sanitizer", "address",
            "example_project",
        ],
        cwd=challenge_task_custom_python.oss_fuzz_dir,
        check=False,
        capture_output=True,
        text=True
    )
