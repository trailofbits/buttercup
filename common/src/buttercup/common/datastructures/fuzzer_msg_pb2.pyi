from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from typing import ClassVar as _ClassVar, Mapping as _Mapping, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class BuildOutput(_message.Message):
    __slots__ = ["engine", "output_ossfuzz_path", "package_name", "sanitizer"]
    ENGINE_FIELD_NUMBER: _ClassVar[int]
    OUTPUT_OSSFUZZ_PATH_FIELD_NUMBER: _ClassVar[int]
    PACKAGE_NAME_FIELD_NUMBER: _ClassVar[int]
    SANITIZER_FIELD_NUMBER: _ClassVar[int]
    engine: str
    output_ossfuzz_path: str
    package_name: str
    sanitizer: str
    def __init__(self, package_name: _Optional[str] = ..., engine: _Optional[str] = ..., sanitizer: _Optional[str] = ..., output_ossfuzz_path: _Optional[str] = ...) -> None: ...

class BuildRequest(_message.Message):
    __slots__ = ["engine", "ossfuzz", "package_name", "sanitizer"]
    ENGINE_FIELD_NUMBER: _ClassVar[int]
    OSSFUZZ_FIELD_NUMBER: _ClassVar[int]
    PACKAGE_NAME_FIELD_NUMBER: _ClassVar[int]
    SANITIZER_FIELD_NUMBER: _ClassVar[int]
    engine: str
    ossfuzz: str
    package_name: str
    sanitizer: str
    def __init__(self, package_name: _Optional[str] = ..., engine: _Optional[str] = ..., sanitizer: _Optional[str] = ..., ossfuzz: _Optional[str] = ...) -> None: ...

class WeightedTarget(_message.Message):
    __slots__ = ["harness_path", "target", "weight"]
    HARNESS_PATH_FIELD_NUMBER: _ClassVar[int]
    TARGET_FIELD_NUMBER: _ClassVar[int]
    WEIGHT_FIELD_NUMBER: _ClassVar[int]
    harness_path: str
    target: BuildOutput
    weight: float
    def __init__(self, weight: _Optional[float] = ..., target: _Optional[_Union[BuildOutput, _Mapping]] = ..., harness_path: _Optional[str] = ...) -> None: ...
