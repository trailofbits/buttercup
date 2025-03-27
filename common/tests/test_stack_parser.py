import pytest
from buttercup.common.stack_parsing import get_crash_data
from pathlib import Path


def get_tc_file(name: str) -> Path:
    """Get testcase file"""
    crash_file = Path(__file__).parent / "data" / "stacktrace_corpus" / f"{name}_stacktrace.txt"
    if not crash_file.exists():
        raise FileNotFoundError(f"Crash file not found at {crash_file}")

    return crash_file


@pytest.fixture
def java_crash_testcase() -> Path:
    """Get java crash_test_case"""
    return get_tc_file("java")


@pytest.fixture
def c_crash_testcase() -> Path:
    """Get c crash_test_case"""
    return get_tc_file("c")


def test_get_crash_data_basic():
    # Simple stacktrace example
    stacktrace = """
    #0 0x7f339b644844 in foo::bar::crash() /src/foo/bar.cc:123:4
    #1 0x7f339b644900 in main /src/main.cc:45:2
    """
    crash_state = get_crash_data(stacktrace)
    assert crash_state is not None
    assert isinstance(crash_state, str)


def test_get_crash_data_symbolized():
    # Test with symbolized stacktrace
    stacktrace = """
    #0 foo::bar::crash() /src/foo/bar.cc:123:4
    #1 main /src/main.cc:45:2
    """
    crash_state = get_crash_data(stacktrace, symbolized=True)
    assert crash_state is not None
    assert isinstance(crash_state, str)


def test_get_crash_data_empty():
    # Test with empty stacktrace
    stacktrace = ""
    crash_state = get_crash_data(stacktrace)
    assert crash_state is not None
    assert isinstance(crash_state, str)


def test_get_crash_data_invalid():
    # Test with invalid stacktrace format
    stacktrace = "This is not a valid stacktrace"
    crash_state = get_crash_data(stacktrace)
    assert crash_state is not None
    assert isinstance(crash_state, str)


def test_java_stacktrace(java_crash_testcase: Path):
    with open(java_crash_testcase, "r") as f:
        trace = f.read()

    crash_state = get_crash_data(trace)
    expected = "org.apache.commons.jxpath.ri.compiler.CoreOperation.parenthesize\norg.apache.commons.jxpath.ri.compiler.CoreOperation.toString\norg.apache.commons.jxpath.ri.compiler.CoreOperation.parenthesize\n"
    assert crash_state == expected


def test_c_stacktrace(c_crash_testcase: Path):
    with open(c_crash_testcase, "r") as f:
        trace = f.read()

    crash_state = get_crash_data(trace)
    print(crash_state)
    assert crash_state is not None
    assert isinstance(crash_state, str)
    expected = "cil_destroy_block\ncil_destroy_data\ncil_tree_node_destroy\n"
    assert crash_state == expected
