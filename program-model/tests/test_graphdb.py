"""Tests for the graph database.
NOTE: Splitting this into individual tests for Kythe indexing is difficult because the project needs to exist in OSS Fuzz.
"""

from pathlib import Path
from xml.dom import minidom
import pytest
from typing import Iterator
from buttercup.common.challenge_task import ChallengeTask
from buttercup.program_model.api import Graph
from buttercup.program_model.graph import encode_value
from buttercup.program_model.program_model import ProgramModel
from buttercup.common.datastructures.msg_pb2 import IndexRequest
from gremlin_python.process.anonymous_traversal import traversal
from gremlin_python.driver.driver_remote_connection import (
    DriverRemoteConnection,
)


def cleanup_graphdb(request, task_id: str):
    """Clean up the JanusGraph database by dropping vertices and edges associated with a specific task ID."""
    from .conftest import cleanup_graphdb as conftest_cleanup

    conftest_cleanup(request, task_id)


@pytest.fixture
def get_graphml_content() -> str:
    """Create a mock graphml file."""

    # Create a test C file with two functions
    test_c_content = """
#include <stdio.h>

int add(int a, int b) {
    return a + b;
}

void print_hello(void) {
    printf("Hello, World!\\n");
}
"""

    content = '<?xml version="1.0" encoding="UTF-8"?>'
    content += '<graphml xmlns="http://graphml.graphdrawing.org/xmlns" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:schemaLocation="http://graphml.graphdrawing.org/xmlns http://graphml.graphdrawing.org/xmlns/1.1/graphml.xsd">'
    content += '<graph id="G" edgedefault="directed">'

    for p in [
        "task_id",
        "path",
        "function",
        "file",
        "signature",
        "root",
        "corpus",
        "language",
        "/kythe/node/kind",
        "/kythe/code",
        "/kythe/loc/start",
        "/kythe/loc/end",
        "/kythe/text",
        "/kythe/edge/defines",
    ]:
        content += f'<key id="{p}" for="node" attr.name="{p}" attr.type="string" />'

    # Create edge key
    content += '<key id="labelE" for="edge" attr.name="labelE" attr.type="string" />'

    # Create function node
    content += '<node id="1">'
    content += f'<data key="task_id">{encode_value(b"unit_test")}</data>'
    content += f'<data key="path">{encode_value(b"test.c")}</data>'
    content += '<data key="root"></data>'
    content += '<data key="corpus"></data>'
    content += f'<data key="language">{encode_value(b"c")}</data>'
    content += f'<data key="/kythe/node/kind">{encode_value(b"function")}</data>'
    content += (
        f'<data key="/kythe/code">{encode_value(b"int add(int a, int b)")}</data>'
    )
    content += "</node>"

    content += '<node id="2">'
    content += f'<data key="task_id">{encode_value(b"unit_test")}</data>'
    content += f'<data key="path">{encode_value(b"test.c")}</data>'
    content += '<data key="root"></data>'
    content += '<data key="corpus"></data>'
    content += f'<data key="language">{encode_value(b"c")}</data>'
    content += f'<data key="/kythe/node/kind">{encode_value(b"function")}</data>'
    content += (
        f'<data key="/kythe/code">{encode_value(b"void print_hello(void)")}</data>'
    )
    content += "</node>"

    # Create anchor node
    content += '<node id="3">'
    content += f'<data key="task_id">{encode_value(b"unit_test")}</data>'
    content += f'<data key="path">{encode_value(b"test.c")}</data>'
    content += '<data key="root"></data>'
    content += '<data key="corpus"></data>'
    content += f'<data key="language">{encode_value(b"c")}</data>'
    content += f'<data key="/kythe/node/kind">{encode_value(b"anchor")}</data>'
    content += f'<data key="/kythe/loc/start">{encode_value(b"21")}</data>'
    content += f'<data key="/kythe/loc/end">{encode_value(b"62")}</data>'
    content += "</node>"

    content += '<edge id="1" source="3" target="1">'
    content += '<data key="labelE">/kythe/edge/defines</data>'
    content += "</edge>"

    content += '<node id="4">'
    content += f'<data key="task_id">{encode_value(b"unit_test")}</data>'
    content += f'<data key="path">{encode_value(b"test.c")}</data>'
    content += '<data key="root"></data>'
    content += '<data key="corpus"></data>'
    content += f'<data key="language">{encode_value(b"c")}</data>'
    content += f'<data key="/kythe/node/kind">{encode_value(b"anchor")}</data>'
    content += f'<data key="/kythe/loc/start">{encode_value(b"66")}</data>'
    content += f'<data key="/kythe/loc/end">{encode_value(b"121")}</data>'
    content += "</node>"

    content += '<edge id="2" source="4" target="2">'
    content += '<data key="labelE">/kythe/edge/defines</data>'
    content += "</edge>"

    # Create file node
    content += '<node id="5">'
    content += f'<data key="task_id">{encode_value(b"unit_test")}</data>'
    content += f'<data key="path">{encode_value(b"test.c")}</data>'
    content += '<data key="root"></data>'
    content += '<data key="corpus"></data>'
    content += f'<data key="language">{encode_value(b"c")}</data>'
    content += f'<data key="/kythe/node/kind">{encode_value(b"file")}</data>'
    content += (
        f'<data key="/kythe/text">{encode_value(test_c_content.encode("utf-8"))}</data>'
    )
    content += "</node>"

    content += "</graph>"
    content += "</graphml>"

    xml_doc = minidom.parseString(content)
    pretty_xml = xml_doc.toprettyxml(indent="  ")
    return pretty_xml


@pytest.fixture
def graphml_db(tmp_path: Path, get_graphml_content: str, request) -> Iterator[bool]:
    cleanup_graphdb(request, "unit_test")

    data_exists = False
    with Graph(url="ws://localhost:8182/gremlin") as graph:
        # Check if the task is already in the database
        if graph.g.V().has("task_id", encode_value(b"unit_test")).count().next():
            data_exists = True
            yield True

    if not data_exists:
        # Create a mock graph database
        # Make the temporary directory readable by the gremlin user
        graphml_path = Path("/crs_scratch/graph.xml")
        graphml_path.write_text(data=get_graphml_content)
        g = traversal().withRemote(
            DriverRemoteConnection("ws://localhost:8182/gremlin", "g")
        )
        g.io(str("/crs_scratch/graph.xml")).read().iterate()
        yield True

    # Clean up the graph database
    cleanup_graphdb(request, "unit_test")


@pytest.mark.skip(reason="Skipping test because we're not using Kythe")
def test_get_function_body(graphml_db: bool):
    """Test getting function body from graph database."""
    assert graphml_db is True

    # Test querying the graph database
    with Graph(url="ws://localhost:8182/gremlin") as graph:
        bodies = graph.get_function_body(function_name="add")
        assert len(bodies) == 1
        assert b"int add(int a, int b)" in bodies[0]
        assert b"return a + b;" in bodies[0]

        bodies = graph.get_function_body(
            function_name="add", source_path=Path("test.c")
        )
        assert len(bodies) == 1
        assert b"int add(int a, int b)" in bodies[0]
        assert b"return a + b;" in bodies[0]

        bodies = graph.get_function_body(
            function_name="add", source_path=Path("doesnotexist.c")
        )
        assert len(bodies) == 0

        bodies = graph.get_function_body(function_name="print_hello")
        assert len(bodies) == 1
        assert b"void print_hello(void)" in bodies[0]
        assert b'printf("Hello, World!\\n");' in bodies[0]


@pytest.fixture
def libpng_oss_fuzz_graphml_content(
    libpng_oss_fuzz_task: ChallengeTask, request
) -> Iterator[bool]:
    """Create a graphml file for libpng task."""

    cleanup_graphdb(request, libpng_oss_fuzz_task.task_meta.task_id)

    data_exists = False
    with Graph(url="ws://localhost:8182/gremlin") as graph:
        # Check if the task is already in the database
        if (
            graph.g.V()
            .has(
                "task_id",
                encode_value(libpng_oss_fuzz_task.task_meta.task_id.encode("utf-8")),
            )
            .count()
            .next()
        ):
            data_exists = True

    if not data_exists:
        index_request = IndexRequest(
            build_type="",
            package_name=libpng_oss_fuzz_task.project_name,
            sanitizer="",
            task_dir=libpng_oss_fuzz_task.task_dir.as_posix(),
            task_id=libpng_oss_fuzz_task.task_meta.task_id,
        )
        with ProgramModel(
            wdir=Path("/crs_scratch"),
            script_dir=Path("scripts"),
            kythe_dir=Path("scripts/gzs/kythe"),
            graphdb_url="ws://localhost:8182/gremlin",
            python="python",
        ) as program_model:
            if not program_model.process_task_kythe(index_request):
                yield False

    with Graph(url="ws://localhost:8182/gremlin") as graph:
        bodies = graph.get_function_body(
            function_name="png_handle_iCCP", source_path=Path("pngrutil.c")
        )
        assert len(bodies) == 2
        assert b"png_handle_iCCP" in bodies[0]

    cleanup_graphdb(request, libpng_oss_fuzz_task.task_meta.task_id)

    yield True


# @pytest.mark.integration
@pytest.mark.skip(reason="Skipping test because we're not using Kythe")
def test_libpng_get_function_body(libpng_oss_fuzz_graphml_content: bool):
    """Test getting function body from libpng."""
    assert libpng_oss_fuzz_graphml_content is True
