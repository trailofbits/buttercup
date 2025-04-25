from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from typing import ClassVar as _ClassVar, Iterable as _Iterable, Mapping as _Mapping, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class CountReply(_message.Message):
    __slots__ = ["entries"]
    ENTRIES_FIELD_NUMBER: _ClassVar[int]
    entries: int
    def __init__(self, entries: _Optional[int] = ...) -> None: ...

class CountRequest(_message.Message):
    __slots__ = ["index", "shards"]
    INDEX_FIELD_NUMBER: _ClassVar[int]
    SHARDS_FIELD_NUMBER: _ClassVar[int]
    index: int
    shards: int
    def __init__(self, index: _Optional[int] = ..., shards: _Optional[int] = ...) -> None: ...

class Entries(_message.Message):
    __slots__ = ["entries"]
    ENTRIES_FIELD_NUMBER: _ClassVar[int]
    entries: _containers.RepeatedCompositeFieldContainer[Entry]
    def __init__(self, entries: _Optional[_Iterable[_Union[Entry, _Mapping]]] = ...) -> None: ...

class Entry(_message.Message):
    __slots__ = ["edge_kind", "fact_name", "fact_value", "source", "target"]
    EDGE_KIND_FIELD_NUMBER: _ClassVar[int]
    FACT_NAME_FIELD_NUMBER: _ClassVar[int]
    FACT_VALUE_FIELD_NUMBER: _ClassVar[int]
    SOURCE_FIELD_NUMBER: _ClassVar[int]
    TARGET_FIELD_NUMBER: _ClassVar[int]
    edge_kind: str
    fact_name: str
    fact_value: bytes
    source: VName
    target: VName
    def __init__(self, source: _Optional[_Union[VName, _Mapping]] = ..., edge_kind: _Optional[str] = ..., target: _Optional[_Union[VName, _Mapping]] = ..., fact_name: _Optional[str] = ..., fact_value: _Optional[bytes] = ...) -> None: ...

class ReadRequest(_message.Message):
    __slots__ = ["edge_kind", "source"]
    EDGE_KIND_FIELD_NUMBER: _ClassVar[int]
    SOURCE_FIELD_NUMBER: _ClassVar[int]
    edge_kind: str
    source: VName
    def __init__(self, source: _Optional[_Union[VName, _Mapping]] = ..., edge_kind: _Optional[str] = ...) -> None: ...

class ScanRequest(_message.Message):
    __slots__ = ["edge_kind", "fact_prefix", "target"]
    EDGE_KIND_FIELD_NUMBER: _ClassVar[int]
    FACT_PREFIX_FIELD_NUMBER: _ClassVar[int]
    TARGET_FIELD_NUMBER: _ClassVar[int]
    edge_kind: str
    fact_prefix: str
    target: VName
    def __init__(self, target: _Optional[_Union[VName, _Mapping]] = ..., edge_kind: _Optional[str] = ..., fact_prefix: _Optional[str] = ...) -> None: ...

class ShardRequest(_message.Message):
    __slots__ = ["index", "shards"]
    INDEX_FIELD_NUMBER: _ClassVar[int]
    SHARDS_FIELD_NUMBER: _ClassVar[int]
    index: int
    shards: int
    def __init__(self, index: _Optional[int] = ..., shards: _Optional[int] = ...) -> None: ...

class VName(_message.Message):
    __slots__ = ["corpus", "language", "path", "root", "signature"]
    CORPUS_FIELD_NUMBER: _ClassVar[int]
    LANGUAGE_FIELD_NUMBER: _ClassVar[int]
    PATH_FIELD_NUMBER: _ClassVar[int]
    ROOT_FIELD_NUMBER: _ClassVar[int]
    SIGNATURE_FIELD_NUMBER: _ClassVar[int]
    corpus: str
    language: str
    path: str
    root: str
    signature: str
    def __init__(self, signature: _Optional[str] = ..., corpus: _Optional[str] = ..., root: _Optional[str] = ..., path: _Optional[str] = ..., language: _Optional[str] = ...) -> None: ...

class VNameMask(_message.Message):
    __slots__ = ["corpus", "language", "path", "root", "signature"]
    CORPUS_FIELD_NUMBER: _ClassVar[int]
    LANGUAGE_FIELD_NUMBER: _ClassVar[int]
    PATH_FIELD_NUMBER: _ClassVar[int]
    ROOT_FIELD_NUMBER: _ClassVar[int]
    SIGNATURE_FIELD_NUMBER: _ClassVar[int]
    corpus: bool
    language: bool
    path: bool
    root: bool
    signature: bool
    def __init__(self, signature: bool = ..., corpus: bool = ..., root: bool = ..., path: bool = ..., language: bool = ...) -> None: ...

class VNameRewriteRule(_message.Message):
    __slots__ = ["pattern", "v_name"]
    PATTERN_FIELD_NUMBER: _ClassVar[int]
    V_NAME_FIELD_NUMBER: _ClassVar[int]
    pattern: str
    v_name: VName
    def __init__(self, pattern: _Optional[str] = ..., v_name: _Optional[_Union[VName, _Mapping]] = ...) -> None: ...

class VNameRewriteRules(_message.Message):
    __slots__ = ["rule"]
    RULE_FIELD_NUMBER: _ClassVar[int]
    rule: _containers.RepeatedCompositeFieldContainer[VNameRewriteRule]
    def __init__(self, rule: _Optional[_Iterable[_Union[VNameRewriteRule, _Mapping]]] = ...) -> None: ...

class WriteReply(_message.Message):
    __slots__: list[str] = []
    def __init__(self) -> None: ...

class WriteRequest(_message.Message):
    __slots__ = ["source", "update"]
    class Update(_message.Message):
        __slots__ = ["edge_kind", "fact_name", "fact_value", "target"]
        EDGE_KIND_FIELD_NUMBER: _ClassVar[int]
        FACT_NAME_FIELD_NUMBER: _ClassVar[int]
        FACT_VALUE_FIELD_NUMBER: _ClassVar[int]
        TARGET_FIELD_NUMBER: _ClassVar[int]
        edge_kind: str
        fact_name: str
        fact_value: bytes
        target: VName
        def __init__(self, edge_kind: _Optional[str] = ..., target: _Optional[_Union[VName, _Mapping]] = ..., fact_name: _Optional[str] = ..., fact_value: _Optional[bytes] = ...) -> None: ...
    SOURCE_FIELD_NUMBER: _ClassVar[int]
    UPDATE_FIELD_NUMBER: _ClassVar[int]
    source: VName
    update: _containers.RepeatedCompositeFieldContainer[WriteRequest.Update]
    def __init__(self, source: _Optional[_Union[VName, _Mapping]] = ..., update: _Optional[_Iterable[_Union[WriteRequest.Update, _Mapping]]] = ...) -> None: ...
