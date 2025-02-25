from buttercup.program_model.graph import Node, Edge, decode_value, encode_value
import logging
from dataclasses import dataclass
from typing import List, Dict
from pathlib import Path
from gremlin_python.structure.graph import Graph as GremlinGraph
from gremlin_python.process.traversal import T, TextP
from gremlin_python.driver.driver_remote_connection import (
    DriverRemoteConnection,
)

logger = logging.getLogger(__name__)


@dataclass
class Graph:
    """Program Model Graph API class."""

    url: str = "ws://graphdb:8182/gremlin"

    def __post_init__(self):
        self.graph = GremlinGraph()
        self.connection = DriverRemoteConnection(self.url, "g")
        self.g = self.graph.traversal().withRemote(self.connection)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.connection.close()

    def _decode_properties(self, obj: dict) -> dict:
        """Decode properties from the graph."""
        properties = {}
        for k, v in obj.items():
            if k != T.id and k != T.label:
                properties[k] = decode_value(v)
        return properties

    def _decode_node(self, node: dict) -> Node:
        """Decode a node from the graph."""
        return Node(
            id=node[T.id],
            label=node[T.label],
            properties=self._decode_properties(node),
        )

    def _decode_edge(self, edge: dict) -> Edge:
        """Decode an edge from the graph."""
        return Edge(
            id=edge[T.id],
            label=edge[T.label],
            properties=self._decode_properties(edge),
        )

    def get_distinct_node_types(self) -> List[Node]:
        """Get distinct node types."""
        nodes: List[Node] = []
        for k in (
            self.g.V()
            .has("/kythe/node/kind")
            .values("/kythe/node/kind")
            .dedup()
            .toList()
        ):
            n = self.g.V().has("/kythe/node/kind", k).limit(1).elementMap().toList()[0]
            nodes.append(self._decode_node(n))
        return nodes

    def get_distinct_edge_types(self) -> List[str]:
        """Get distinct edge types."""
        edges: List[str] = []
        for l in self.g.E().label().dedup().toList():  # noqa: E741
            edges.append(l)
        return edges

    def _get_function_nodes(
        self, function_name: str, source_path: str | None = None
    ) -> List[Dict]:
        """Retrieves all function nodes matching the given function name and optionally source path."""
        if source_path is None:
            return (
                self.g.V()
                .has("/kythe/node/kind", encode_value(b"function"))
                .has(
                    "/kythe/code",
                    TextP.containing(function_name),
                )
                .elementMap()
                .toList()
            )
        else:
            return (
                self.g.V()
                .has("/kythe/node/kind", encode_value(b"function"))
                .has(
                    "/kythe/code",
                    TextP.containing(function_name),
                )
                .has("path", source_path)
                .elementMap()
                .toList()
            )

    def _get_node_anchors(self, node_id: str) -> List[Dict]:
        """Get all anchors for a given node."""
        return self.g.V(node_id).in_("/kythe/edge/defines").elementMap().toList()

    def _get_function_node_body(self, function_node: Dict) -> List[str]:
        """Get the body of a function node."""

        # Get anchor nodes for this function node
        anchors = self._get_node_anchors(function_node[T.id])
        logger.debug(f"Found {len(anchors)} anchors")

        files: List[Dict] = []

        # For each anchor found
        for a in anchors:
            logger.debug(f"Anchor: {a}")

            # Get start and end bytes of the function
            a_plain = self._decode_node(a)
            start = int(a_plain.properties.get("/kythe/loc/start"))
            end = int(a_plain.properties.get("/kythe/loc/end"))
            logger.debug(f"Start byte offset: {start}, End byte offset: {end}")

            # Get the file nodes matching the anchor's file path
            file_path = a_plain.properties.get("path")
            files.extend(
                self.g.V()
                .has("/kythe/node/kind", encode_value(b"file"))
                .has("path", encode_value(file_path))
                .elementMap()
                .toList()
            )
        logger.debug(f"Found {len(files)} files")

        bodies: List[str] = []

        # For each file found, return the function body
        for fn in files:
            fn_plain = self._decode_node(fn)
            bodies.append(fn_plain.properties.get("/kythe/text")[start:end])

        return bodies

    def get_function_body(
        self, function_name: str, source_path: Path | None = None
    ) -> List[str]:
        """Get function bodies by name."""

        function_name_encode = encode_value(function_name.encode("utf-8"))
        source_path_encode = (
            encode_value(str(source_path).encode("utf-8")) if source_path else None
        )

        if source_path is not None:
            logger.info(
                f"Searching for functions with name: {function_name} from file path: {source_path}"
            )
            logger.debug(f"Encoded source path: {source_path_encode}")
        else:
            logger.info(f"Searching for functions with name: {function_name}")
        logger.debug(f"Encoded function name: {function_name_encode}")

        # Retrieve all functions matching this function name (and optionally source path)
        functions = self._get_function_nodes(
            function_name=function_name_encode, source_path=source_path_encode
        )
        logger.debug(f"Found {len(functions)} functions")

        bodies: List[str] = []

        # For each function found
        for f in functions:
            logger.debug(f"Function: {f}")
            bodies.extend(self._get_function_node_body(f))

        return bodies

    # TODO(Evan)
    def set_node_property(
        self, node: Node, property_name: str, property_value: str
    ) -> bool:
        """Set a property on a node."""
        logger.error("Not implemented")
        return False

    # TODO(Evan)
    def set_edge_property(
        self, edge: Edge, property_name: str, property_value: str
    ) -> bool:
        """Set a property on an edge."""
        logger.error("Not implemented")
        return False
