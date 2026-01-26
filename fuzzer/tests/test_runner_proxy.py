import json
import subprocess
import time
from unittest.mock import Mock, patch

import pytest
from buttercup.common.types import FuzzConfiguration

from buttercup.fuzzing_infra.runner_proxy import Conf, Crash, FuzzResult, RunnerProxy


@pytest.fixture
def fuzz_config():
    return FuzzConfiguration(
        corpus_dir="/path/to/corpus", target_path="/path/to/target", engine="libfuzzer", sanitizer="address"
    )


@patch("buttercup.fuzzing_infra.runner_proxy.subprocess.Popen")
def test_run_fuzzer_success(mock_popen, fuzz_config):
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
    mock_process = Mock()
    mock_process.communicate.return_value = (json.dumps(mock_result).encode(), b"")
    mock_process.returncode = 0
    mock_process.pid = 12345
    mock_popen.return_value = mock_process

    # Run fuzzer
    result = runner_proxy.run_fuzzer(fuzz_config)

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
    mock_popen.assert_called_once()
    call_args = mock_popen.call_args[0][0]  # First positional argument (cmd)
    assert call_args == expected_cmd

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


@patch("buttercup.fuzzing_infra.runner_proxy.subprocess.Popen")
def test_run_fuzzer_failure(mock_popen, fuzz_config):
    """Test fuzzer execution failure via subprocess"""
    # Create runner proxy
    conf = Conf(
        timeout=100,
        runner_path="/path/to/runner",
    )
    runner_proxy = RunnerProxy(conf)

    # Mock the subprocess to return non-zero exit code
    mock_process = Mock()
    mock_process.communicate.return_value = (b"", b"Fuzzer crashed")
    mock_process.returncode = 1
    mock_process.pid = 12345
    mock_popen.return_value = mock_process

    # Run fuzzer and expect failure
    res = runner_proxy.run_fuzzer(fuzz_config)
    assert "Task failed (exit code 1): Fuzzer crashed" in res.logs
    assert res.crashes == []
    assert res.command == ""


@patch("buttercup.fuzzing_infra.runner_proxy.subprocess.Popen")
def test_run_fuzzer_timeout(mock_popen, fuzz_config):
    """Test fuzzer execution timeout"""
    # Create runner proxy with very short timeout for testing
    conf = Conf(
        timeout=1,  # 1 second timeout
        runner_path="/path/to/runner",
    )
    runner_proxy = RunnerProxy(conf)

    # Mock the subprocess to timeout
    mock_process = Mock()
    mock_process.communicate.side_effect = subprocess.TimeoutExpired("test", 1)
    mock_process.returncode = None
    mock_process.poll.return_value = None
    mock_process.pid = 12345
    mock_popen.return_value = mock_process

    # Run fuzzer and expect timeout
    start_time = time.time()
    res = runner_proxy.run_fuzzer(fuzz_config)

    assert "Task timed out" in res.logs
    assert res.crashes == []
    assert res.command == ""

    # Verify it didn't take too long (should timeout quickly in test environment)
    elapsed = time.time() - start_time
    assert elapsed < 3.0  # Should timeout within 3 seconds


@patch("buttercup.fuzzing_infra.runner_proxy.subprocess.Popen")
def test_merge_corpus_success(mock_popen, fuzz_config):
    """Test successful corpus merge via subprocess"""
    # Create runner proxy
    conf = Conf(
        timeout=100,
        runner_path="/path/to/runner",
    )
    runner_proxy = RunnerProxy(conf)

    # Mock the subprocess
    mock_process = Mock()
    mock_process.communicate.return_value = (b"", b"")
    mock_process.returncode = 0
    mock_process.pid = 12345
    mock_popen.return_value = mock_process

    # Run merge corpus
    runner_proxy.merge_corpus(fuzz_config, "/path/to/output")

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
    mock_popen.assert_called_once()
    call_args = mock_popen.call_args[0][0]  # First positional argument (cmd)
    assert call_args == expected_cmd


@patch("buttercup.fuzzing_infra.runner_proxy.subprocess.Popen")
def test_subprocess_error_handling(mock_popen, fuzz_config):
    """Test subprocess error handling"""
    # Create runner proxy
    conf = Conf(
        timeout=100,
        runner_path="/path/to/runner",
    )
    runner_proxy = RunnerProxy(conf)

    # Mock subprocess to raise an exception
    mock_popen.side_effect = FileNotFoundError("Runner not found")

    # Run fuzzer and expect error
    res = runner_proxy.run_fuzzer(fuzz_config)
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
