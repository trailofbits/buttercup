import time
from unittest.mock import Mock, patch

import httpx
import pytest

from buttercup.common.types import FuzzConfiguration
from buttercup.fuzzing_infra.runner_proxy import Conf, Crash, FuzzResult, RunnerProxy


@pytest.fixture
def fuzz_config():
    return FuzzConfiguration(
        corpus_dir="/path/to/corpus", target_path="/path/to/target", engine="libfuzzer", sanitizer="address"
    )


@patch("buttercup.fuzzing_infra.runner_proxy.httpx.Client")
def test_run_fuzzer_success(mock_client_class, fuzz_config):
    """Test successful fuzzer execution via HTTP"""
    # Setup mock client
    mock_client = Mock()
    mock_client_class.return_value = mock_client

    # Create runner proxy after mocking
    conf = Conf(
        timeout=100,
        server_url="http://localhost:8000",
        poll_interval=0.1,
        timeout_buffer=5.0,  # 5 second buffer for testing
    )
    runner_proxy = RunnerProxy(conf)

    # Mock the start task response
    start_response = Mock()
    start_response.json.return_value = {"task_id": "test-task-123", "status": "running"}
    start_response.raise_for_status.return_value = None

    # Mock the status check responses
    status_response = Mock()
    status_response.json.return_value = {
        "task_id": "test-task-123",
        "type": "fuzz",
        "status": "completed",
        "result": {
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
        },
    }
    status_response.raise_for_status.return_value = None

    # Configure mock to return different responses for different calls
    mock_client.post.return_value = start_response
    mock_client.get.return_value = status_response

    # Run fuzzer
    result = runner_proxy.run_fuzzer(fuzz_config)

    # Verify HTTP calls were made
    mock_client.post.assert_called_once_with(
        "http://localhost:8000/fuzz",
        json={
            "corpus_dir": "/path/to/corpus",
            "target_path": "/path/to/target",
            "engine": "libfuzzer",
            "sanitizer": "address",
            "timeout": 100,
        },
    )

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


@patch("buttercup.fuzzing_infra.runner_proxy.httpx.Client")
def test_run_fuzzer_failure(mock_client_class, fuzz_config):
    """Test fuzzer execution failure via HTTP"""
    # Setup mock client
    mock_client = Mock()
    mock_client_class.return_value = mock_client

    # Create runner proxy after mocking
    conf = Conf(
        timeout=100,
        server_url="http://localhost:8000",
        poll_interval=0.1,
        timeout_buffer=5.0,  # 5 second buffer for testing
    )
    runner_proxy = RunnerProxy(conf)

    # Mock the start task response
    start_response = Mock()
    start_response.json.return_value = {"task_id": "test-task-123", "status": "running"}
    start_response.raise_for_status.return_value = None

    # Mock the status check response with failure
    status_response = Mock()
    status_response.json.return_value = {
        "task_id": "test-task-123",
        "type": "fuzz",
        "status": "failed",
        "error": "Fuzzer crashed",
    }
    status_response.raise_for_status.return_value = None

    mock_client.post.return_value = start_response
    mock_client.get.return_value = status_response

    # Run fuzzer and expect failure
    with pytest.raises(RuntimeError, match="Task failed: Fuzzer crashed"):
        runner_proxy.run_fuzzer(fuzz_config)


@patch("buttercup.fuzzing_infra.runner_proxy.httpx.Client")
def test_run_fuzzer_timeout(mock_client_class, fuzz_config):
    """Test fuzzer execution timeout"""
    # Setup mock client
    mock_client = Mock()
    mock_client_class.return_value = mock_client

    # Create runner proxy after mocking with very short timeouts for testing
    conf = Conf(
        timeout=1,  # 1 second timeout
        server_url="http://localhost:8000",
        poll_interval=0.1,
        timeout_buffer=0.5,  # 0.5 second buffer for testing
    )
    runner_proxy = RunnerProxy(conf)

    # Mock the start task response
    start_response = Mock()
    start_response.json.return_value = {"task_id": "test-task-123", "status": "running"}
    start_response.raise_for_status.return_value = None

    # Mock the status check response to always return "running"
    status_response = Mock()
    status_response.json.return_value = {"task_id": "test-task-123", "type": "fuzz", "status": "running"}
    status_response.raise_for_status.return_value = None

    mock_client.post.return_value = start_response
    mock_client.get.return_value = status_response

    # Run fuzzer and expect timeout
    # With timeout=1 and buffer=0.5, max wait time is 1.5 seconds
    start_time = time.time()
    with pytest.raises(RuntimeError, match="Task timeout"):
        runner_proxy.run_fuzzer(fuzz_config)

    # Verify it didn't take too long (should timeout quickly in test environment)
    elapsed = time.time() - start_time
    assert elapsed < 3.0  # Should timeout within 3 seconds


@patch("buttercup.fuzzing_infra.runner_proxy.httpx.Client")
def test_merge_corpus_success(mock_client_class, fuzz_config):
    """Test successful corpus merge via HTTP"""
    # Setup mock client
    mock_client = Mock()
    mock_client_class.return_value = mock_client

    # Create runner proxy after mocking
    conf = Conf(
        timeout=100,
        server_url="http://localhost:8000",
        poll_interval=0.1,
        timeout_buffer=5.0,  # 5 second buffer for testing
    )
    runner_proxy = RunnerProxy(conf)

    # Mock the start task response
    start_response = Mock()
    start_response.json.return_value = {"task_id": "test-task-456", "status": "running"}
    start_response.raise_for_status.return_value = None

    # Mock the status check response
    status_response = Mock()
    status_response.json.return_value = {"task_id": "test-task-456", "type": "merge_corpus", "status": "completed"}
    status_response.raise_for_status.return_value = None

    mock_client.post.return_value = start_response
    mock_client.get.return_value = status_response

    # Run merge corpus
    runner_proxy.merge_corpus(fuzz_config, "/path/to/output")

    # Verify HTTP calls were made
    mock_client.post.assert_called_once_with(
        "http://localhost:8000/merge-corpus",
        json={
            "corpus_dir": "/path/to/corpus",
            "target_path": "/path/to/target",
            "engine": "libfuzzer",
            "sanitizer": "address",
            "output_dir": "/path/to/output",
            "timeout": 100,
        },
    )


@patch("buttercup.fuzzing_infra.runner_proxy.httpx.Client")
def test_http_error_handling(mock_client_class, fuzz_config):
    """Test HTTP error handling"""
    # Setup mock client to raise HTTP error
    mock_client = Mock()
    mock_client_class.return_value = mock_client

    # Create runner proxy after mocking
    conf = Conf(
        timeout=100,
        server_url="http://localhost:8000",
        poll_interval=0.1,
        timeout_buffer=5.0,  # 5 second buffer for testing
    )
    runner_proxy = RunnerProxy(conf)

    # Mock HTTP error - use httpx.ConnectError to match the actual error
    mock_client.post.side_effect = httpx.ConnectError("[Errno 61] Connection refused")

    # Run fuzzer and expect error
    with pytest.raises(httpx.ConnectError, match="\\[Errno 61\\] Connection refused"):
        runner_proxy.run_fuzzer(fuzz_config)


def test_runner_proxy_cleanup():
    """Test that HTTP client is properly cleaned up"""
    conf = Conf(timeout=100)
    proxy = RunnerProxy(conf)

    # Verify client exists
    assert hasattr(proxy, "client")
    assert proxy.client is not None

    # Test cleanup
    proxy.__del__()
    # Note: We can't easily test if the client was actually closed in a unit test
    # but we can verify the method exists and doesn't crash


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
    conf = Conf(timeout=60)

    assert conf.timeout == 60
    assert conf.server_url == "http://localhost:8000"
    assert conf.poll_interval == 1.0
    assert conf.timeout_buffer == 60.0
