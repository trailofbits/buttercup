import json
import time
from unittest.mock import AsyncMock, patch

import pytest

from buttercup.common.types import FuzzConfiguration
from buttercup.fuzzing_infra.runner_proxy import Conf, Crash, FuzzResult, RunnerProxy


@pytest.fixture
def fuzz_config():
    return FuzzConfiguration(
        corpus_dir="/path/to/corpus", target_path="/path/to/target", engine="libfuzzer", sanitizer="address"
    )


@patch("buttercup.fuzzing_infra.runner_proxy.asyncio.create_subprocess_exec")
@pytest.mark.asyncio
async def test_run_fuzzer_success(mock_create_subprocess, fuzz_config):
    """Test successful fuzzer execution via subprocess"""
    # Create runner proxy
    conf = Conf(
        timeout=100,
        runner_path="/path/to/runner",
    )
    runner_proxy = RunnerProxy(conf)

    # Mock subprocess result
    mock_result = {
        "logs": "test logs",
        "crashes": [
            {
                "input_path": "input1",
                "stacktrace": "stacktrace1",
                "reproduce_args": ["arg1", "arg2"],
                "crash_time": 1.0,
            }
        ],
        "stats": {"execs_per_sec": 1000},
        "time_executed": 10.0,
        "timed_out": False,
        "command": "test command",
    }

    # Mock the subprocess
    mock_process = AsyncMock()
    mock_process.communicate.return_value = (json.dumps(mock_result).encode(), b"")
    mock_process.returncode = 0
    mock_create_subprocess.return_value = mock_process

    # Run fuzzer
    result = await runner_proxy.run_fuzzer(fuzz_config)

    # Verify subprocess was called with correct arguments
    expected_cmd = [
        "/path/to/runner",
        "--timeout",
        "100",
        "--corpusdir",
        "/path/to/corpus",
        "--engine",
        "libfuzzer",
        "--sanitizer",
        "address",
        "/path/to/target",
        "fuzz",
    ]
    mock_create_subprocess.assert_called_once()
    call_args = mock_create_subprocess.call_args[0]
    assert call_args == tuple(expected_cmd)

    # Verify result is a FuzzResult instance
    assert isinstance(result, FuzzResult)
    assert result.logs == "test logs"
    assert result.crashes == [
        Crash(
            input_path="input1",
            stacktrace="stacktrace1",
            reproduce_args=["arg1", "arg2"],
            crash_time=1.0,
        ),
    ]
    assert result.stats == {"execs_per_sec": 1000}
    assert result.time_executed == 10.0
    assert not result.timed_out
    assert result.command == "test command"


@patch("buttercup.fuzzing_infra.runner_proxy.asyncio.create_subprocess_exec")
@pytest.mark.asyncio
async def test_run_fuzzer_failure(mock_create_subprocess, fuzz_config):
    """Test fuzzer execution failure via subprocess"""
    # Create runner proxy
    conf = Conf(
        timeout=100,
        runner_path="/path/to/runner",
    )
    runner_proxy = RunnerProxy(conf)

    # Mock the subprocess to return non-zero exit code
    mock_process = AsyncMock()
    mock_process.communicate.return_value = (b"", b"Fuzzer crashed")
    mock_process.returncode = 1
    mock_create_subprocess.return_value = mock_process

    # Run fuzzer and expect failure
    res = await runner_proxy.run_fuzzer(fuzz_config)
    assert "Task failed: Fuzzer crashed" in res.logs
    assert res.crashes == []
    assert res.command == ""


@patch("buttercup.fuzzing_infra.runner_proxy.asyncio.create_subprocess_exec")
@pytest.mark.asyncio
async def test_run_fuzzer_timeout(mock_create_subprocess, fuzz_config):
    """Test fuzzer execution timeout"""
    # Create runner proxy with very short timeout for testing
    conf = Conf(
        timeout=1,  # 1 second timeout
        runner_path="/path/to/runner",
    )
    runner_proxy = RunnerProxy(conf)

    # Mock the subprocess to timeout
    mock_process = AsyncMock()
    mock_process.communicate.side_effect = TimeoutError()
    mock_process.returncode = None
    mock_create_subprocess.return_value = mock_process

    # Run fuzzer and expect timeout
    start_time = time.time()
    res = await runner_proxy.run_fuzzer(fuzz_config)

    assert "Task timed out" in res.logs
    assert res.crashes == []
    assert res.command == ""

    # Verify it didn't take too long (should timeout quickly in test environment)
    elapsed = time.time() - start_time
    assert elapsed < 3.0  # Should timeout within 3 seconds


@patch("buttercup.fuzzing_infra.runner_proxy.asyncio.create_subprocess_exec")
@pytest.mark.asyncio
async def test_merge_corpus_success(mock_create_subprocess, fuzz_config):
    """Test successful corpus merge via subprocess"""
    # Create runner proxy
    conf = Conf(
        timeout=100,
        runner_path="/path/to/runner",
    )
    runner_proxy = RunnerProxy(conf)

    # Mock the subprocess
    mock_process = AsyncMock()
    mock_process.communicate.return_value = (b"", b"")
    mock_process.returncode = 0
    mock_create_subprocess.return_value = mock_process

    # Run merge corpus
    await runner_proxy.merge_corpus(fuzz_config, "/path/to/output")

    # Verify subprocess was called with correct arguments
    expected_cmd = [
        "/path/to/runner",
        "--timeout",
        "100",
        "--corpusdir",
        "/path/to/corpus",
        "--engine",
        "libfuzzer",
        "--sanitizer",
        "address",
        "/path/to/target",
        "merge",
        "--output-dir",
        "/path/to/output",
    ]
    mock_create_subprocess.assert_called_once()
    call_args = mock_create_subprocess.call_args[0]
    assert call_args == tuple(expected_cmd)


@patch("buttercup.fuzzing_infra.runner_proxy.asyncio.create_subprocess_exec")
@pytest.mark.asyncio
async def test_subprocess_error_handling(mock_create_subprocess, fuzz_config):
    """Test subprocess error handling"""
    # Create runner proxy
    conf = Conf(
        timeout=100,
        runner_path="/path/to/runner",
    )
    runner_proxy = RunnerProxy(conf)

    # Mock subprocess to raise an exception
    mock_create_subprocess.side_effect = FileNotFoundError("Runner not found")

    # Run fuzzer and expect error
    res = await runner_proxy.run_fuzzer(fuzz_config)
    assert "Runner not found" in res.logs
    assert res.crashes == []
    assert res.command == ""


def test_runner_proxy_initialization():
    """Test that RunnerProxy initializes correctly"""
    conf = Conf(timeout=100, runner_path="/path/to/runner")
    proxy = RunnerProxy(conf)

    # Verify configuration is set correctly
    assert proxy.conf.timeout == 100
    assert proxy.conf.runner_path == "/path/to/runner"
    assert proxy._timeout == 5  # Default internal timeout


def test_fuzz_result_creation():
    """Test FuzzResult dataclass creation"""
    result = FuzzResult(
        logs="test logs",
        command="fuzzer command",
        crashes=[
            Crash(
                input_path="input1",
                stacktrace="stacktrace1",
                reproduce_args=["arg1", "arg2"],
                crash_time=1.0,
            ),
            Crash(
                input_path="input2",
                stacktrace="stacktrace2",
                reproduce_args=["arg3", "arg4"],
                crash_time=2.0,
            ),
        ],
        stats={"execs_per_sec": 1000},
        time_executed=5.5,
        timed_out=False,
    )

    assert result.logs == "test logs"
    assert result.crashes == [
        Crash(
            input_path="input1",
            stacktrace="stacktrace1",
            reproduce_args=["arg1", "arg2"],
            crash_time=1.0,
        ),
        Crash(
            input_path="input2",
            stacktrace="stacktrace2",
            reproduce_args=["arg3", "arg4"],
            crash_time=2.0,
        ),
    ]
    assert result.stats == {"execs_per_sec": 1000}
    assert result.time_executed == 5.5
    assert not result.timed_out
    assert result.command == "fuzzer command"


def test_conf_defaults():
    """Test Conf dataclass default values"""
    from pathlib import Path

    conf = Conf(timeout=60, runner_path=Path("/path/to/runner"))

    assert conf.timeout == 60
    assert conf.runner_path == Path("/path/to/runner")
