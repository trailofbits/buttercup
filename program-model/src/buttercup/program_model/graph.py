import urllib.parse
from xml.dom import minidom
import logging
from dataclasses import dataclass, field
from io import BytesIO
from typing import Generator, Dict, Set
from buttercup.program_model.data.kythe.proto.storage_pb2 import Entry, VName
from buttercup.program_model.utils.varint import decode_stream

logger = logging.getLogger(__name__)


def encode_value(value: bytes) -> str:
    """Encode bytes as hex string"""
    return value.hex()


def decode_value(value: str) -> bytes:
    """Decode hex string as bytes"""
    return bytes.fromhex(value)


@dataclass(frozen=True, repr=False)
class KytheURI:
    """Kythe entries described here: https://kythe.io/docs/kythe-storage.html#_entry"""

    corpus: str
    language: str
    path: str
    root: str
    signature: str

    def __str__(self):
        lst = [self.corpus, self.language, self.path, self.root, self.signature]
        uristr = "/".join([urllib.parse.quote(x, safe="") for x in lst])
        return uristr

    @staticmethod
    def from_vname(vn: VName):
        return KytheURI(
            signature=vn.signature,
            corpus=vn.corpus,
            root=vn.root,
            path=vn.path,
            language=vn.language,
        )


@dataclass
class Node:
    """Node in the graph."""

    id: str
    label: str | None = None
    properties: Dict[str, str] = field(default_factory=dict)

    def __str__(self):
        properties_str = ",".join([f"[{k}: {v}]" for k, v in self.properties.items()])
        return f"Node(id={self.id}, label={self.label}, properties={properties_str}"

    def to_graphml(self) -> str:
        """Convert node to a GraphML string."""
        content = []
        content.append(f'<node id="{self.id}">')
        for key, value in self.properties.items():
            content.append(f'<data key="{key}">{value}</data>')
        content.append("</node>")
        return "".join(content)


@dataclass
class Edge:
    """Edge in the graph."""

    id: str
    source_id: str
    target_id: str
    properties: Dict[str, str] = field(default_factory=dict)

    def __str__(self):
        properties_str = ",".join([f"[{k}: {v}]" for k, v in self.properties.items()])
        return f"Edge(id={self.id}, source_id={self.source_id}, target_id={self.target_id}, properties={properties_str}"

    def to_graphml(self) -> str:
        """Convert edge to a GraphML string."""
        content = []
        content.append(
            f'<edge id="{self.id}" source="{self.source_id}" target="{self.target_id}">'
        )
        for key, value in self.properties.items():
            content.append(f'<data key="{key}">{value}</data>')
        content.append("</edge>")
        return "".join(content)


@dataclass(repr=False)
class GraphStorage:
    """Class to interact between Kythe and an output file."""

    def __init__(self, task_id: str):
        self.task_id: str = task_id
        self.nodes: Dict[str, Node] = {}
        self.node_properties: Set[str] = set(
            ["corpus", "language", "path", "root", "signature", "task_id"]
        )
        self.edges: Dict[str, Edge] = {}
        self.edge_properties: Set[str] = set(["labelE", "task_id"])

    def is_edge(self, ent: Entry) -> bool:
        """Check if the entry is an edge."""
        return ent.edge_kind != ""

    def convert_node(self, nd: VName) -> Node:
        """Converts a Kythe node to a GraphML node."""
        uri = str(KytheURI.from_vname(nd))
        if uri in self.nodes.keys():
            return self.nodes[uri]
        return Node(
            id=uri,
            properties={
                "corpus": encode_value(nd.corpus.encode("utf-8")),
                "language": encode_value(nd.language.encode("utf-8")),
                "path": encode_value(nd.path.encode("utf-8")),
                "root": encode_value(nd.root.encode("utf-8")),
                "signature": encode_value(nd.signature.encode("utf-8")),
            },
        )

    def process_stream(self, fl: BytesIO):
        """Process a stream of Kythe entries and output them to a GraphML file."""

        try:
            for entry in self.iterate_over_entries(fl):
                source_node = self.convert_node(entry.source)
                source_node.properties["task_id"] = encode_value(
                    self.task_id.encode("utf-8")
                )
                key = entry.fact_name
                value = encode_value(entry.fact_value)

                if self.is_edge(entry):
                    target_node = self.convert_node(entry.target)
                    target_node.properties["task_id"] = encode_value(
                        self.task_id.encode("utf-8")
                    )
                    edge = Edge(
                        id=len(self.edges.keys()),
                        source_id=source_node.id,
                        target_id=target_node.id,
                    )
                    edge.properties["labelE"] = entry.edge_kind
                    edge.properties["task_id"] = encode_value(
                        self.task_id.encode("utf-8")
                    )
                    self.edges[edge.id] = edge
                else:
                    source_node.properties[key] = value
                    self.node_properties.add(key)
                    self.nodes[source_node.id] = source_node
        except Exception as e:
            logger.error("Exception occurred: %s", e)
            raise e

    def iterate_over_entries(self, fl: BytesIO) -> Generator[Entry, None, None]:
        """Iterate over entries in the stream."""

        # Indexers emit a delimited stream of entry protobufs
        # From: https://kythe.io/examples/#indexing-compilations
        while True:
            try:
                yield self.parse_entry(fl)
            # This is the end of the stream. This error is expected.
            except EOFError:
                break
            except Exception as e:
                raise e

    def parse_entry(self, fl: BytesIO) -> Entry:
        """Parse a Kythe entry from the stream."""

        # Read the size of the entry protobuf
        sz = decode_stream(fl)
        bts = bytes()
        while len(bts) < sz:
            rd = fl.read(sz - len(bts))
            if len(rd) <= 0:
                return None
            bts += rd
        ent = Entry()
        ent.ParseFromString(bts)
        return ent

    def to_graphml(self) -> str:
        """Convert graph to a GraphML file.
        From: https://tinkerpop.apache.org/docs/3.7.3/dev/io/
        """
        content = '<?xml version="1.0" encoding="UTF-8"?>'
        content += '<graphml xmlns="http://graphml.graphdrawing.org/xmlns" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:schemaLocation="http://graphml.graphdrawing.org/xmlns http://graphml.graphdrawing.org/xmlns/1.1/graphml.xsd">'
        content += '<graph id="G" edgedefault="directed">'

        # Output node properties
        for p in self.node_properties:
            content += f'<key id="{p}" for="node" attr.name="{p}" attr.type="string" />'

        # Output edge properties
        for p in self.edge_properties:
            content += f'<key id="{p}" for="edge" attr.name="{p}" attr.type="string" />'

        # Output node contents
        for node in self.nodes.values():
            content += node.to_graphml()

        # Output edge contents
        for edge in self.edges.values():
            content += edge.to_graphml()

        content += "</graph>"
        content += "</graphml>"

        xml_doc = minidom.parseString(content)
        pretty_xml = xml_doc.toprettyxml(indent="  ")
        return pretty_xml
