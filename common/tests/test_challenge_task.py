from pathlib import Path
import pytest
from unittest.mock import MagicMock, patch
import subprocess
import os
import base64
from buttercup.common.challenge_task import (
    ChallengeTask,
    ChallengeTaskError,
    ReproduceResult,
    CommandResult,
)
from buttercup.common.task_meta import TaskMeta
import tempfile


@pytest.fixture
def task_dir(tmp_path: Path) -> Path:
    """Create a mock challenge task directory structure."""
    # Create the main directories
    tmp_path = tmp_path / "task-id-challenge-task"
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

    # Create task metadata
    TaskMeta(
        project_name="example_project",
        focus="my-source",
        task_id="task-id-challenge-task",
        metadata={"task_id": "task-id-challenge-task", "round_id": "testing", "team_id": "tob"},
    ).save(tmp_path)

    return tmp_path


@pytest.fixture
def challenge_task_readonly(task_dir: Path) -> ChallengeTask:
    """Create a mock challenge task for testing."""
    return ChallengeTask(
        read_only_task_dir=task_dir,
    )


@pytest.fixture
def challenge_task(task_dir: Path) -> ChallengeTask:
    """Create a mock challenge task for testing."""
    return ChallengeTask(
        read_only_task_dir=task_dir,
        local_task_dir=task_dir,
    )


@pytest.fixture
def challenge_task_custom_python(task_dir: Path) -> ChallengeTask:
    """Create a mock challenge task with custom python path for testing."""
    return ChallengeTask(
        read_only_task_dir=task_dir,
        local_task_dir=task_dir,
        python_path="/usr/bin/python3",
    )


def get_mock_popen(returncode: int, stdout: list[bytes], stderr: list[bytes]):
    with patch("subprocess.Popen") as mock_popen:
        mock_process = MagicMock()
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

    assert result.did_crash() is False
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
        )


def test_missing_required_dirs(tmp_path: Path):
    """Test handling of missing required directories."""
    # Create task dir without required subdirectories
    task_dir = tmp_path / "task"
    task_dir.mkdir()

    # Add TaskMeta even though directories are missing
    TaskMeta(
        project_name="example_project",
        focus="my-source",
        task_id="task-id-challenge-task",
        metadata={"task_id": "task-id-challenge-task", "round_id": "testing", "team_id": "tob"},
    ).save(task_dir)

    with pytest.raises(ChallengeTaskError, match=f"Missing required directory: {task_dir / 'src'}"):
        ChallengeTask(
            read_only_task_dir=task_dir,
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
def libjpeg_oss_fuzz_task_dir(tmp_path: Path) -> Path:
    """Create a challenge task using a real OSS-Fuzz repository."""
    # Clone real oss-fuzz repo into temp dir
    tmp_path = tmp_path / "libjpeg-turbo"
    tmp_path.mkdir(parents=True)

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

    # Create task metadata
    TaskMeta(
        project_name="libjpeg-turbo",
        focus="libjpeg-turbo",
        task_id="task-id-libjpeg-turbo",
        metadata={"task_id": "task-id-libjpeg-turbo", "round_id": "testing", "team_id": "tob"},
    ).save(tmp_path)

    yield tmp_path


@pytest.fixture
def libjpeg_oss_fuzz_task(libjpeg_oss_fuzz_task_dir: Path) -> ChallengeTask:
    return ChallengeTask(
        read_only_task_dir=libjpeg_oss_fuzz_task_dir,
    )


@pytest.fixture
def libjpeg_oss_fuzz_task_rw(libjpeg_oss_fuzz_task: ChallengeTask) -> ChallengeTask:
    with libjpeg_oss_fuzz_task.get_rw_copy(None) as local_task:
        yield local_task


@pytest.fixture
def libjpeg_crash_testcase() -> Path:
    """Get libjpeg-turbo crash testcase"""
    crash_file = Path(__file__).parent / "data" / "libjpeg-crash"
    if not crash_file.exists():
        raise FileNotFoundError(f"Crash file not found at {crash_file}")

    return crash_file


@pytest.mark.integration
def test_real_build_workflow(libjpeg_oss_fuzz_task_rw: ChallengeTask):
    """Test the full build workflow using actual OSS-Fuzz repository."""
    # Build the base image
    result = libjpeg_oss_fuzz_task_rw.build_image(pull_latest_base_image=False)
    assert result.success is True, f"Build image failed: {result.error}"

    # Build the fuzzers
    result = libjpeg_oss_fuzz_task_rw.build_fuzzers(
        engine="libfuzzer",
        sanitizer="address",
        architecture="x86_64",
    )
    assert result.success is True, f"Build fuzzers failed: {result.error}"

    # Check the build
    result = libjpeg_oss_fuzz_task_rw.check_build(
        engine="libfuzzer",
        sanitizer="address",
        architecture="x86_64",
    )
    assert result.success is True, f"Check build failed: {result.error}"


@pytest.mark.integration
def test_build_fuzzers_with_cache(libjpeg_oss_fuzz_task_rw: ChallengeTask):
    """Test building fuzzers with cache."""
    result = libjpeg_oss_fuzz_task_rw.build_fuzzers_with_cache(
        engine="libfuzzer",
        sanitizer="address",
    )
    assert result.success is True
    assert result.output is not None
    assert "cp /src/libjpeg_turbo_fuzzer_seed_corpus.zip /out/" in result.output.decode()

    result = libjpeg_oss_fuzz_task_rw.build_fuzzers_with_cache(
        engine="libfuzzer",
        sanitizer="address",
    )
    assert result.success is True
    assert result.output is not None
    assert "Check build passed" in result.output.decode()
    assert "cp /src/libjpeg_turbo_fuzzer_seed_corpus.zip /out/" not in result.output.decode()


@pytest.mark.integration
def test_real_reproduce_pov(libjpeg_oss_fuzz_task_rw: ChallengeTask, libjpeg_crash_testcase: Path):
    """Test the reproduce POV workflow using actual OSS-Fuzz repository."""
    # Reproduce the POV
    libjpeg_oss_fuzz_task_rw.build_image(pull_latest_base_image=False)
    libjpeg_oss_fuzz_task_rw.build_fuzzers(engine="libfuzzer", sanitizer="address")
    result = libjpeg_oss_fuzz_task_rw.reproduce_pov(
        fuzzer_name="libjpeg_turbo_fuzzer",
        crash_path=libjpeg_crash_testcase,
    )
    assert result.did_crash(), "Reproduce POV failed"


def test_copy_task(challenge_task_readonly: ChallengeTask, mock_subprocess):
    """Test copying a challenge task to a temporary directory."""
    with patch.object(ChallengeTask, "_check_python_path"):
        with challenge_task_readonly.get_rw_copy(None) as local_task:
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
        with challenge_task_readonly.get_rw_copy(None) as local_task:
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
        )
        assert commited_task.get_source_path().exists()
        assert commited_task.get_oss_fuzz_path().exists()
        assert commited_task.get_diff_path().exists()

        with pytest.raises(ChallengeTaskError, match="Missing required directory"):
            ChallengeTask(
                read_only_task_dir=old_local_dir,
                local_task_dir=old_local_dir,
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
        with challenge_task_readonly.get_rw_copy(None) as local_task:
            local_task.build_image()
            local_task.build_fuzzers(engine="libfuzzer", sanitizer="address")
            old_local_dir = local_task.task_dir

        with pytest.raises(ChallengeTaskError, match="Missing required directory"):
            ChallengeTask(
                read_only_task_dir=old_local_dir,
                local_task_dir=old_local_dir,
            )


def test_get_diffs(challenge_task: ChallengeTask):
    """Test getting diffs from the source code."""
    diffs = challenge_task.get_diffs()
    assert len(diffs) == 2
    assert diffs[0].name == "patch1.diff"
    assert diffs[1].name == "patch2.diff"


def test_is_delta_mode(challenge_task: ChallengeTask):
    """Test checking if the task is in diff mode."""
    assert challenge_task.is_delta_mode() is True


def test_apply_patch_diff(challenge_task: ChallengeTask):
    """Test applying a patch diff to the source code."""
    diff_path = challenge_task.get_diff_path() / "patch1.diff"
    challenge_task.get_diffs = MagicMock(return_value=[diff_path])
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
        with challenge_task_readonly.get_rw_copy(None) as local_task:
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
        with challenge_task.get_rw_copy(None) as local_task:
            assert local_task.task_dir != local_task.read_only_task_dir, "get_rw_copy should always create a copy"
            local_task.get_source_path().joinpath("b.txt").write_text("b")

            local_task.restore()


def test_workdir_from_dockerfile(challenge_task_readonly: ChallengeTask):
    """Test getting the workdir from the dockerfile."""
    assert challenge_task_readonly.workdir_from_dockerfile() == Path("/src/example_project")


@pytest.mark.integration
def test_workdir_from_dockerfile_libjpeg(libjpeg_oss_fuzz_task: ChallengeTask):
    """Test getting the workdir from the dockerfile."""
    assert libjpeg_oss_fuzz_task.workdir_from_dockerfile() == Path("/src/libjpeg-turbo")


@pytest.mark.integration
def test_exec_docker_cmd(libjpeg_oss_fuzz_task_rw: ChallengeTask):
    """Test executing a command inside the docker container."""
    result = libjpeg_oss_fuzz_task_rw.exec_docker_cmd(["ls", "/"])
    assert result.success is True
    assert result.output is not None
    assert "root" in result.output.decode()

    result = libjpeg_oss_fuzz_task_rw.exec_docker_cmd(["ls", "/src"])
    assert result.success is True
    assert result.output is not None
    assert "libjpeg-turbo" in result.output.decode()

    # Test mounting directories
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)

        # Create some test files
        (tmp_path / "test1.txt").write_text("test1")
        (tmp_path / "test2.txt").write_text("test2")

        # Mount the temp dir to /mnt in container
        mount_dirs = {tmp_path: Path("/mnt")}

        result = libjpeg_oss_fuzz_task_rw.exec_docker_cmd(["ls", "/mnt"], mount_dirs=mount_dirs)
        assert result.success is True
        assert result.output is not None
        assert "test1.txt" in result.output.decode()
        assert "test2.txt" in result.output.decode()

        # Verify we can read the file contents
        result = libjpeg_oss_fuzz_task_rw.exec_docker_cmd(["cat", "/mnt/test1.txt"], mount_dirs=mount_dirs)
        assert result.success is True
        assert result.output is not None
        assert result.output.decode() == "test1"


@pytest.mark.integration
def test_build_and_restore(libjpeg_oss_fuzz_task_rw: ChallengeTask):
    """Test building and restoring a challenge task."""
    libjpeg_oss_fuzz_task_rw.build_image()
    libjpeg_oss_fuzz_task_rw.build_fuzzers()
    libjpeg_oss_fuzz_task_rw.commit()

    # Modify the source code
    libjpeg_oss_fuzz_task_rw.get_source_path().joinpath("test.txt").write_text("modified content")

    libjpeg_oss_fuzz_task_rw.restore()

    assert not libjpeg_oss_fuzz_task_rw.get_source_path().joinpath("test.txt").exists()


@pytest.mark.integration
def test_tmp_dir(libjpeg_oss_fuzz_task: ChallengeTask):
    """Test building fuzzers with cache."""
    local_dir = None
    with libjpeg_oss_fuzz_task.get_rw_copy(None) as local_task:
        local_dir = local_task.task_dir
        assert local_dir.exists()
        assert local_dir.is_dir()
        local_task.build_fuzzers()

    assert not local_dir.exists()


@pytest.mark.integration
def test_container_image(libjpeg_oss_fuzz_task: ChallengeTask):
    """Test getting the container image."""
    assert libjpeg_oss_fuzz_task.container_image() == "gcr.io/oss-fuzz/libjpeg-turbo"


@pytest.mark.integration
def test_container_image_custom_org(libjpeg_oss_fuzz_task_dir: Path):
    """Test getting the container image with a custom organization."""
    with patch.dict(os.environ, {"OSS_FUZZ_CONTAINER_ORG": "myorg"}):
        task = ChallengeTask(
            read_only_task_dir=libjpeg_oss_fuzz_task_dir,
        )
        assert task.container_image() == "myorg/libjpeg-turbo"


@pytest.fixture(autouse=True)
def mock_node_data_dir():
    """Set the NODE_DATA_DIR environment variable for all tests."""
    with patch.dict(os.environ, {"NODE_DATA_DIR": "/test/node/data/dir"}):
        yield


@pytest.fixture(autouse=True)
def mock_node_local(monkeypatch, tmp_path: Path):
    """Mock the node_local module functions used by ChallengeTask."""
    # Create a patch for buttercup.common.node_local's _get_root_path to return a valid path
    with patch("buttercup.common.node_local._get_root_path", return_value=Path("/test/node/data/dir")):
        # Create a patch for remote_archive_to_dir that just returns the path
        with patch("buttercup.common.node_local.remote_archive_to_dir") as mock_remote_archive:
            # Create a patch for scratch_path to return a valid path
            with patch("buttercup.common.node_local.scratch_path", return_value=tmp_path / "node-local-scratch"):
                # The remote_archive_to_dir function should just return the input path
                mock_remote_archive.side_effect = lambda p: p
                yield


@patch("buttercup.common.node_local._get_root_path")
@patch("buttercup.common.node_local.remote_archive_to_dir")
def test_challenge_task_with_node_local_storage_existing(
    mock_remote_archive_to_dir, mock_get_root_path, mock_node_local_storage, task_dir
):
    """Test ChallengeTask behavior when using node_local and path exists."""
    mock_get_root_path.return_value = Path(mock_node_local_storage)
    # When path already exists, remote_archive_to_dir should not be called
    mock_remote_archive_to_dir.side_effect = Exception("Should not be called")

    # Create a path that exists in the node local storage
    existing_path = Path(mock_node_local_storage) / "existing-task"

    # The original Path.exists method to use for paths we don't specifically handle
    original_exists = Path.exists

    # Patch Path.exists to return specific values based on what's being checked
    def mock_exists(self):
        # For the main task directory and helper.py, return True
        if str(self) == str(existing_path) or str(self).endswith("helper.py"):
            return True
        # For checking required directories
        if str(self).endswith("src") or str(self).endswith("fuzz-tooling"):
            return True
        # For test.txt
        if str(self).endswith("test.txt"):
            return True
        # For all other cases, call the original method
        return original_exists(self)

    # Mock is_dir to always return True for directory checks
    def mock_is_dir(self):
        return True

    with patch.object(Path, "exists", mock_exists):
        with patch.object(Path, "is_dir", mock_is_dir):
            # Create a challenge task with this path - it should use the local version
            with patch.object(ChallengeTask, "_check_python_path"):
                with patch.object(TaskMeta, "load"):
                    task = ChallengeTask(read_only_task_dir=existing_path)

                    # Verify it's using the local path
                    assert task.read_only_task_dir == existing_path

                    # Verify mock_remote_archive_to_dir wasn't called
                    mock_remote_archive_to_dir.assert_not_called()

                    # Verify content is from the local copy
                    with patch.object(Path, "read_text", return_value="node local storage content"):
                        source_file = task.get_source_path() / "test.txt"
                        assert source_file.read_text() == "node local storage content"


@patch("buttercup.common.node_local._get_root_path")
@patch("buttercup.common.node_local.remote_archive_to_dir")
def test_challenge_task_with_node_local_storage_download(
    mock_remote_archive_to_dir, mock_get_root_path, mock_node_local_storage, task_dir
):
    """Test ChallengeTask behavior when using node_local and path doesn't exist."""
    mock_get_root_path.return_value = Path(mock_node_local_storage)

    # Create a path that doesn't exist in the node local storage
    non_existing_path = Path(mock_node_local_storage) / "non-existing-task"
    downloaded_path = Path(mock_node_local_storage) / "downloaded-task"

    # Create the directory structure for the downloaded path
    downloaded_path.mkdir(exist_ok=True)
    oss_fuzz = downloaded_path / "fuzz-tooling" / "my-oss-fuzz"
    source = downloaded_path / "src" / "my-source"
    oss_fuzz.mkdir(parents=True, exist_ok=True)
    source.mkdir(parents=True, exist_ok=True)

    # Create a mock helper.py file
    helper_path = oss_fuzz / "infra/helper.py"
    helper_path.parent.mkdir(parents=True, exist_ok=True)
    helper_path.write_text("import sys;\nsys.exit(0)\n")

    # Create task metadata
    TaskMeta(
        project_name="example_project",
        focus="my-source",
        task_id="task-id-challenge-task",
        metadata={"task_id": "task-id-challenge-task", "round_id": "testing", "team_id": "tob"},
    ).save(downloaded_path)

    # Setup mock to return a downloaded path
    mock_remote_archive_to_dir.return_value = downloaded_path

    # Patch Path.exists to return False for the original path
    # but True for the downloaded path and its contents
    original_exists = Path.exists

    def mock_exists(self):
        # Non-existing path returns False
        if str(self) == str(non_existing_path):
            return False
        # For helper.py file, return True
        if str(self).endswith("helper.py"):
            return True
        # For checking directories
        if str(self).endswith("src") or str(self).endswith("fuzz-tooling"):
            return True
        # For all other cases, call the original method
        return original_exists(self)

    with patch.object(Path, "exists", mock_exists):
        # Create a challenge task with this path - it should trigger download
        with patch.object(ChallengeTask, "_check_python_path"):
            with patch.object(ChallengeTask, "_check_dir_exists"):
                task = ChallengeTask(read_only_task_dir=non_existing_path)

                # Verify remote_archive_to_dir was called with correct path
                mock_remote_archive_to_dir.assert_called_once_with(non_existing_path)

                # Verify it's using the downloaded path
                assert task.read_only_task_dir == downloaded_path


@pytest.fixture
def mock_node_local_storage(tmp_path: Path):
    """Setup a mock NODE_DATA_DIR environment for testing node local storage."""
    node_data_dir = tmp_path / "node_data_dir"
    node_data_dir.mkdir(exist_ok=True)
    scratch_dir = node_data_dir / "scratch"
    scratch_dir.mkdir(exist_ok=True)

    # Create a pre-existing local path to simulate already downloaded data
    local_task_path = node_data_dir / "existing-task"
    local_task_path.mkdir(exist_ok=True)

    # Copy task structure to local task path
    oss_fuzz = local_task_path / "fuzz-tooling" / "my-oss-fuzz"
    source = local_task_path / "src" / "my-source"
    oss_fuzz.mkdir(parents=True, exist_ok=True)
    source.mkdir(parents=True, exist_ok=True)

    # Create a mock helper.py file
    helper_path = oss_fuzz / "infra/helper.py"
    helper_path.parent.mkdir(parents=True, exist_ok=True)
    helper_path.write_text("import sys;\nsys.exit(0)\n")

    # Create a mock test.txt file with different content to verify which one is used
    (source / "test.txt").write_text("node local storage content")

    # Create task metadata
    TaskMeta(
        project_name="example_project",
        focus="my-source",
        task_id="task-id-challenge-task",
        metadata={"task_id": "task-id-challenge-task", "round_id": "testing", "team_id": "tob"},
    ).save(local_task_path)

    yield node_data_dir


@pytest.mark.integration
def test_run_fuzzer_libjpeg(libjpeg_oss_fuzz_task_rw: ChallengeTask, tmp_path: Path):
    """Test running a fuzzer on a challenge task for 10 seconds."""
    corpus_dir = tmp_path / "test-corpus"
    corpus_dir.mkdir(exist_ok=True)

    libjpeg_oss_fuzz_task_rw.build_fuzzers()
    result = libjpeg_oss_fuzz_task_rw.run_fuzzer(
        harness_name="libjpeg_turbo_fuzzer",
        corpus_dir=corpus_dir,
        fuzzer_args=["\\-max_total_time=10"],
    )
    # Can't assert success because it will be False if the fuzzer finds a crash
    # assert result.success is True
    assert result.output is not None


def test_reproduce_result_stacktrace():
    """Test the stacktrace method of ReproduceResult with various output sizes."""
    # Test case 1: Short string (under 1MB limit)
    short_output = b"INFO: Seed: 12345\nRunning normally\n==ERROR: AddressSanitizer: heap-buffer-overflow"
    result1 = ReproduceResult(
        command_result=CommandResult(success=False, returncode=1, output=short_output, error=None)
    )
    stacktrace1 = result1.stacktrace()
    assert stacktrace1 is not None
    assert stacktrace1 == short_output.decode("utf-8", errors="ignore")
    assert len(stacktrace1) == len(short_output.decode("utf-8", errors="ignore"))

    # Test case 2: Large string (over 1MB limit) - should be truncated
    # Create a large output that exceeds the 1MB limit
    MAX_OUTPUT_LEN = 1 * 1024 * 1024  # 1 MB
    large_content = (
        b"INFO: Seed: 12345\n" + b"A" * (MAX_OUTPUT_LEN + 1000) + b"\n==ERROR: AddressSanitizer: heap-buffer-overflow"
    )

    result2 = ReproduceResult(
        command_result=CommandResult(success=False, returncode=1, output=large_content, error=None)
    )
    stacktrace2 = result2.stacktrace()
    assert stacktrace2 is not None

    # Verify the output is truncated to approximately MAX_OUTPUT_LEN
    assert len(stacktrace2.encode("utf-8")) <= MAX_OUTPUT_LEN + 100  # Allow some flexibility for truncation marker

    # Verify it contains the truncation marker
    assert "...truncated" in stacktrace2

    # Verify it contains both the beginning and end of the original content
    assert "INFO: Seed: 12345" in stacktrace2
    assert "==ERROR: AddressSanitizer: heap-buffer-overflow" in stacktrace2

    # Verify the structure: start + truncation marker + end
    parts = stacktrace2.split("...truncated")
    assert len(parts) == 2
    assert parts[0].startswith("INFO: Seed: 12345")
    assert parts[1].endswith("==ERROR: AddressSanitizer: heap-buffer-overflow")

    # Test case 3: Empty output
    result3 = ReproduceResult(command_result=CommandResult(success=True, returncode=0, output=None, error=None))
    stacktrace3 = result3.stacktrace()
    assert stacktrace3 is None

    # Test case 4: Exactly at the limit (1MB)
    prefix = b"INFO: Seed: 12345\n"
    suffix = b"\n==ERROR: AddressSanitizer: heap-buffer-overflow"
    exact_size_content = prefix + b"B" * (MAX_OUTPUT_LEN - len(prefix) - len(suffix)) + suffix

    result4 = ReproduceResult(
        command_result=CommandResult(success=False, returncode=1, output=exact_size_content, error=None)
    )
    stacktrace4 = result4.stacktrace()
    assert stacktrace4 is not None

    # Should not be truncated since it's exactly at the limit
    assert len(stacktrace4.encode("utf-8")) == MAX_OUTPUT_LEN
    assert "...truncated" not in stacktrace4
    assert stacktrace4 == exact_size_content.decode("utf-8", errors="ignore")

    # Test case 5: Just over the limit (1MB + 1 byte)
    over_limit_content = (
        b"INFO: Seed: 12345\n" + b"C" * (MAX_OUTPUT_LEN - 19) + b"\n==ERROR: AddressSanitizer: heap-buffer-overflow"
    )

    result5 = ReproduceResult(
        command_result=CommandResult(success=False, returncode=1, output=over_limit_content, error=None)
    )
    stacktrace5 = result5.stacktrace()
    assert stacktrace5 is not None

    # Should be truncated since it's over the limit
    assert len(stacktrace5.encode("utf-8")) <= MAX_OUTPUT_LEN + 100
    assert "...truncated" in stacktrace5

    # Test case 6: Very large string (2MB) to test extreme truncation
    very_large_content = (
        b"INFO: Seed: 12345\n" + b"D" * (2 * MAX_OUTPUT_LEN) + b"\n==ERROR: AddressSanitizer: heap-buffer-overflow"
    )

    result6 = ReproduceResult(
        command_result=CommandResult(success=False, returncode=1, output=very_large_content, error=None)
    )
    stacktrace6 = result6.stacktrace()
    assert stacktrace6 is not None

    # Should be significantly truncated
    assert len(stacktrace6.encode("utf-8")) <= MAX_OUTPUT_LEN + 100
    assert "...truncated" in stacktrace6

    # Verify the truncation marker shows the correct number of truncated bytes
    truncation_info = stacktrace6.split("...truncated")[1].split(" bytes...")[0]
    truncated_bytes = int(truncation_info)
    assert truncated_bytes >= MAX_OUTPUT_LEN  # Should have truncated at least 1MB


def test_reproduce_result_methods():
    """Test the did_run and did_crash methods of ReproduceResult."""
    # Test case 1: Successful run, no crash
    result1 = ReproduceResult(
        command_result=CommandResult(
            success=True, returncode=0, output=b"INFO: Seed: 12345\nRunning normally", error=None
        )
    )
    assert result1.did_run() is True
    assert result1.did_crash() is False

    # Test case 2: Failed run, no crash (fuzzer didn't start)
    result2 = ReproduceResult(
        command_result=CommandResult(success=False, returncode=1, output=b"Error: Could not start fuzzer", error=None)
    )
    assert result2.did_run() is False
    assert result2.did_crash() is False

    # Test case 3: Successful run with crash
    result3 = ReproduceResult(
        command_result=CommandResult(
            success=False,
            returncode=1,
            output=b"INFO: Seed: 12345\nRunning normally\n==ERROR: AddressSanitizer: heap-buffer-overflow",
            error=None,
        )
    )
    assert result3.did_run() is True
    assert result3.did_crash() is True

    # Test case 4: Run with seed info in error output
    result4 = ReproduceResult(
        command_result=CommandResult(
            success=False,
            returncode=1,
            output=None,
            error=b"INFO: Seed: 12345\nRunning normally\n==ERROR: AddressSanitizer: heap-buffer-overflow",
        )
    )
    assert result4.did_run() is True
    assert result4.did_crash() is True

    # Test case 5: Run with None returncode
    result5 = ReproduceResult(
        command_result=CommandResult(
            success=False, returncode=None, output=b"INFO: Seed: 12345\nRunning normally", error=None
        )
    )
    assert result5.did_run() is True
    assert result5.did_crash() is False

    # Test case 6: Timeout with crash token (should be detected as crash)
    result6 = ReproduceResult(
        command_result=CommandResult(
            success=False,
            returncode=124,  # TIMEOUT_ERR_RESULT
            output=b"INFO: Seed: 12345\nRunning normally\n==ERROR: AddressSanitizer: heap-buffer-overflow\nTimeout occurred",
            error=None,
        )
    )
    assert result6.did_run() is True
    assert result6.did_crash() is True  # Should detect crash due to crash token in stacktrace

    # Test case 7: Timeout without crash token (should not be detected as crash)
    result7 = ReproduceResult(
        command_result=CommandResult(
            success=False,
            returncode=124,  # TIMEOUT_ERR_RESULT
            output=b"INFO: Seed: 12345\nRunning normally\nTimeout occurred\nNo crash detected",
            error=None,
        )
    )
    assert result7.did_run() is True
    assert result7.did_crash() is False  # Should not detect crash due to no crash token

    # Test case 8: Timeout with crash token in error output
    output = b"""/out/fuzzer-postauth_nomaths -rss_limit_mb=2560 -timeout=25 -runs=100 /testcase -max_len=50000 -timeout_exitcode=0 -dict=fuzzer-postauth_nomaths.dict < /dev/null
INFO: found LLVMFuzzerCustomMutator (0x5595fa311560). Disabling -len_control by default.
Dictionary: 58 entries
INFO: Running with entropic power schedule (0xFF, 100).
INFO: Seed: 3932698478
INFO: Loaded 1 modules   (7459 inline 8-bit counters): 7459 [0x5595fa3cec00, 0x5595fa3d0923), 
INFO: Loaded 1 PC tables (7459 PCs): 7459 [0x5595fa3d0928,0x5595fa3edb58), 
/out/fuzzer-postauth_nomaths: Running 1 inputs 100 time(s) each.
Running: /testcase
Dropbear fuzzer: Disabling stderr output
fuzzer-postauth_nomaths: src/../fuzz/fuzz-wrapfd.c:216: int wrapfd_select(int, fd_set *, fd_set *, fd_set *, struct timeval *): Assertion `wrap_fds[i].mode != UNUSED' failed.
AddressSanitizer:DEADLYSIGNAL
=================================================================
==18==ERROR: AddressSanitizer: ABRT on unknown address 0x000000000012 (pc 0x7f99ebd7600b bp 0x7f99ebeeb588 sp 0x7ffe363d6470 T0)
SCARINESS: 10 (signal)
    #0 0x7f99ebd7600b in raise (/lib/x86_64-linux-gnu/libc.so.6+0x4300b) (BuildId: 5792732f783158c66fb4f3756458ca24e46e827d)
    #1 0x7f99ebd55858 in abort (/lib/x86_64-linux-gnu/libc.so.6+0x22858) (BuildId: 5792732f783158c66fb4f3756458ca24e46e827d)
    #2 0x7f99ebd55728  (/lib/x86_64-linux-gnu/libc.so.6+0x22728) (BuildId: 5792732f783158c66fb4f3756458ca24e46e827d)
    #3 0x7f99ebd66fd5 in __assert_fail (/lib/x86_64-linux-gnu/libc.so.6+0x33fd5) (BuildId: 5792732f783158c66fb4f3756458ca24e46e827d)
    #4 0x5595fa2befa5 in wrapfd_select /src/dropbear/src/../fuzz/fuzz-wrapfd.c:216:5
    #5 0x5595fa2c004d in session_loop /src/dropbear/src/common-session.c:210:9
    #6 0x5595fa3064a0 in svr_session /src/dropbear/src/svr-session.c:208:2
    #7 0x5595fa2bcff1 in fuzz_run_server /src/dropbear/src/../fuzz/fuzz-common.c:287:9
    #8 0x5595fa156620 in fuzzer::Fuzzer::ExecuteCallback(unsigned char const*, unsigned long) /src/llvm-project/compiler-rt/lib/fuzzer/FuzzerLoop.cpp:614:13
    #9 0x5595fa141895 in fuzzer::RunOneTest(fuzzer::Fuzzer*, char const*, unsigned long) /src/llvm-project/compiler-rt/lib/fuzzer/FuzzerDriver.cpp:327:6
    #10 0x5595fa14732f in fuzzer::FuzzerDriver(int*, char***, int (*)(unsigned char const*, unsigned long)) /src/llvm-project/compiler-rt/lib/fuzzer/FuzzerDriver.cpp:862:9
    #11 0x5595fa1725d2 in main /src/llvm-project/compiler-rt/lib/fuzzer/FuzzerMain.cpp:20:10
    #12 0x7f99ebd57082 in __libc_start_main (/lib/x86_64-linux-gnu/libc.so.6+0x24082) (BuildId: 5792732f783158c66fb4f3756458ca24e46e827d)
    #13 0x5595fa139a7d in _start (/out/fuzzer-postauth_nomaths+0x7ea7d)

DEDUP_TOKEN: raise--abort--
AddressSanitizer can not provide additional info.
SUMMARY: AddressSanitizer: ABRT (/lib/x86_64-linux-gnu/libc.so.6+0x4300b) (BuildId: 5792732f783158c66fb4f3756458ca24e46e827d) in raise
==18==ABORTING
MS: 0 ; base unit: 0000000000000000000000000000000000000000
subprocess command returned a non-zero exit status: 1"""
    result8 = ReproduceResult(
        command_result=CommandResult(
            success=False,
            returncode=124,  # TIMEOUT_ERR_RESULT
            output=b"INFO: Seed: 12345\nRunning normally\n" + output + b"\nTimeout occurred",
            error=b"",
        )
    )
    assert result8.did_run() is True
    assert result8.did_crash() is True  # Should detect crash due to crash token in error output

    # Test case 9: Timeout with empty output (should not be detected as crash)
    result9 = ReproduceResult(
        command_result=CommandResult(
            success=False,
            returncode=124,  # TIMEOUT_ERR_RESULT
            output=None,
            error=None,
        )
    )
    assert result9.did_run() is False
    assert result9.did_crash() is False  # Should not detect crash due to no output and no crash token

    # Test case 10: Timeout with only seed info (should not be detected as crash)
    result10 = ReproduceResult(
        command_result=CommandResult(
            success=False,
            returncode=124,  # TIMEOUT_ERR_RESULT
            output=b"INFO: Seed: 12345\nTimeout occurred",
            error=None,
        )
    )
    assert result10.did_run() is True
    assert result10.did_crash() is False  # Should not detect crash due to no crash token

    # Test case 11: FAILURE_ERR_RESULT (201) - should not be detected as crash
    result11 = ReproduceResult(
        command_result=CommandResult(
            success=False,
            returncode=201,  # FAILURE_ERR_RESULT
            output=b"INFO: Seed: 12345\nRunning normally\n==ERROR: AddressSanitizer: heap-buffer-overflow",
            error=None,
        )
    )
    assert result11.did_run() is True
    assert result11.did_crash() is False  # Should not detect crash due to FAILURE_ERR_RESULT

    # Test case 12: Different crash patterns in timeout scenario
    result12 = ReproduceResult(
        command_result=CommandResult(
            success=False,
            returncode=124,  # TIMEOUT_ERR_RESULT
            output=b"INFO: Seed: 12345\nRunning normally\n" + output + b"\nTimeout occurred",
            error=None,
        )
    )
    assert result12.did_run() is True
    assert result12.did_crash() is True  # Should detect crash due to UBSan error in stacktrace

    # Test case 13: Timeout with multiple crash patterns
    result13 = ReproduceResult(
        command_result=CommandResult(
            success=False,
            returncode=124,  # TIMEOUT_ERR_RESULT
            output=b"INFO: Seed: 12345\nRunning normally\n" + output + b"\n" + output + b"\nTimeout occurred",
            error=None,
        )
    )
    assert result13.did_run() is True
    assert result13.did_crash() is True  # Should detect crash due to multiple crash patterns in stacktrace


@pytest.mark.integration
def test_exec_docker_cmd_grep_after_build(libjpeg_oss_fuzz_task_rw: ChallengeTask):
    """Test exec_docker_cmd running grep after build_fuzzers has been called."""
    # First call build_fuzzers to set up container
    libjpeg_oss_fuzz_task_rw.build_fuzzers()

    # Then test grep command
    result = libjpeg_oss_fuzz_task_rw.exec_docker_cmd(["ls", "-lah", "wrjpgcom"])

    assert result.success is True
    assert result.returncode == 0
    assert b"-rwxr-xr-x" in result.output and b"wrjpgcom" in result.output


def test_apply_patch_diff_with_file(challenge_task: ChallengeTask):
    """Test applying a specific patch diff file to the source code."""
    # Create a test file to patch
    test_file = challenge_task.get_source_path() / "test_file.txt"
    test_file.write_text("original content\n")

    # Create a git diff patch file
    diff_file = challenge_task.get_diff_path() / "test_patch.diff"
    diff_content = """diff --git a/test_file.txt b/test_file.txt
index 1234567..abcdefg 100644
--- a/test_file.txt
+++ b/test_file.txt
@@ -1 +1,2 @@
-original content
+modified content
+new line
"""
    diff_file.write_text(diff_content)

    # Apply the specific patch file
    result = challenge_task.apply_patch_diff(diff_file=diff_file)

    assert result is True
    assert test_file.exists()
    assert test_file.read_text() == "modified content\nnew line\n"


def test_apply_patch_diff_binary_file(challenge_task: ChallengeTask):
    """Test applying a git diff patch for a binary file."""
    # Create a binary test file
    test_binary = challenge_task.get_source_path() / "test.bin"
    exp_test_binary_content = """UEsDBBQAAAgIAHVmrlgtOwivDgAAAAwAAAAQADUAJTc0JTY1JTczJTc0LnR4dFVUDQAHnpZDZp6W
Q2aelkNmCgAgAAAAAAABABgAYaCn/x6m2gFhoKf/HqbaAWGgp/8eptoBy0jNyclXKM8vyknhAgBQ
SwECFAAUAAAICAB1Zq5YLTsIrw4AAAAMAAAAEAAtAAAAAAAAAAAAAAAAAAAAJTc0JTY1JTczJTc0
LnR4dFVUBQAHnpZDZgoAIAAAAAAAAQAYAGGgp/8eptoBYaCn/x6m2gFhoKf/HqbaAVBLBQYAAAAA
AQABAGsAAABxAAAAAAA="""

    # Create a git diff patch file for binary
    diff_file = challenge_task.get_diff_path() / "binary_patch.diff"
    diff_content = """diff --git a/test.bin b/test.bin
new file mode 100644
index 0000000000000000000000000000000000000000..e3ec044f087ad576d0dffefc4ec71cd17011c287
GIT binary patch
literal 242
zcmWIWW@Zs#VBp|jC{0@zp=-^to{xcnfd_~M7)%*d%}rFzOjXT|fegKpijvR}UIzAg
z)11>_n2SLHsFZ<$kwJnXal!Kca?5TpqSL26&YnCOu5n)fl;=Yxh5&CyCJ_c)R_cOH
dLlBq_V1+n<7>fhES=k_tV`Rt%G77=w0sx8GJ7xd?

literal 0
HcmV?d00001

"""
    diff_file.write_text(diff_content)

    # Apply the binary patch
    result = challenge_task.apply_patch_diff(diff_file=diff_file)

    assert result is True
    assert base64.b64decode(exp_test_binary_content) == test_binary.read_bytes()


def test_apply_patch_diff_file_not_found(challenge_task: ChallengeTask):
    """Test applying a patch file that doesn't exist."""
    non_existent_diff = challenge_task.get_diff_path() / "nonexistent.diff"

    with pytest.raises(ChallengeTaskError, match="Diff file .* not found"):
        challenge_task.apply_patch_diff(diff_file=non_existent_diff)


def test_apply_patch_diff_git_apply_failure(challenge_task: ChallengeTask):
    """Test applying a patch file that causes git apply to fail."""
    # Create a test file
    test_file = challenge_task.get_source_path() / "test_file.txt"
    test_file.write_text("original content\n")

    # Create an invalid diff file
    diff_file = challenge_task.get_diff_path() / "invalid_patch.diff"
    diff_file.write_text("invalid diff content")

    # Mock subprocess to simulate git apply failure
    with patch("subprocess.run") as mock_run:
        # Simulate git apply failure
        mock_run.side_effect = subprocess.CalledProcessError(
            returncode=1, cmd=["patch", "-p1"], output="", stderr="patch does not apply"
        )

        with pytest.raises(ChallengeTaskError, match="Error applying diff"):
            challenge_task.apply_patch_diff(diff_file=diff_file)
