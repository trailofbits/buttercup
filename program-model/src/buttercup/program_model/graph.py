import urllib.parse
import logging
import uuid
from dataclasses import dataclass, field
from typing import Generator, Dict, Set
from buttercup.program_model.data.kythe.proto.storage_pb2 import Entry, VName
from buttercup.program_model.utils.varint import decode_stream
from multiprocessing import Pool
from abc import ABC, abstractmethod
from typing import Any, List, TextIO
from io import BytesIO

logger = logging.getLogger(__name__)

ENTRY_CHUNK_SIZE = 50


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

    def __str__(self) -> str:
        lst = [self.corpus, self.language, self.path, self.root, self.signature]
        uristr = "/".join([urllib.parse.quote(x, safe="") for x in lst])
        return uristr

    @staticmethod
    def from_vname(vn: VName) -> Any:
        return KytheURI(
            signature=vn.signature,
            corpus=vn.corpus,
            root=vn.root,
            path=vn.path,
            language=vn.language,
        )


class ToGraphML(ABC):
    """Class to convert a Kythe entry to a GraphML string."""

    @abstractmethod
    def to_graphml(self) -> str:
        """Convert the entry to a GraphML string."""
        pass


@dataclass
class Node(ToGraphML):
    """Node in the graph."""

    id: str
    label: str | None = None
    properties: Dict[str, str] = field(default_factory=dict)

    def __str__(self) -> str:
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
class Edge(ToGraphML):
    """Edge in the graph."""

    id: str
    source_id: str
    target_id: str
    properties: Dict[str, str] = field(default_factory=dict)

    def __str__(self) -> str:
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


@dataclass
class WriteResult:
    """Result of writing a fragment."""

    nodes: list[Node]
    edges: list[Edge]
    node_props: list[str]
    edge_props: list[str]


def chunk_data(
    generator: Generator[Any, None, None], chunk_size: int
) -> Generator[list[Any], None, None]:
    """Split a generator into chunks of specified size."""
    chunk = []
    for item in generator:
        chunk.append(item)
        if len(chunk) == chunk_size:
            yield chunk
            chunk = []
    if chunk:
        yield chunk


class GraphWriter:
    """Class to write a GraphML file."""

    def __init__(self, task_id: str):
        self.task_id: str = task_id

    def is_edge(self, ent: Entry) -> bool:
        """Check if the entry is an edge."""
        return ent.edge_kind != ""

    def convert_node(self, nd: VName) -> Node:
        """Converts a Kythe node to a GraphML node."""
        uri = str(KytheURI.from_vname(nd))
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

    def entry_to_graphml(
        self,
        entry: Entry,
        node_props: list[str],
        edge_props: list[str],
        edges: list[Edge],
        nodes: list[Node],
    ) -> None:
        source_node = self.convert_node(entry.source)
        nodes.append(source_node)
        source_node.properties["task_id"] = encode_value(self.task_id.encode("utf-8"))
        key = entry.fact_name
        value = encode_value(entry.fact_value)
        if self.is_edge(entry):
            target_node = self.convert_node(entry.target)
            nodes.append(target_node)
            target_node.properties["task_id"] = encode_value(
                self.task_id.encode("utf-8")
            )
            edge_id = str(uuid.uuid4())
            edge = Edge(
                id=edge_id,
                source_id=source_node.id,
                target_id=target_node.id,
            )
            edge.properties["labelE"] = entry.edge_kind
            edge.properties["task_id"] = encode_value(self.task_id.encode("utf-8"))
            edges.append(edge)
        else:
            source_node.properties[key] = value
            node_props.append(key)
            nodes.append(source_node)

    def write_entry(self, entries: list[bytes]) -> WriteResult:
        node_props: list[str] = list()
        edge_props: list[str] = list()
        edges: list[Edge] = list()
        nodes: list[Node] = list()

        for bts in entries:
            try:
                ent = Entry()
                ent.ParseFromString(bts)
            except Exception as e:
                logger.error("Error parsing entry: %s", e)
                continue

            self.entry_to_graphml(ent, node_props, edge_props, edges, nodes)

        return WriteResult(
            nodes=nodes,
            edges=edges,
            node_props=node_props,
            edge_props=edge_props,
        )


@dataclass(repr=False)
class GraphStorage:
    """Class to interact between Kythe and an output file."""

    def __init__(self, task_id: str):
        self.task_id: str = task_id
        self.node_properties: Set[str] = set(
            ["corpus", "language", "path", "root", "signature", "task_id"]
        )
        self.edge_properties: Set[str] = set(["labelE", "task_id"])

    def process_stream(self, fl: BytesIO, outfile: TextIO) -> None:
        """Process a stream of Kythe entries and output them to a GraphML file."""

        try:
            fw = GraphWriter(self.task_id)
            with Pool() as p:
                nodes: dict[str, Node] = dict()
                edges: list[Edge] = list()

                for res in p.imap_unordered(
                    fw.write_entry,
                    chunk_data(self.iterate_over_entries(fl), ENTRY_CHUNK_SIZE),
                    chunksize=3,
                ):
                    for node_props in res.node_props:
                        self.node_properties.add(node_props)
                    for edge_props in res.edge_props:
                        self.edge_properties.add(edge_props)
                    for node in res.nodes:
                        if node.id in nodes:
                            nodes[node.id].properties.update(node.properties)
                        else:
                            nodes[node.id] = node
                    for edge in res.edges:
                        edges.append(edge)
            self.to_graphml(outfile, nodes, edges)

        except Exception as e:
            logger.error("Exception occurred: %s", e)
            raise e

    def iterate_over_entries(self, fl: BytesIO) -> Generator[bytes, None, None]:
        """Iterate over entries in the stream."""

        # Indexers emit a delimited stream of entry protobufs
        # From: https://kythe.io/examples/#indexing-compilations
        while True:
            try:
                yield self.next_entry(fl)
            # This is the end of the stream. This error is expected.
            except EOFError:
                break
            except Exception as e:
                raise e

    def next_entry(self, fl: BytesIO) -> bytes:
        """Parse a Kythe entry from the stream."""

        # Read the size of the entry protobuf
        sz = decode_stream(fl)
        bts = bytes()
        while len(bts) < sz:
            rd = fl.read(sz - len(bts))
            if len(rd) <= 0:
                return b""
            bts += rd
        return bts

    def parse_entry(self, bts: bytes) -> Entry:
        """Parse a Kythe entry from a bytes object."""
        ent = Entry()
        ent.ParseFromString(bts)
        return ent

    def parse_entries(self, fl: BytesIO) -> Generator[Entry, None, None]:
        """Parse a stream of Kythe entries from a file."""
        while True:
            bts = self.next_entry(fl)
            if bts == b"":
                break
            yield self.parse_entry(bts)

    def to_graphml(
        self, outfile: TextIO, nodes: Dict[str, Node], edges: List[Edge]
    ) -> None:
        """Convert graph to a GraphML file.
        From: https://tinkerpop.apache.org/docs/3.7.3/dev/io/
        """
        outfile.write('<?xml version="1.0" encoding="UTF-8"?>\n')
        outfile.write(
            '<graphml xmlns="http://graphml.graphdrawing.org/xmlns" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:schemaLocation="http://graphml.graphdrawing.org/xmlns http://graphml.graphdrawing.org/xmlns/1.1/graphml.xsd">\n'
        )
        outfile.write('<graph id="G" edgedefault="directed">\n')

        # Output node properties
        for p in self.node_properties:
            outfile.write(
                f'<key id="{p}" for="node" attr.name="{p}" attr.type="string" />\n'
            )

        # Output edge properties
        for p in self.edge_properties:
            outfile.write(
                f'<key id="{p}" for="edge" attr.name="{p}" attr.type="string" />\n'
            )

        # Output node contents
        id_set = set()
        for id_name, node in nodes.items():
            id_set.add(id_name)
            outfile.write(node.to_graphml())

        # Output edge contents
        for edge in edges:
            if edge.source_id in id_set and edge.target_id in id_set:
                outfile.write(edge.to_graphml())

        outfile.write("</graph>")
        outfile.write("</graphml>")
