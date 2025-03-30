import pytest
from redis import Redis
from buttercup.common.maps import CoverageMap
from buttercup.common.datastructures.msg_pb2 import FunctionCoverage


@pytest.fixture
def redis_client():
    res = Redis(host="localhost", port=6379, db=15)
    yield res
    res.flushdb()


@pytest.fixture
def coverage_map(redis_client):
    return CoverageMap(redis_client, harness_name="test_harness", package_name="test_package", task_id="test_task_id")


def test_coverage_map_set_and_get(coverage_map):
    # Create a FunctionCoverage instance
    function_coverage = FunctionCoverage()
    function_coverage.function_name = "test_function"
    function_coverage.function_paths.extend(["path1", "path2"])
    function_coverage.total_lines = 100
    function_coverage.covered_lines = 75

    # Set the function coverage
    coverage_map.set_function_coverage(function_coverage)

    # Retrieve the function coverage
    function_paths_list = list(function_coverage.function_paths)
    retrieved_coverage = coverage_map.get_function_coverage(function_coverage.function_name, function_paths_list)

    # Verify the retrieved coverage matches the original
    assert retrieved_coverage.function_name == function_coverage.function_name
    assert retrieved_coverage.function_paths == function_coverage.function_paths
    assert retrieved_coverage.total_lines == function_coverage.total_lines
    assert retrieved_coverage.covered_lines == function_coverage.covered_lines


def test_coverage_map_iteration(coverage_map):
    # Create a FunctionCoverage instance
    function_coverage = FunctionCoverage()
    function_coverage.function_name = "test_function"
    function_coverage.function_paths.extend(["path1", "path2"])
    function_coverage.total_lines = 100
    function_coverage.covered_lines = 75

    # Set the function coverage
    coverage_map.set_function_coverage(function_coverage)

    # Get all function coverages
    coverages = coverage_map.list_function_coverage()

    # Verify we got exactly one coverage entry
    assert len(coverages) == 1

    # Verify the retrieved coverage matches the original
    retrieved_coverage = coverages[0]
    assert retrieved_coverage.function_name == function_coverage.function_name
    assert retrieved_coverage.function_paths == function_coverage.function_paths
    assert retrieved_coverage.total_lines == function_coverage.total_lines
    assert retrieved_coverage.covered_lines == function_coverage.covered_lines


def test_coverage_map_multiple_functions(coverage_map):
    # Create multiple FunctionCoverage instances
    function1 = FunctionCoverage()
    function1.function_name = "function1"
    function1.function_paths.extend(["path1"])
    function1.total_lines = 100
    function1.covered_lines = 80

    function2 = FunctionCoverage()
    function2.function_name = "function2"
    function2.function_paths.extend(["path2"])
    function2.total_lines = 200
    function2.covered_lines = 180

    # Set both function coverages
    coverage_map.set_function_coverage(function1)
    coverage_map.set_function_coverage(function2)

    # Get all function coverages
    coverages = coverage_map.list_function_coverage()

    # Verify we got exactly two coverage entries
    assert len(coverages) == 2

    # Create a set of function names for easier verification
    function_names = {coverage.function_name for coverage in coverages}
    assert function_names == {"function1", "function2"}


def test_coverage_map_nonexistent_function(coverage_map):
    # Try to get coverage for a nonexistent function
    coverage = coverage_map.get_function_coverage("nonexistent_function", ["nonexistent_path"])
    assert coverage is None
