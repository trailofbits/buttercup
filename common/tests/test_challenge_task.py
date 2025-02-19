from pathlib import Path
import pytest
from unittest.mock import Mock, patch
import subprocess
from buttercup.common.challenge_task import ChallengeTask, ChallengeTaskError


@pytest.fixture
def task_dir(tmp_path: Path) -> Path:
    """Create a mock challenge task directory structure."""
    # Create the main directories
    oss_fuzz = tmp_path / "fuzz-tooling" / "my-oss-fuzz"
    source = tmp_path / "src" / "my-source"
    diffs = tmp_path / "diff" / "my-diff"

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

    return tmp_path


@pytest.fixture
def challenge_task_readonly(task_dir: Path) -> ChallengeTask:
    """Create a mock challenge task for testing."""
    return ChallengeTask(
        read_only_task_dir=task_dir,
        project_name="example_project",
    )


@pytest.fixture
def challenge_task(task_dir: Path) -> ChallengeTask:
    """Create a mock challenge task for testing."""
    return ChallengeTask(
        read_only_task_dir=task_dir,
        local_task_dir=task_dir,
        project_name="example_project",
    )


@pytest.fixture
def challenge_task_custom_python(task_dir: Path) -> ChallengeTask:
    """Create a mock challenge task with custom python path for testing."""
    return ChallengeTask(
        read_only_task_dir=task_dir,
        local_task_dir=task_dir,
        project_name="example_project",
        python_path="/usr/bin/python3",
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
    assert challenge_task.get_oss_fuzz_subpath() == Path("fuzz-tooling") / "my-oss-fuzz"
    assert challenge_task.get_source_subpath() == Path("src") / "my-source"
    assert challenge_task.get_diff_subpath() == Path("diff") / "my-diff"

    assert (challenge_task.task_dir / challenge_task.get_oss_fuzz_subpath()).is_dir()
    assert (challenge_task.task_dir / challenge_task.get_source_subpath()).is_dir()
    assert (challenge_task.task_dir / challenge_task.get_diff_subpath()).is_dir()

    assert challenge_task.get_source_path() == challenge_task.task_dir / challenge_task.get_source_subpath()
    assert challenge_task.get_diff_path() == challenge_task.task_dir / challenge_task.get_diff_subpath()
    assert challenge_task.get_oss_fuzz_path() == challenge_task.task_dir / challenge_task.get_oss_fuzz_subpath()


def test_readonly_task(challenge_task_readonly: ChallengeTask):
    """Test that a readonly task raises an error when trying to build."""
    with pytest.raises(ChallengeTaskError, match="Challenge Task is read-only, cannot perform this operation"):
        challenge_task_readonly.build_image()

    with pytest.raises(ChallengeTaskError, match="Challenge Task is read-only, cannot perform this operation"):
        challenge_task_readonly.build_fuzzers(engine="libfuzzer", sanitizer="address")

    with pytest.raises(ChallengeTaskError, match="Challenge Task is read-only, cannot perform this operation"):
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
    assert kwargs["cwd"] == challenge_task.task_dir / challenge_task.get_oss_fuzz_subpath()

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
    assert args[0][-1].endswith(str(challenge_task.get_source_subpath()))
    assert kwargs["cwd"] == challenge_task.task_dir / challenge_task.get_oss_fuzz_subpath()


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
    assert kwargs["cwd"] == challenge_task.task_dir / challenge_task.get_oss_fuzz_subpath()


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
    assert kwargs["cwd"] == challenge_task.task_dir / challenge_task.get_oss_fuzz_subpath()


def test_failed_build_image(challenge_task: ChallengeTask, mock_failed_subprocess):
    """Test handling failed build image operation."""
    result = challenge_task.build_image()

    assert result.success is False
    assert result.error == b"Build failed"


def test_invalid_task_dir():
    """Test handling of invalid task directory."""
    with pytest.raises(ChallengeTaskError, match="Missing required directory: /nonexistent"):
        ChallengeTask(
            read_only_task_dir=Path("/nonexistent"),
            project_name="example_project",
        )


def test_missing_required_dirs(tmp_path: Path):
    """Test handling of missing required directories."""
    # Create task dir without required subdirectories
    task_dir = tmp_path / "task"
    task_dir.mkdir()

    with pytest.raises(ChallengeTaskError, match=f"Missing required directory: {task_dir / 'src'}"):
        ChallengeTask(
            read_only_task_dir=task_dir,
            project_name="example_project",
        )


def test_build_image_custom_python(challenge_task_custom_python: ChallengeTask, mock_subprocess):
    """Test building the docker image using custom python path."""
    result = challenge_task_custom_python.build_image()

    assert result.success is True
    mock_subprocess.assert_called_once()
    args, kwargs = mock_subprocess.call_args
    assert args[0] == ["/usr/bin/python3", "infra/helper.py", "build_image", "--no-pull", "example_project"]
    assert kwargs["cwd"] == challenge_task_custom_python.task_dir / challenge_task_custom_python.get_oss_fuzz_subpath()


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
        "/usr/bin/python3",
        "infra/helper.py",
        "build_fuzzers",
        "--engine",
        "libfuzzer",
        "--sanitizer",
        "address",
        "example_project",
    ]
    assert args[0][-1].endswith(str(challenge_task_custom_python.get_source_subpath()))
    assert kwargs["cwd"] == challenge_task_custom_python.task_dir / challenge_task_custom_python.get_oss_fuzz_subpath()


@pytest.fixture
def libjpeg_oss_fuzz_task(tmp_path: Path) -> ChallengeTask:
    """Create a challenge task using a real OSS-Fuzz repository."""
    # Clone real oss-fuzz repo into temp dir
    oss_fuzz_dir = tmp_path / "fuzz-tooling"
    oss_fuzz_dir.mkdir(parents=True)
    source_dir = tmp_path / "src"
    source_dir.mkdir(parents=True)

    subprocess.run(["git", "-C", str(oss_fuzz_dir), "clone", "https://github.com/google/oss-fuzz.git"], check=True)
    # Restore libjpeg-turbo project directory to specific commit
    subprocess.run(
        [
            "git",
            "-C",
            str(oss_fuzz_dir / "oss-fuzz"),
            "checkout",
            "a5d517924f758028f299d7c6cecf3b471503a202",
            "--",
            "projects/libjpeg-turbo",
        ],
        check=True,
    )

    # Download libpng source code
    libjpeg_url = "https://github.com/libjpeg-turbo/libjpeg-turbo"
    # Checkout specific libjpeg commit for reproducibility
    subprocess.run(["git", "-C", str(source_dir), "clone", libjpeg_url], check=True)
    subprocess.run(
        ["git", "-C", str(source_dir / "libjpeg-turbo"), "checkout", "6d91e950c871103a11bac2f10c63bf998796c719"],
        check=True,
    )

    return ChallengeTask(
        read_only_task_dir=tmp_path,
        local_task_dir=tmp_path,
        project_name="libjpeg-turbo",
    )


@pytest.fixture
def libjpeg_crash_testcase() -> Path:
    """Get libjpeg-turbo crash testcase"""
    crash_file = Path(__file__).parent / "data" / "libjpeg-crash"
    if not crash_file.exists():
        raise FileNotFoundError(f"Crash file not found at {crash_file}")

    return crash_file


@pytest.mark.integration
def test_real_build_workflow(libjpeg_oss_fuzz_task: ChallengeTask):
    """Test the full build workflow using actual OSS-Fuzz repository."""
    # Build the base image
    result = libjpeg_oss_fuzz_task.build_image(pull_latest_base_image=False)
    assert result.success is True, f"Build image failed: {result.error}"

    # Build the fuzzers
    result = libjpeg_oss_fuzz_task.build_fuzzers(
        engine="libfuzzer",
        sanitizer="address",
        architecture="x86_64",
    )
    assert result.success is True, f"Build fuzzers failed: {result.error}"

    # Check the build
    result = libjpeg_oss_fuzz_task.check_build(
        engine="libfuzzer",
        sanitizer="address",
        architecture="x86_64",
    )
    assert result.success is True, f"Check build failed: {result.error}"


@pytest.mark.integration
def test_build_fuzzers_with_cache(libjpeg_oss_fuzz_task: ChallengeTask):
    """Test building fuzzers with cache."""
    result = libjpeg_oss_fuzz_task.build_fuzzers_with_cache(
        engine="libfuzzer",
        sanitizer="address",
    )
    assert result.success is True
    assert result.output is not None
    assert "cp /src/libjpeg_turbo_fuzzer_seed_corpus.zip /out/" in result.output.decode()

    result = libjpeg_oss_fuzz_task.build_fuzzers_with_cache(
        engine="libfuzzer",
        sanitizer="address",
    )
    assert result.success is True
    assert result.output is not None
    assert "Check build passed" in result.output.decode()
    assert "cp /src/libjpeg_turbo_fuzzer_seed_corpus.zip /out/" not in result.output.decode()


@pytest.mark.integration
def test_real_reproduce_pov(libjpeg_oss_fuzz_task: ChallengeTask, libjpeg_crash_testcase: Path):
    """Test the reproduce POV workflow using actual OSS-Fuzz repository."""
    # Reproduce the POV
    libjpeg_oss_fuzz_task.build_image(pull_latest_base_image=False)
    libjpeg_oss_fuzz_task.build_fuzzers(engine="libfuzzer", sanitizer="address")
    result = libjpeg_oss_fuzz_task.reproduce_pov(
        fuzzer_name="libjpeg_turbo_fuzzer",
        crash_path=libjpeg_crash_testcase,
    )
    assert result.success is False, "Reproduce POV failed"


def test_copy_task(challenge_task_readonly: ChallengeTask, mock_subprocess):
    """Test copying a challenge task to a temporary directory."""
    with patch.object(ChallengeTask, "_check_python_path"):
        with challenge_task_readonly.get_rw_copy() as local_task:
            # Verify the task directory is different
            assert local_task.task_dir != challenge_task_readonly.task_dir

            # Verify the file structure was copied
            assert local_task.get_source_path().is_dir()
            assert local_task.get_oss_fuzz_path().is_dir()
            assert local_task.get_diff_path().is_dir()

            # Verify file contents were copied
            copied_file = local_task.get_source_path() / "test.txt"
            assert copied_file.exists()
            assert copied_file.read_text() == "mock test content"

            # Verify we can modify the copy without affecting the original
            new_content = "modified content"
            copied_file.write_text(new_content)
            assert copied_file.read_text() != (challenge_task_readonly.get_source_path() / "test.txt").read_text()

            result = local_task.build_image()
            assert result.success is True
            assert result.output is not None
            assert result.output == b"output line 1\noutput line 2\n"
            mock_subprocess.assert_called_once()

    # Verify the temporary directory was cleaned up
    assert not local_task.task_dir.exists()


def test_commit_task(challenge_task_readonly: ChallengeTask, mock_subprocess):
    """Test committing a challenge task."""
    with patch.object(ChallengeTask, "_check_python_path"):
        with challenge_task_readonly.get_rw_copy() as local_task:
            local_task.build_image()
            local_task.build_fuzzers(engine="libfuzzer", sanitizer="address")
            old_local_dir = local_task.task_dir
            local_task.commit()
            commited_local_dir = local_task.task_dir
            assert commited_local_dir != old_local_dir
            assert commited_local_dir.exists()
            assert commited_local_dir.is_dir()
            assert not old_local_dir.exists()

        commited_task = ChallengeTask(
            read_only_task_dir=commited_local_dir,
            local_task_dir=commited_local_dir,
            project_name="example_project",
        )
        assert commited_task.get_source_path().exists()
        assert commited_task.get_oss_fuzz_path().exists()
        assert commited_task.get_diff_path().exists()

        with pytest.raises(ChallengeTaskError, match="Missing required directory"):
            ChallengeTask(
                read_only_task_dir=old_local_dir,
                local_task_dir=old_local_dir,
                project_name="example_project",
            )


def test_commit_task_with_suffix(challenge_task_readonly: ChallengeTask, mock_subprocess, tmp_path: Path):
    """Test committing a challenge task with a suffix."""
    with patch.object(ChallengeTask, "_check_python_path"):
        with challenge_task_readonly.get_rw_copy(work_dir=tmp_path) as local_task:
            local_task.commit(suffix="test")

        with challenge_task_readonly.get_rw_copy(work_dir=tmp_path) as local_task:
            with pytest.raises(ChallengeTaskError, match="Failed to commit task"):
                local_task.commit(suffix="test")


def test_no_commit_task(challenge_task_readonly: ChallengeTask, mock_subprocess):
    """Test that a not-commited task cannot be accessed after the context manager is closed."""
    with patch.object(ChallengeTask, "_check_python_path"):
        with challenge_task_readonly.get_rw_copy() as local_task:
            local_task.build_image()
            local_task.build_fuzzers(engine="libfuzzer", sanitizer="address")
            old_local_dir = local_task.task_dir

        with pytest.raises(ChallengeTaskError, match="Missing required directory"):
            ChallengeTask(
                read_only_task_dir=old_local_dir,
                local_task_dir=old_local_dir,
                project_name="example_project",
            )


def test_get_diffs(challenge_task: ChallengeTask):
    """Test getting diffs from the source code."""
    diffs = challenge_task.get_diffs()
    assert len(diffs) == 2
    assert diffs[0].name == "patch1.diff"
    assert diffs[1].name == "patch2.diff"


def test_apply_patch_diff(challenge_task: ChallengeTask):
    """Test applying a patch diff to the source code."""
    diff_path = challenge_task.get_diff_path() / "patch1.diff"
    challenge_task.get_diffs = Mock(return_value=[diff_path])
    with diff_path.open("w") as f:
        f.write(r"""diff -ru a/test.txt b/test.txt
--- a/test.txt        2025-02-18 14:27:44.815130716 +0000
+++ b/test.txt        2025-02-18 14:28:12.061424543 +0000
@@ -1 +1 @@
-mock test content
\ No newline at end of file
+modified content
\ No newline at end of file
""")

    challenge_task.apply_patch_diff()
    assert challenge_task.get_source_path().joinpath("test.txt").exists()
    assert challenge_task.get_source_path().joinpath("test.txt").read_text() == "modified content"


def test_restore_task(challenge_task_readonly: ChallengeTask):
    """Test restoring a challenge task."""
    with patch.object(ChallengeTask, "_check_python_path"):
        with challenge_task_readonly.get_rw_copy() as local_task:
            local_task.get_source_path().joinpath("a.txt").write_text("a")
            local_task.get_source_path().joinpath("b.txt").write_text("b")
            assert local_task.get_source_path().joinpath("a.txt").exists()

            local_task.restore()
            assert not local_task.get_source_path().joinpath("a.txt").exists()
            assert not local_task.get_source_path().joinpath("b.txt").exists()
            assert local_task.get_source_path().joinpath("test.txt").exists()


def test_restore_task_same_dir(challenge_task: ChallengeTask):
    """Test restoring a challenge task to the same directory."""
    with patch.object(ChallengeTask, "_check_python_path"):
        with challenge_task.get_rw_copy() as local_task:
            assert local_task.task_dir == local_task.read_only_task_dir
            local_task.get_source_path().joinpath("b.txt").write_text("b")

            with pytest.raises(
                ChallengeTaskError, match="Task cannot be restored, it doesn't have a local task directory"
            ):
                local_task.restore()
