"""Integration tests for DebugSubagent that use real Docker execution.

These tests mock LLM responses but execute real Docker commands to verify
the Docker mounting and GDB execution works correctly.
"""

import logging
import stat
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest
from langchain_core.messages import AIMessage

from buttercup.common.challenge_task import ChallengeTask, CommandResult
from buttercup.common.datastructures.msg_pb2 import BuildOutput, BuildType
from buttercup.common.reproduce_multiple import ReproduceMultiple
from buttercup.seed_gen.debug_subagent import DebugSubagent, DebugTaskState
from buttercup.seed_gen.find_harness import HarnessInfo

# Set up logging to see what's happening
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@pytest.fixture
def simple_gdb_script():
    """A minimal GDB script that just prints some info."""
    return """# Simple GDB script for testing
set confirm off
set pagination off
echo \\n=== GDB Test Script ===\\n
info registers
echo \\n=== Script Complete ===\\n
quit
"""


@pytest.fixture
def minimal_binary(tmp_path):
    """Create a minimal ELF binary for testing (or use a system binary)."""
    # Use a system binary that exists in most containers
    # In real tests, you'd use an actual fuzzer binary
    test_binary = tmp_path / "test_binary"
    
    # Try to copy a simple binary from the system
    import shutil
    for binary_path in ["/bin/true", "/bin/false", "/bin/echo"]:
        if Path(binary_path).exists():
            shutil.copy(binary_path, test_binary)
            test_binary.chmod(0o755)
            return test_binary
    
    # Fallback: create a simple script
    test_binary.write_text("#!/bin/sh\necho test\n")
    test_binary.chmod(0o755)
    return test_binary


@pytest.fixture
def mock_task_with_real_docker(tmp_path):
    """Create a mock task that uses real Docker execution."""
    # Create a minimal challenge task structure
    task_dir = tmp_path / "task"
    task_dir.mkdir()
    
    # Create a real ChallengeTask (or mock it minimally)
    challenge_task = Mock(spec=ChallengeTask)
    challenge_task.task_dir = task_dir
    challenge_task.harness_name = "test_fuzzer"
    challenge_task.project_name = "test_project"
    
    # Make exec_docker_cmd actually run Docker
    def real_exec_docker_cmd(cmd, mount_dirs=None, container_image=None, **kwargs):
        """Execute real Docker command for testing."""
        import subprocess
        import shlex
        
        if container_image is None:
            container_image = "gcr.io/oss-fuzz-base/base-runner-debug"
        
        docker_cmd = ["docker", "run", "--privileged", "--shm-size=2g", "--rm"]
        
        if mount_dirs:
            for src, dst in mount_dirs.items():
                src_resolved = Path(src).resolve()
                if not src_resolved.exists():
                    return CommandResult(
                        success=False,
                        output=b"",
                        error=f"Mount source does not exist: {src_resolved}".encode(),
                        returncode=1,
                    )
                docker_cmd += ["-v", f"{src_resolved.as_posix()}:{dst.as_posix()}"]
        
        if isinstance(cmd, list):
            cmd_str = shlex.join(cmd)
        else:
            cmd_str = cmd
        
        docker_cmd += [container_image, "bash", "-c", cmd_str]
        
        logger.info(f"Executing Docker command: {' '.join(docker_cmd)}")
        
        try:
            result = subprocess.run(
                docker_cmd,
                capture_output=True,
                timeout=30,
                check=False,
            )
            return CommandResult(
                success=result.returncode == 0,
                output=result.stdout,
                error=result.stderr,
                returncode=result.returncode,
            )
        except subprocess.TimeoutExpired:
            return CommandResult(
                success=False,
                output=b"",
                error=b"Docker command timed out",
                returncode=124,
            )
        except Exception as e:
            return CommandResult(
                success=False,
                output=b"",
                error=str(e).encode(),
                returncode=1,
            )
    
    challenge_task.exec_docker_cmd = real_exec_docker_cmd
    challenge_task.get_build_dir = Mock(return_value=tmp_path / "build" / "out")
    
    # Create mock task
    mock_task = Mock()
    mock_task.challenge_task = challenge_task
    mock_task.harness_name = "test_fuzzer"
    mock_task.llm = Mock()
    mock_task.tools = []
    mock_task.codequery = Mock()
    
    return mock_task


@pytest.fixture
def real_reproduce_multiple(mock_task_with_real_docker, tmp_path):
    """Create a ReproduceMultiple with real build directory."""
    build_output = BuildOutput()
    build_output.task_dir = str(mock_task_with_real_docker.challenge_task.task_dir)
    build_output.build_type = BuildType.FUZZER
    build_output.engine = "libfuzzer"
    build_output.sanitizer = "address"
    
    reproduce_multiple = ReproduceMultiple(tmp_path, [build_output])
    
    # Set up the build directory
    build_dir = tmp_path / "build" / "out"
    build_dir.mkdir(parents=True)
    
    # Create a test binary in the build directory
    test_binary = build_dir / "test_fuzzer"
    import shutil
    for binary_path in ["/bin/true", "/bin/false"]:
        if Path(binary_path).exists():
            shutil.copy(binary_path, test_binary)
            test_binary.chmod(0o755)
            break
    
    with patch.object(reproduce_multiple, "open") as mock_open:
        mock_context = MagicMock()
        mock_context.builds_cache = [mock_task_with_real_docker.challenge_task]
        mock_context.get_crashes = Mock(return_value=iter([]))
        mock_open.return_value.__enter__.return_value = mock_context
        mock_open.return_value.__exit__.return_value = None
        yield reproduce_multiple


@pytest.mark.integration
def test_docker_mount_verification(mock_task_with_real_docker, tmp_path):
    """Test that Docker can mount files correctly."""
    # Create test files
    test_file = tmp_path / "test.txt"
    test_file.write_text("hello world")
    
    mount_dirs = {
        test_file: Path("/tmp/test.txt"),
    }
    
    result = mock_task_with_real_docker.challenge_task.exec_docker_cmd(
        ["cat", "/tmp/test.txt"],
        mount_dirs=mount_dirs,
        container_image="gcr.io/oss-fuzz-base/base-runner-debug",
    )
    
    assert result.success, f"Docker mount failed: {result.error.decode()}"
    assert b"hello world" in result.output, "File content not found in output"


@pytest.mark.integration
def test_gdb_script_execution_direct(
    mock_task_with_real_docker,
    simple_gdb_script,
    minimal_binary,
    tmp_path,
):
    """Test executing a GDB script directly via Docker (bypassing DebugSubagent)."""
    # Write GDB script to temp file
    with tempfile.NamedTemporaryFile(mode="w", suffix=".gdb", delete=False) as f:
        f.write(simple_gdb_script)
        f.flush()
        script_path = Path(f.name)
    
    try:
        # Create a simple input file
        input_file = tmp_path / "input.bin"
        input_file.write_bytes(b"test input")
        
        # Mount files
        mount_dirs = {
            script_path: Path("/tmp/debug_script.gdb"),
            input_file: Path("/tmp/input.bin"),
            minimal_binary.parent: Path("/out"),
        }
        
        # Run GDB
        gdb_cmd = [
            "gdb",
            "-batch",
            "-x",
            "/tmp/debug_script.gdb",
            "--args",
            f"/out/{minimal_binary.name}",
            "/tmp/input.bin",
        ]
        
        result = mock_task_with_real_docker.challenge_task.exec_docker_cmd(
            gdb_cmd,
            mount_dirs=mount_dirs,
            container_image="gcr.io/oss-fuzz-base/base-runner-debug",
        )
        
        logger.info(f"GDB stdout: {result.output.decode('utf-8', errors='ignore')}")
        logger.info(f"GDB stderr: {result.error.decode('utf-8', errors='ignore')}")
        logger.info(f"GDB return code: {result.returncode}")
        
        # GDB might return non-zero even on success, so check for expected output
        output = result.output.decode("utf-8", errors="ignore")
        assert "GDB Test Script" in output or "Script Complete" in output or len(output) > 50, (
            f"GDB didn't produce expected output. Output: {output[:500]}"
        )
        
    finally:
        # Clean up
        if script_path.exists():
            script_path.unlink()


@pytest.mark.integration
def test_debug_subagent_execute_script(
    mock_task_with_real_docker,
    real_reproduce_multiple,
    simple_gdb_script,
    tmp_path,
):
    """Test _execute_debug_script method directly with real Docker."""
    debug_subagent = DebugSubagent(
        mock_task_with_real_docker,
        real_reproduce_multiple,
        skip_validation=True,
    )
    
    # Create GDB script file
    with tempfile.NamedTemporaryFile(mode="w", suffix=".gdb", delete=False) as f:
        f.write(simple_gdb_script)
        f.flush()
        script_path = Path(f.name)
    
    # Create PoV input
    pov_input = tmp_path / "pov.bin"
    pov_input.write_bytes(b"test pov input")
    
    try:
        # Call _execute_debug_script directly
        output = debug_subagent._execute_debug_script(script_path, pov_input)
        
        logger.info(f"Debug output: {output[:500]}")
        
        # Check that we got some output
        assert len(output) > 50, f"Expected substantial output, got: {output}"
        assert "GDB" in output or "Script" in output or "registers" in output.lower(), (
            f"Expected GDB output, got: {output[:500]}"
        )
        
    finally:
        if script_path.exists():
            script_path.unlink()


@pytest.mark.integration
def test_debug_subagent_full_workflow_mocked_llm(
    mock_task_with_real_docker,
    real_reproduce_multiple,
    tmp_path,
):
    """Test full debug workflow with mocked LLM but real Docker."""
    debug_subagent = DebugSubagent(
        mock_task_with_real_docker,
        real_reproduce_multiple,
        skip_validation=True,
    )
    
    # Create PoV input
    pov_input = tmp_path / "pov.bin"
    pov_input.write_bytes(b"test input data")
    
    # Mock LLM responses
    simple_analysis = "This is a test analysis of the debugging task."
    simple_gdb_script = """# Test GDB script
set confirm off
set pagination off
echo \\n=== Debug Script ===\\n
info registers
echo \\n=== Done ===\\n
quit
"""
    
    # Patch LLM to return our canned responses
    def mock_llm_invoke(prompt_vars):
        if "analysis" in str(prompt_vars.get("prompt", "")):
            return AIMessage(content=simple_analysis)
        elif "debug_script" in str(prompt_vars.get("prompt", "")):
            return AIMessage(content=f"```gdb\n{simple_gdb_script}\n```")
        return AIMessage(content="No match")
    
    mock_task_with_real_docker.llm.invoke = Mock(side_effect=mock_llm_invoke)
    
    # Mock context retrieval to skip it
    debug_subagent._get_context = Mock(return_value=None)
    mock_task_with_real_docker._continue_context_retrieval = Mock(return_value=False)
    
    # Run debug
    result = debug_subagent.debug(
        harness=HarnessInfo(name="test_fuzzer", source_path=Path("/src/test.cc")),
        pov_input_path=pov_input,
        debug_context="Test debugging scenario",
        output_dir=tmp_path / "debug_output",
    )
    
    # Verify results
    assert result is not None
    assert len(result.debug_output) > 0, "Expected debug output"
    logger.info(f"Debug result: pov_valid={result.pov_valid}, output_len={len(result.debug_output)}")


def test_docker_file_mount_debugging(tmp_path):
    """Helper test to debug Docker file mounting issues.
    
    This test verifies that Docker can mount files correctly. The test uses
    a parent directory mount approach which is more reliable than mounting
    individual files directly (which can fail if the target path exists as
    a directory in the container).
    
    Note: The actual debug_subagent mounts individual files, which works in
    practice because it uses unique paths like /tmp/debug_script.gdb that
    don't exist in the container.
    """
    import subprocess
    import tempfile
    
    # Use /tmp directly instead of pytest's tmp_path to avoid potential
    # Docker volume mount issues with pytest's temporary directories
    with tempfile.TemporaryDirectory(dir="/tmp", prefix="docker_test_") as test_dir:
        test_dir_path = Path(test_dir)
        test_file = test_dir_path / "test.txt"
        test_file.write_text("test content")
    
    # Force sync to ensure file is written to disk before mounting
    import os
    with test_file.open('r+b') as f:
        os.fsync(f.fileno())
    
    # Also sync the parent directory to ensure metadata is written
    dir_fd = os.open(str(tmp_path), os.O_RDONLY)
    try:
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)
    
    # Verify file exists and is actually a file using system commands
    import subprocess as sp
    ls_result = sp.run(["ls", "-la", str(tmp_path)], capture_output=True, text=True)
    logger.info(f"Host ls output: {ls_result.stdout}")
    
    # Verify file exists and is actually a file
    assert test_file.exists(), "Test file should exist"
    assert test_file.is_file(), "Test file should be a file, not directory"
    assert not test_file.is_dir(), "Test file should not be a directory"
    
    # Double-check file is readable
    content = test_file.read_text()
    assert content == "test content", f"File content mismatch. Got: {content!r}"
    
        # Mount parent directory (more reliable approach)
        # This is what we'd use if individual file mounts were problematic
        mount_source = test_dir_path.resolve().as_posix()
        logger.info(f"Mounting directory: {mount_source}")
        logger.info(f"Files in source directory (Python): {list(test_dir_path.iterdir())}")
        logger.info(f"Test file absolute path: {test_file.resolve()}")
        logger.info(f"Test file exists: {test_file.exists()}, is_file: {test_file.is_file()}")
    
        # First, verify the mount works by listing the directory
        docker_cmd_ls = [
            "docker", "run", "--rm",
            "-v", f"{mount_source}:/mnt/test_dir",
            "gcr.io/oss-fuzz-base/base-runner-debug",
            "ls", "-la", "/mnt/test_dir",
        ]
        
        logger.info(f"Testing directory listing: {' '.join(docker_cmd_ls)}")
        try:
            result_ls = subprocess.run(docker_cmd_ls, capture_output=True, timeout=30)
        except subprocess.TimeoutExpired:
            pytest.skip("Docker command timed out - image may need to be pulled or Docker may be slow")
            return
        
        logger.info(f"LS Return code: {result_ls.returncode}")
        logger.info(f"LS Stdout: {result_ls.stdout.decode('utf-8', errors='ignore')}")
        if result_ls.stderr:
            logger.info(f"LS Stderr: {result_ls.stderr.decode('utf-8', errors='ignore')}")
        
        # Check if Docker is working at all
        if result_ls.returncode != 0:
            if b"Unable to find image" in result_ls.stderr:
                pytest.skip("Docker image not available - run: docker pull gcr.io/oss-fuzz-base/base-runner-debug")
                return
            # If listing fails, the mount might not be working
            pytest.fail(
                f"Directory listing failed. This suggests the mount isn't working. "
                f"Stderr: {result_ls.stderr.decode('utf-8', errors='ignore')}"
            )
        
        # Check if the file appears in the mounted directory
        ls_output = result_ls.stdout.decode('utf-8', errors='ignore')
        if 'test.txt' not in ls_output:
            # File is not visible in the mounted directory
            # This could be a Docker volume mount issue or filesystem sync problem
            pytest.fail(
                f"File 'test.txt' not found in mounted directory. "
                f"Directory listing: {ls_output}. "
                f"Host directory contents: {list(test_dir_path.iterdir())}. "
                f"This suggests a Docker volume mount issue - the file exists on host but not in container."
            )
        
        # Now try to read the file
        docker_cmd = [
            "docker", "run", "--rm",
            "-v", f"{mount_source}:/mnt/test_dir",
            "gcr.io/oss-fuzz-base/base-runner-debug",
            "cat", "/mnt/test_dir/test.txt",
        ]
        
        logger.info(f"Testing file read: {' '.join(docker_cmd)}")
        
        try:
            result = subprocess.run(docker_cmd, capture_output=True, timeout=30)
        except subprocess.TimeoutExpired:
            pytest.skip("Docker command timed out - image may need to be pulled or Docker may be slow")
            return
        
        logger.info(f"Return code: {result.returncode}")
        logger.info(f"Stdout: {result.stdout.decode('utf-8', errors='ignore')}")
        if result.stderr:
            logger.info(f"Stderr: {result.stderr.decode('utf-8', errors='ignore')}")
        
        # The test should pass
        assert result.returncode == 0, (
            f"Docker command failed with return code {result.returncode}. "
            f"Stderr: {result.stderr.decode('utf-8', errors='ignore')}. "
            f"Directory listing showed: {result_ls.stdout.decode('utf-8', errors='ignore')}"
        )
        assert b"test content" in result.stdout, (
            f"File content not found. Got: {result.stdout.decode('utf-8', errors='ignore')[:100]}"
        )


if __name__ == "__main__":
    # Run with: python -m pytest seed-gen/test/test_debug_subagent_integration.py -v -s
    pytest.main([__file__, "-v", "-s"])

