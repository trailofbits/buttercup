import pytest
import os
import tempfile
from unittest.mock import patch, MagicMock
from redis import Redis
from buttercup.fuzzing_infra.coverage_bot import CoverageBot
from buttercup.fuzzing_infra.coverage_runner import CoveredFunction
from buttercup.common.maps import CoverageMap
from buttercup.common.datastructures.msg_pb2 import FunctionCoverage


@pytest.fixture
def redis_client():
    res = Redis(host="localhost", port=6379, db=13)
    yield res
    res.flushdb()


@pytest.fixture
def coverage_bot(redis_client):
    return CoverageBot(
        redis=redis_client,
        timer_seconds=1,
        wdir="/tmp",
        python="python3",
        allow_pull=True,
        base_image_url="test_image",
        llvm_cov_tool="llvm-cov",
        sample_size=10,
    )


def test_sample_corpus_with_zero_sample_size(redis_client):
    # Create a coverage bot with sample_size=0
    bot = CoverageBot(
        redis=redis_client,
        timer_seconds=1,
        wdir="/tmp",
        python="python3",
        allow_pull=True,
        base_image_url="test_image",
        llvm_cov_tool="llvm-cov",
        sample_size=0,
    )

    # Create a mock corpus object instead of a real one
    mock_corpus = MagicMock()

    # Create a temporary directory to act as our corpus
    with tempfile.TemporaryDirectory() as corpus_dir:
        # Create a few test files in the corpus directory
        for i in range(5):
            with open(os.path.join(corpus_dir, f"test_file_{i}"), "w") as f:
                f.write(f"test content {i}")

        # Set the path property on our mock corpus
        mock_corpus.path = corpus_dir

        # Test the _sample_corpus method
        with bot._sample_corpus(mock_corpus) as result:
            # Now result is a tuple of (path, files)
            sampled_path, files = result
            assert sampled_path == corpus_dir
            assert len(files) > 0


def test_sample_corpus_with_positive_sample_size(redis_client):
    # Create a coverage bot with sample_size=3
    bot = CoverageBot(
        redis=redis_client,
        timer_seconds=1,
        wdir="/tmp",
        python="python3",
        allow_pull=True,
        base_image_url="test_image",
        llvm_cov_tool="llvm-cov",
        sample_size=3,
    )

    # Create a mock corpus object instead of a real one
    mock_corpus = MagicMock()

    # Create a temporary directory to act as our corpus
    with tempfile.TemporaryDirectory() as corpus_dir:
        # Create some test files in the corpus directory
        for i in range(10):  # Create 10 files, but we'll sample only 3
            with open(os.path.join(corpus_dir, f"test_file_{i}"), "w") as f:
                f.write(f"test content {i}")

        # Set the path property on our mock corpus
        mock_corpus.path = corpus_dir

        # Mock node_local.scratch_dir to return a temporary directory
        with patch("buttercup.common.node_local.scratch_dir") as mock_scratch_dir:
            # Create a temporary directory for the mock
            with tempfile.TemporaryDirectory() as tmp_dir:
                # Create a mock TmpDir that returns our temporary directory
                mock_tmp_dir = MagicMock()
                mock_tmp_dir.path = tmp_dir
                # Make the scratch_dir function return our mock
                mock_scratch_dir.return_value.__enter__.return_value = mock_tmp_dir

                # Test the _sample_corpus method
                with bot._sample_corpus(mock_corpus) as result:
                    # Now result is a tuple of (path, files)
                    sampled_path, files = result
                    # Verify the sampled path is not the original corpus path
                    assert sampled_path != corpus_dir
                    # Verify the sampled path is the temporary directory
                    assert sampled_path == tmp_dir
                    # Verify the correct number of files were copied
                    assert len(os.listdir(sampled_path)) == 3
                    # Verify we got the right number of files in the return value
                    assert len(files) == 3


def test_sample_corpus_with_fewer_files_than_sample_size(redis_client):
    # Create a coverage bot with sample_size=10
    bot = CoverageBot(
        redis=redis_client,
        timer_seconds=1,
        wdir="/tmp",
        python="python3",
        allow_pull=True,
        base_image_url="test_image",
        llvm_cov_tool="llvm-cov",
        sample_size=10,
    )

    # Create a mock corpus object
    mock_corpus = MagicMock()

    # Create a temporary directory to act as our corpus
    with tempfile.TemporaryDirectory() as corpus_dir:
        # Create fewer files than the sample_size
        for i in range(5):  # Create only 5 files, but sample_size is 10
            with open(os.path.join(corpus_dir, f"test_file_{i}"), "w") as f:
                f.write(f"test content {i}")

        mock_corpus.path = corpus_dir

        # Mock node_local.scratch_dir to return a temporary directory
        with patch("buttercup.common.node_local.scratch_dir") as mock_scratch_dir:
            # Create a temporary directory for the mock
            with tempfile.TemporaryDirectory() as tmp_dir:
                # Create a mock TmpDir that returns our temporary directory
                mock_tmp_dir = MagicMock()
                mock_tmp_dir.path = tmp_dir
                # Make the scratch_dir function return our mock
                mock_scratch_dir.return_value.__enter__.return_value = mock_tmp_dir

                # Test the _sample_corpus method
                with bot._sample_corpus(mock_corpus) as result:
                    # Now result is a tuple of (path, files)
                    sampled_path, files = result
                    # Verify the sampled path is the temporary directory
                    assert sampled_path == tmp_dir
                    # Verify all 5 files were copied, not just a subset
                    assert len(os.listdir(sampled_path)) == 5
                    # Verify we got all files in the return value
                    assert len(files) == 5


def test_should_update_function_coverage_zero_coverage(redis_client):
    coverage_map = CoverageMap(redis_client, "test_harness", "test_package", "test_task")
    function_coverage = FunctionCoverage()
    function_coverage.function_name = "test_function"
    function_coverage.total_lines = 0
    function_coverage.covered_lines = 0
    function_coverage.function_paths.extend(["path1"])

    result = CoverageBot._should_update_function_coverage(coverage_map, function_coverage)
    assert result is False


def test_should_update_function_coverage_new_function(redis_client):
    coverage_map = CoverageMap(redis_client, "test_harness", "test_package", "test_task")

    function_coverage = FunctionCoverage()
    function_coverage.function_name = "test_function"
    function_coverage.total_lines = 100
    function_coverage.covered_lines = 50
    function_coverage.function_paths.extend(["path1"])

    result = CoverageBot._should_update_function_coverage(coverage_map, function_coverage)
    assert result is True


def test_should_update_function_coverage_better_coverage(redis_client):
    coverage_map = CoverageMap(redis_client, "test_harness", "test_package", "test_task")

    # First set some initial coverage
    old_coverage = FunctionCoverage()
    old_coverage.function_name = "test_function"
    old_coverage.total_lines = 100
    old_coverage.covered_lines = 50
    old_coverage.function_paths.extend(["path1"])
    coverage_map.set_function_coverage(old_coverage)

    # Now test with better coverage
    function_coverage = FunctionCoverage()
    function_coverage.function_name = "test_function"
    function_coverage.total_lines = 100
    function_coverage.covered_lines = 75
    function_coverage.function_paths.extend(["path1"])

    result = CoverageBot._should_update_function_coverage(coverage_map, function_coverage)
    assert result is True


def test_should_update_function_coverage_worse_coverage(redis_client):
    coverage_map = CoverageMap(redis_client, "test_harness", "test_package", "test_task")

    # First set some initial coverage
    old_coverage = FunctionCoverage()
    old_coverage.function_name = "test_function"
    old_coverage.total_lines = 100
    old_coverage.covered_lines = 75
    old_coverage.function_paths.extend(["path1"])
    coverage_map.set_function_coverage(old_coverage)

    # Now test with worse coverage
    function_coverage = FunctionCoverage()
    function_coverage.function_name = "test_function"
    function_coverage.total_lines = 100
    function_coverage.covered_lines = 50
    function_coverage.function_paths.extend(["path1"])

    result = CoverageBot._should_update_function_coverage(coverage_map, function_coverage)
    assert result is False


def test_submit_function_coverage(coverage_bot, redis_client):
    # Create test data
    func_coverage = [
        CoveredFunction(names="test_function", total_lines=100, covered_lines=75, function_paths=["path1", "path2"])
    ]
    harness_name = "test_harness"
    package_name = "test_package"
    task_id = "test_task_id"

    # Create a real CoverageMap instance
    coverage_map = CoverageMap(redis_client, harness_name, package_name, task_id)

    coverage_bot._submit_function_coverage(func_coverage, harness_name, package_name, task_id)

    # Verify the coverage was stored correctly
    stored_coverage = coverage_map.get_function_coverage("test_function", ["path1", "path2"])
    assert stored_coverage is not None
    assert stored_coverage.function_name == "test_function"
    assert stored_coverage.total_lines == 100
    assert stored_coverage.covered_lines == 75
    assert list(stored_coverage.function_paths) == ["path1", "path2"]


def test_submit_function_coverage_multiple_functions(coverage_bot, redis_client):
    # Create test data with multiple functions
    func_coverage = [
        CoveredFunction(names="function1", total_lines=100, covered_lines=75, function_paths=["path1"]),
        CoveredFunction(names="function2", total_lines=200, covered_lines=150, function_paths=["path2"]),
    ]
    harness_name = "test_harness"
    package_name = "test_package"
    task_id = "test_task_id"

    # Create a real CoverageMap instance
    coverage_map = CoverageMap(redis_client, harness_name, package_name, task_id)

    coverage_bot._submit_function_coverage(func_coverage, harness_name, package_name, task_id)

    # Verify both functions were stored correctly
    stored_coverages = coverage_map.list_function_coverage()
    assert len(stored_coverages) == 2

    # Create a set of function names for easier verification
    function_names = {coverage.function_name for coverage in stored_coverages}
    assert function_names == {"function1", "function2"}
