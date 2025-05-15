from unittest.mock import MagicMock, patch
from pathlib import Path
import pytest
from buttercup.common.reproduce_multiple import ReproduceMultiple
from buttercup.common.datastructures.msg_pb2 import BuildOutput
from buttercup.common.challenge_task import ReproduceResult, CommandResult


@pytest.fixture
def build_outputs():
    return [
        BuildOutput(task_dir="/path/to/task1"),
        BuildOutput(task_dir="/path/to/task2"),
    ]


VALID_STDOUT = b"""
INFO: Running with entropic power schedule (0xFF, 100).
INFO: Seed: 954068278
INFO: Loaded 1 modules   (6849 inline 8-bit counters): 6849 [0x561a974abfe8, 0x561a974adaa9), 
INFO: Loaded 1 PC tables (6849 PCs): 6849 [0x561a974adab0,0x561a974c86c0), 
/out/libpng_read_fuzzer: Running 1 inputs 100 time(s) each.
Running: /testcase
DEBUG - pngrutil.c:1447:10: runtime error: 
"""

INVALID_STDOUT = b"""
Unable to find image \'ghcr.io/aixcc-finals/base-runner:v1.0.0\' locally
docker: Error response from daemon: Get "https://ghcr.io/v2/": net/http: request canceled while waiting for connection (Client.Timeout exceeded while awaiting headers)

Run \'docker run --help\' for more information
ERROR:__main__:libpng_read_fuzzer does not seem to exist. Please run build_fuzzers first.
"""


@pytest.fixture
def mock_challenge_task():
    with patch("buttercup.common.reproduce_multiple.ChallengeTask") as mock:
        # Setup the mock ChallengeTask
        task_instance = MagicMock()

        task_instance.reproduce_pov.side_effect = [
            ReproduceResult(command_result=CommandResult(success=False, returncode=1, output=VALID_STDOUT, error=None)),
            ReproduceResult(command_result=CommandResult(success=True, returncode=0, output=b"SUCCESS", error=None)),
        ]

        mock.get_rw_copy.return_value.__enter__.return_value = task_instance
        task_instance.get_rw_copy.return_value.__enter__.return_value = task_instance
        mock.return_value = task_instance
        yield mock


def test_mock_challenge_task(mock_challenge_task):
    with mock_challenge_task.get_rw_copy() as task:
        print(task.reproduce_pov.side_effect)
        assert not task.reproduce_pov("a").command_result.success


def test_reproduce_multiple_open_and_reproduce(build_outputs, mock_challenge_task):
    work_dir = Path("/tmp/workdir")
    repro_multiple = ReproduceMultiple(work_dir, build_outputs)

    # Test the context manager
    with repro_multiple.open() as rm:
        # Verify ChallengeTask was created for each build
        assert mock_challenge_task.call_count == len(build_outputs)

        # Test reproduce with a POV
        pov_path = Path("/path/to/pov")
        harness_name = "test_harness"

        # Get first crash
        result = rm.get_first_crash(pov_path, harness_name)

        # Verify we got a result and it's from the first task (which was set to crash)
        assert result is not None
        build_output, reproduce_result = result
        assert build_output.task_dir == "/path/to/task1"
        assert reproduce_result.did_crash()
        assert reproduce_result.stacktrace() == VALID_STDOUT.decode(encoding="utf-8")


def test_reproduce_fail_reproduce(build_outputs, mock_challenge_task):
    work_dir = Path("/tmp/workdir")
    repro_multiple = ReproduceMultiple(work_dir, build_outputs)

    # Override the mock to return no crashes
    task_instance = mock_challenge_task.return_value
    task_instance.reproduce_pov.side_effect = [
        ReproduceResult(command_result=CommandResult(success=False, returncode=1, output=INVALID_STDOUT, error=None)),
    ]

    with repro_multiple.open() as rm:
        pov_path = Path("/path/to/pov")
        harness_name = "test_harness"

        _, result = next(rm.attempt_reproduce(pov_path, harness_name))
        assert result.did_run() is False
        assert result.did_crash() is False


def test_reproduce_multiple_no_crashes(build_outputs, mock_challenge_task):
    work_dir = Path("/tmp/workdir")
    repro_multiple = ReproduceMultiple(work_dir, build_outputs)

    # Override the mock to return no crashes
    task_instance = mock_challenge_task.return_value
    task_instance.reproduce_pov.side_effect = [
        ReproduceResult(command_result=CommandResult(success=True, returncode=0, output=b"SUCCESS", error=None)),
        ReproduceResult(command_result=CommandResult(success=True, returncode=0, output=b"SUCCESS", error=None)),
    ]

    with repro_multiple.open() as rm:
        pov_path = Path("/path/to/pov")
        harness_name = "test_harness"

        # Get first crash should return None when no crashes occur
        result = rm.get_first_crash(pov_path, harness_name)
        assert result is None


def test_reproduce_multiple_without_open():
    work_dir = Path("/tmp/workdir")
    repro_multiple = ReproduceMultiple(work_dir, [])

    # Attempting to use reproduce without opening should raise an error
    with pytest.raises(RuntimeError, match="Build cache is not populated"):
        next(repro_multiple.attempt_reproduce(Path("/path/to/pov"), "test_harness"))
