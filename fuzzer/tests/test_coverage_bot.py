import pytest
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
    )


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
