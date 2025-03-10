import os
from pathlib import Path
from tempfile import TemporaryDirectory
from xml.dom import minidom
import pytest
from buttercup.common.challenge_task import ChallengeTask
from buttercup.common.task_meta import TaskMeta
from buttercup.program_model.api import Graph
from buttercup.program_model.graph import encode_value


@pytest.fixture
def task_dir(tmp_path: Path) -> Path:
    """Create a mock challenge task directory structure."""
    # Create the main directories
    oss_fuzz = tmp_path / "fuzz-tooling" / "my-oss-fuzz"
    source = tmp_path / "src" / "my-source"
    diffs = tmp_path / "diff" / "my-diff"

    oss_fuzz.mkdir(parents=True, exist_ok=True)
    source.mkdir(parents=True, exist_ok=True)
    diffs.mkdir(parents=True, exist_ok=True)

    # Create some mock patch files
    (diffs / "patch1.diff").write_text("mock patch 1")
    (diffs / "patch2.diff").write_text("mock patch 2")

    # Create a mock helper.py file
    helper_path = oss_fuzz / "infra/helper.py"
    helper_path.parent.mkdir(parents=True, exist_ok=True)
    helper_path.write_text("import sys;\nsys.exit(0)\n")

    # Create a mock test.txt file
    (source / "test.txt").write_text("mock test content")

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
    (source / "test.c").write_text(test_c_content)

    # Create task metadata
    TaskMeta(project_name="example_project", focus="my-source").save(tmp_path)

    return tmp_path


@pytest.fixture
def challenge_task_readonly(task_dir: Path) -> ChallengeTask:
    """Create a mock challenge task for testing."""
    return ChallengeTask(
        read_only_task_dir=task_dir,
    )


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


@pytest.mark.skip("Skipping test as we switch to using codequery until Kythe is ready")
def test_get_function_body(get_graphml_content: str):
    """Test getting function body from graph database."""

    from gremlin_python.process.anonymous_traversal import traversal
    from gremlin_python.driver.driver_remote_connection import (
        DriverRemoteConnection,
    )

    # Create a mock graph database
    with TemporaryDirectory() as td:
        # Make the temporary directory readable by the gremlin user
        os.chmod(td, 0o777)
        graphml_path = Path(td) / "graph.xml"
        graphml_path.write_text(data=get_graphml_content)
        g = traversal().withRemote(
            DriverRemoteConnection("ws://localhost:8182/gremlin", "g")
        )
        g.io(str(graphml_path)).read().iterate()

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
