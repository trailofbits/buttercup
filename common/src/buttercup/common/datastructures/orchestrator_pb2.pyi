from google.protobuf.internal import containers as _containers
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from typing import ClassVar as _ClassVar, Iterable as _Iterable, Mapping as _Mapping, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class Patch(_message.Message):
    __slots__ = ["patch", "task_id", "vulnerability_id"]
    PATCH_FIELD_NUMBER: _ClassVar[int]
    TASK_ID_FIELD_NUMBER: _ClassVar[int]
    VULNERABILITY_ID_FIELD_NUMBER: _ClassVar[int]
    patch: str
    task_id: str
    vulnerability_id: str
    def __init__(self, task_id: _Optional[str] = ..., vulnerability_id: _Optional[str] = ..., patch: _Optional[str] = ...) -> None: ...

class SourceDetail(_message.Message):
    __slots__ = ["path", "sha256", "source_type", "url"]
    class SourceType(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = []
    PATH_FIELD_NUMBER: _ClassVar[int]
    SHA256_FIELD_NUMBER: _ClassVar[int]
    SOURCE_TYPE_DIFF: SourceDetail.SourceType
    SOURCE_TYPE_FIELD_NUMBER: _ClassVar[int]
    SOURCE_TYPE_FUZZ_TOOLING: SourceDetail.SourceType
    SOURCE_TYPE_REPO: SourceDetail.SourceType
    URL_FIELD_NUMBER: _ClassVar[int]
    path: str
    sha256: str
    source_type: SourceDetail.SourceType
    url: str
    def __init__(self, sha256: _Optional[str] = ..., source_type: _Optional[_Union[SourceDetail.SourceType, str]] = ..., url: _Optional[str] = ..., path: _Optional[str] = ...) -> None: ...

class Task(_message.Message):
    __slots__ = ["cancelled", "deadline", "message_id", "message_time", "sources", "task_id", "task_type"]
    class TaskType(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = []
    CANCELLED_FIELD_NUMBER: _ClassVar[int]
    DEADLINE_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_ID_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_TIME_FIELD_NUMBER: _ClassVar[int]
    SOURCES_FIELD_NUMBER: _ClassVar[int]
    TASK_ID_FIELD_NUMBER: _ClassVar[int]
    TASK_TYPE_DELTA: Task.TaskType
    TASK_TYPE_FIELD_NUMBER: _ClassVar[int]
    TASK_TYPE_FULL: Task.TaskType
    cancelled: bool
    deadline: int
    message_id: str
    message_time: int
    sources: _containers.RepeatedCompositeFieldContainer[SourceDetail]
    task_id: str
    task_type: Task.TaskType
    def __init__(self, message_id: _Optional[str] = ..., message_time: _Optional[int] = ..., task_id: _Optional[str] = ..., task_type: _Optional[_Union[Task.TaskType, str]] = ..., sources: _Optional[_Iterable[_Union[SourceDetail, _Mapping]]] = ..., deadline: _Optional[int] = ..., cancelled: bool = ...) -> None: ...

class TaskDelete(_message.Message):
    __slots__ = ["received_at", "task_id"]
    RECEIVED_AT_FIELD_NUMBER: _ClassVar[int]
    TASK_ID_FIELD_NUMBER: _ClassVar[int]
    received_at: float
    task_id: str
    def __init__(self, task_id: _Optional[str] = ..., received_at: _Optional[float] = ...) -> None: ...

class TaskDownload(_message.Message):
    __slots__ = ["task"]
    TASK_FIELD_NUMBER: _ClassVar[int]
    task: Task
    def __init__(self, task: _Optional[_Union[Task, _Mapping]] = ...) -> None: ...

class TaskReady(_message.Message):
    __slots__ = ["task"]
    TASK_FIELD_NUMBER: _ClassVar[int]
    task: Task
    def __init__(self, task: _Optional[_Union[Task, _Mapping]] = ...) -> None: ...

class TaskVulnerability(_message.Message):
    __slots__ = ["architecture", "data_file", "harness_path", "package_name", "sanitizer", "task_id", "vulnerability_id"]
    ARCHITECTURE_FIELD_NUMBER: _ClassVar[int]
    DATA_FILE_FIELD_NUMBER: _ClassVar[int]
    HARNESS_PATH_FIELD_NUMBER: _ClassVar[int]
    PACKAGE_NAME_FIELD_NUMBER: _ClassVar[int]
    SANITIZER_FIELD_NUMBER: _ClassVar[int]
    TASK_ID_FIELD_NUMBER: _ClassVar[int]
    VULNERABILITY_ID_FIELD_NUMBER: _ClassVar[int]
    architecture: str
    data_file: str
    harness_path: str
    package_name: str
    sanitizer: str
    task_id: str
    vulnerability_id: str
    def __init__(self, task_id: _Optional[str] = ..., vulnerability_id: _Optional[str] = ..., package_name: _Optional[str] = ..., sanitizer: _Optional[str] = ..., harness_path: _Optional[str] = ..., data_file: _Optional[str] = ..., architecture: _Optional[str] = ...) -> None: ...
