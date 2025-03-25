import pytest
from buttercup.program_model.api import Graph
from buttercup.program_model.graph import encode_value


def is_cleanup_enabled(request) -> bool:
    """Check if the --no-cleanup flag was passed to pytest."""
    return not request.config.getoption("--no-cleanup")


def cleanup_graphdb(request, task_id: str):
    """Clean up the JanusGraph database by dropping vertices and edges associated with a specific task ID."""
    if not is_cleanup_enabled(request):
        return

    with Graph(url="ws://localhost:8182/gremlin") as graph:
        # Drop vertices and edges associated with the task ID
        graph.g.V().has(
            "task_id", encode_value(task_id.encode("utf-8"))
        ).drop().iterate()
        graph.g.E().has(
            "task_id", encode_value(task_id.encode("utf-8"))
        ).drop().iterate()


def pytest_addoption(parser):
    parser.addoption(
        "--runintegration",
        action="store_true",
        default=False,
        help="run integration tests",
    )
    parser.addoption(
        "--no-cleanup",
        action="store_true",
        default=False,
        help="do not clean up database before and after tests",
    )


def pytest_configure(config):
    config.addinivalue_line("markers", "integration: mark test as an integration test")


def pytest_collection_modifyitems(config, items):
    if config.getoption("--runintegration"):
        # --runintegration given in cli: do not skip integration tests
        return
    skip_integration = pytest.mark.skip(reason="need --runintegration option to run")
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip_integration)
