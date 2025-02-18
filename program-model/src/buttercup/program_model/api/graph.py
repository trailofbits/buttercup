from buttercup.program_model.graph import Node, Edge, decode_value
import logging
from dataclasses import dataclass
from typing import List
from gremlin_python.structure.graph import Graph as GremlinGraph
from gremlin_python.process.traversal import T
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

    def get_nodes_by_text(self, search_text: str) -> List[Node]:
        """Get a node from the graph by text."""

        logger.debug(f"Searching for {search_text}")

        nodes = self.g.V().has("/kythe/text").element_map().to_list()

        rv: List[Node] = []
        for node in nodes:
            node_text = node["/kythe/text"]
            decoded_text = decode_value(node_text).decode()
            if search_text in decoded_text:
                property = {}
                for k, v in node.items():
                    if k != T.id and k != T.label:
                        property[k] = v

                rv.append(
                    Node(
                        id=node[T.id],
                        label=node[T.label],
                        property=property,
                    )
                )

        return rv

    def get_nodes_by_file_name(self, file_name: str) -> Node:
        """Get nodes from the graph by file name."""
        pass

    def set_node_property(self, node: Node, property_name: str, property_value: str):
        """Set a property on a node."""
        pass

    def set_edge_property(self, edge: Edge, property_name: str, property_value: str):
        """Set a property on an edge."""
        pass
