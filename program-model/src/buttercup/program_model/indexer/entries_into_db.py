from buttercup.program_model.data.kythe.proto.storage_pb2 import Entry, VName
from buttercup.program_model.utils.varint import decode_stream
from typing import Generator
from io import BytesIO
from gremlin_python.structure.graph import Graph, GraphTraversalSource
from gremlin_python.driver.driver_remote_connection import DriverRemoteConnection
from dataclasses import dataclass
import urllib
from gremlin_python.structure.graph import Vertex
import sys
import argparse


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
    return ent.edge_kind != ""


def convert_node(trv: GraphTraversalSource, nd: VName) -> Vertex:
    ur = KytheURI.from_vname(nd)
    s = str(ur)
    print(s)
    maybe_nd = next(trv.V().has_label(s), None)
    if maybe_nd is not None:
        return maybe_nd

    return trv.add_v(str(ur)).next()


class JanusStorage:
    def __init__(self, url: str):
        self.connection = DriverRemoteConnection(url, traversal_source="g")
        self.graph = Graph()
        self.g = self.graph.traversal().with_remote(self.connection)
        next(self.g.V().has_label("x"), None)

    def process_stream(self, _project_name: str, fl: BytesIO):
        next(self.g.V().has_label("x"), None)
        tx = self.g.tx()
        trv = tx.begin()
        for ent in iterate_over_entries(fl):
            next(trv.V().has_label("x"), None)
            if is_edge(ent):
                n1 = convert_node(trv, ent.source)
                n2 = convert_node(trv, ent.target)
                trv.add_e().from_(n1).to(n2).property(
                    "edge_kind", ent.edge_kind
                ).iterate()
            else:
                n1 = convert_node(trv, ent.source)
                trv.V().has_id(n1.id).property(
                    ent.fact_name, ent.fact_value.decode()
                ).iterate()
        tx.commit()


def iterate_over_entries(fl: BytesIO) -> Generator[Entry, None, None]:
    try:
        sz = decode_stream(fl)
        bts = bytes()
        while len(bts) < sz:
            rd = fl.read(sz - len(bts))
            if len(rd) <= 0:
                return None
            bts += rd
        ent = Entry()
        ent.ParseFromString(bts)
        yield ent
    except EOFError:
        return None
    except Exception:
        # TODO(Ian) should catch decode errors
        return None


def main():
    prsr = argparse.ArgumentParser("Entry Upload to Janus")
    prsr.add_argument("--url", required=True)
    args = prsr.parse_args()

    storage = JanusStorage(args.url)
    with sys.stdin.buffer as f:
        storage.process_stream("", f)


if __name__ == "__main__":
    main()
