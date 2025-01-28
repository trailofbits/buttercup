from buttercup.program_model.data.kythe.proto.storage_pb2 import Entry, VName
from buttercup.program_model.utils.varint import decode_stream
from typing import Generator
from io import BytesIO
from gremlin_python.structure.graph import Graph, GraphTraversalSource
from gremlin_python.driver.driver_remote_connection import DriverRemoteConnection
from gremlin_python.driver.client import Client
from gremlin_python.driver.serializer import GraphSONSerializersV3d0
from dataclasses import dataclass
import urllib
from gremlin_python.structure.graph import Vertex
import sys
import argparse
from collections import defaultdict


@dataclass(frozen=True, repr=False)
class KytheURI:
    signature: str
    corpus: str
    root: str
    path: str
    language: str

    def __str__(self):
        lst = [self.signature, self.corpus, self.root, self.path, self.language]
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


def is_edge(ent: Entry) -> bool:
    """Check if the entry is an edge."""
    return ent.edge_kind != ""


def convert_node(trv: GraphTraversalSource, nd: VName) -> Vertex:
    """Convert a Kythe node to a JanusGraph vertex."""
    uri = str(KytheURI.from_vname(nd))

    # Return node if it already exists
    maybe_node = next(trv.V().has('uri', uri), None)
    if maybe_node is not None:
        return maybe_node

    # Create a new node
    return trv.add_v('node').property('uri', uri).next()


class JanusStorage:
    """Class to interact with JanusGraph."""

    def __init__(self, url: str):
        self.connection = DriverRemoteConnection(
                            url, 
                            traversal_source="g",
                            message_serializer=GraphSONSerializersV3d0()
                          )
        self.graph = Graph()
        self.g = self.graph.traversal().with_remote(self.connection)

        # TODO(Evan): We'll only need to do this once.
        # Add index
        # From: https://docs.janusgraph.org/schema/index-management/index-performance/
        client = Client(url, "g")
        gremlin_script = """
        mgmt = graph.openManagement()
        uriKey = mgmt.makePropertyKey('uri').dataType(String.class).make()
        mgmt.addIndexKey(uriKey)
        mgmt.commit();
        """
        client.submit(gremlin_script)
        client.close()

    def process_stream(self, _project_name: str, fl: BytesIO):
        """Process a stream of Kythe entries and add them to JanusGraph."""
        tx = self.g.tx()
        trv = tx.begin()

        try:
            for e, entry in enumerate(iterate_over_entries(fl)):
                sys.stdout.write(f"Parsing entry {e}\r")
                sys.stdout.flush()

                # Convert source node
                source = convert_node(trv, entry.source)

                if is_edge(entry):
                    # Convert target node
                    target = convert_node(trv, entry.target)

                    # Add edge between source and target
                    trv.add_e(entry.edge_kind).from_(source).to(target).property(entry.fact_name, entry.fact_value.decode()).iterate()
                else:
                    # Update property of node
                    trv.V(source.id).property(entry.fact_name, entry.fact_value.decode()).iterate()

            tx.commit()
        except Exception as e:
            tx.rollback()
            print(f"Exception occurred: {e}")
            raise e
        finally:
            self.connection.close()
            sys.stdout.write("\n")
            sys.stdout.flush()

    def clear_graph(self):
        """Remove all vertices and edges from the graph."""
        self.g.V().drop().iterate()


def iterate_over_entries(fl: BytesIO) -> Generator[Entry, None, None]:
    """Iterate over entries in the stream."""

    # Indexers emit a delimited stream of entry protobufs
    # From: https://kythe.io/examples/#indexing-compilations
    while True:
        try:
            yield parse_entry(fl)
        # This is the end of the stream. This error is expected.
        except EOFError:
            break
        except Exception as e:
            print("Exception: ", e)
            break


def parse_entry(fl: BytesIO) -> Entry:
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


def main():
    prsr = argparse.ArgumentParser("Entry Upload to Janus")
    prsr.add_argument("--url", required=True)
    args = prsr.parse_args()

    storage = JanusStorage(args.url)

    # NOTE(Evan): Leaving this here for now for testing.
    storage.clear_graph()
    print("Cleared graph")

    with sys.stdin.buffer as f:
        storage.process_stream("", f)


if __name__ == "__main__":
    main()
