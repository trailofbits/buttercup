from google.protobuf.internal import containers as _containers
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from typing import ClassVar as _ClassVar, Iterable as _Iterable, Mapping as _Mapping, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class BuildOutput(_message.Message):
    __slots__ = ["apply_diff", "build_type", "engine", "sanitizer", "task_dir", "task_id"]
    APPLY_DIFF_FIELD_NUMBER: _ClassVar[int]
    BUILD_TYPE_FIELD_NUMBER: _ClassVar[int]
    ENGINE_FIELD_NUMBER: _ClassVar[int]
    SANITIZER_FIELD_NUMBER: _ClassVar[int]
    TASK_DIR_FIELD_NUMBER: _ClassVar[int]
    TASK_ID_FIELD_NUMBER: _ClassVar[int]
    apply_diff: bool
    build_type: str
    engine: str
    sanitizer: str
    task_dir: str
    task_id: str
    def __init__(self, engine: _Optional[str] = ..., sanitizer: _Optional[str] = ..., task_dir: _Optional[str] = ..., task_id: _Optional[str] = ..., build_type: _Optional[str] = ..., apply_diff: bool = ...) -> None: ...

class BuildRequest(_message.Message):
    __slots__ = ["apply_diff", "build_type", "engine", "sanitizer", "task_dir", "task_id"]
    APPLY_DIFF_FIELD_NUMBER: _ClassVar[int]
    BUILD_TYPE_FIELD_NUMBER: _ClassVar[int]
    ENGINE_FIELD_NUMBER: _ClassVar[int]
    SANITIZER_FIELD_NUMBER: _ClassVar[int]
    TASK_DIR_FIELD_NUMBER: _ClassVar[int]
    TASK_ID_FIELD_NUMBER: _ClassVar[int]
    apply_diff: bool
    build_type: str
    engine: str
    sanitizer: str
    task_dir: str
    task_id: str
    def __init__(self, engine: _Optional[str] = ..., sanitizer: _Optional[str] = ..., task_dir: _Optional[str] = ..., task_id: _Optional[str] = ..., build_type: _Optional[str] = ..., apply_diff: bool = ...) -> None: ...

class ConfirmedVulnerability(_message.Message):
    __slots__ = ["crash", "vuln_id"]
    CRASH_FIELD_NUMBER: _ClassVar[int]
    VULN_ID_FIELD_NUMBER: _ClassVar[int]
    crash: TracedCrash
    vuln_id: str
    def __init__(self, crash: _Optional[_Union[TracedCrash, _Mapping]] = ..., vuln_id: _Optional[str] = ...) -> None: ...

class Crash(_message.Message):
    __slots__ = ["crash_input_path", "harness_name", "stacktrace", "target"]
    CRASH_INPUT_PATH_FIELD_NUMBER: _ClassVar[int]
    HARNESS_NAME_FIELD_NUMBER: _ClassVar[int]
    STACKTRACE_FIELD_NUMBER: _ClassVar[int]
    TARGET_FIELD_NUMBER: _ClassVar[int]
    crash_input_path: str
    harness_name: str
    stacktrace: str
    target: BuildOutput
    def __init__(self, target: _Optional[_Union[BuildOutput, _Mapping]] = ..., harness_name: _Optional[str] = ..., crash_input_path: _Optional[str] = ..., stacktrace: _Optional[str] = ...) -> None: ...

class IndexOutput(_message.Message):
    __slots__ = ["build_type", "package_name", "sanitizer", "task_dir", "task_id"]
    BUILD_TYPE_FIELD_NUMBER: _ClassVar[int]
    PACKAGE_NAME_FIELD_NUMBER: _ClassVar[int]
    SANITIZER_FIELD_NUMBER: _ClassVar[int]
    TASK_DIR_FIELD_NUMBER: _ClassVar[int]
    TASK_ID_FIELD_NUMBER: _ClassVar[int]
    build_type: str
    package_name: str
    sanitizer: str
    task_dir: str
    task_id: str
    def __init__(self, build_type: _Optional[str] = ..., package_name: _Optional[str] = ..., sanitizer: _Optional[str] = ..., task_dir: _Optional[str] = ..., task_id: _Optional[str] = ...) -> None: ...

class IndexRequest(_message.Message):
    __slots__ = ["build_type", "package_name", "sanitizer", "task_dir", "task_id"]
    BUILD_TYPE_FIELD_NUMBER: _ClassVar[int]
    PACKAGE_NAME_FIELD_NUMBER: _ClassVar[int]
    SANITIZER_FIELD_NUMBER: _ClassVar[int]
    TASK_DIR_FIELD_NUMBER: _ClassVar[int]
    TASK_ID_FIELD_NUMBER: _ClassVar[int]
    build_type: str
    package_name: str
    sanitizer: str
    task_dir: str
    task_id: str
    def __init__(self, build_type: _Optional[str] = ..., package_name: _Optional[str] = ..., sanitizer: _Optional[str] = ..., task_dir: _Optional[str] = ..., task_id: _Optional[str] = ...) -> None: ...

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
    __slots__ = ["sha256", "source_type", "url"]
    class SourceType(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = []
    SHA256_FIELD_NUMBER: _ClassVar[int]
    SOURCE_TYPE_DIFF: SourceDetail.SourceType
    SOURCE_TYPE_FIELD_NUMBER: _ClassVar[int]
    SOURCE_TYPE_FUZZ_TOOLING: SourceDetail.SourceType
    SOURCE_TYPE_REPO: SourceDetail.SourceType
    URL_FIELD_NUMBER: _ClassVar[int]
    sha256: str
    source_type: SourceDetail.SourceType
    url: str
    def __init__(self, sha256: _Optional[str] = ..., source_type: _Optional[_Union[SourceDetail.SourceType, str]] = ..., url: _Optional[str] = ...) -> None: ...

class Task(_message.Message):
    __slots__ = ["cancelled", "deadline", "focus", "message_id", "message_time", "project_name", "sources", "task_id", "task_type"]
    class TaskType(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = []
    CANCELLED_FIELD_NUMBER: _ClassVar[int]
    DEADLINE_FIELD_NUMBER: _ClassVar[int]
    FOCUS_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_ID_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_TIME_FIELD_NUMBER: _ClassVar[int]
    PROJECT_NAME_FIELD_NUMBER: _ClassVar[int]
    SOURCES_FIELD_NUMBER: _ClassVar[int]
    TASK_ID_FIELD_NUMBER: _ClassVar[int]
    TASK_TYPE_DELTA: Task.TaskType
    TASK_TYPE_FIELD_NUMBER: _ClassVar[int]
    TASK_TYPE_FULL: Task.TaskType
    cancelled: bool
    deadline: int
    focus: str
    message_id: str
    message_time: int
    project_name: str
    sources: _containers.RepeatedCompositeFieldContainer[SourceDetail]
    task_id: str
    task_type: Task.TaskType
    def __init__(self, message_id: _Optional[str] = ..., message_time: _Optional[int] = ..., task_id: _Optional[str] = ..., task_type: _Optional[_Union[Task.TaskType, str]] = ..., sources: _Optional[_Iterable[_Union[SourceDetail, _Mapping]]] = ..., deadline: _Optional[int] = ..., cancelled: bool = ..., project_name: _Optional[str] = ..., focus: _Optional[str] = ...) -> None: ...

class TaskDelete(_message.Message):
    __slots__ = ["all", "received_at", "task_id"]
    ALL_FIELD_NUMBER: _ClassVar[int]
    RECEIVED_AT_FIELD_NUMBER: _ClassVar[int]
    TASK_ID_FIELD_NUMBER: _ClassVar[int]
    all: bool
    received_at: float
    task_id: str
    def __init__(self, task_id: _Optional[str] = ..., all: bool = ..., received_at: _Optional[float] = ...) -> None: ...

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

class TracedCrash(_message.Message):
    __slots__ = ["crash", "tracer_stacktrace"]
    CRASH_FIELD_NUMBER: _ClassVar[int]
    TRACER_STACKTRACE_FIELD_NUMBER: _ClassVar[int]
    crash: Crash
    tracer_stacktrace: str
    def __init__(self, crash: _Optional[_Union[Crash, _Mapping]] = ..., tracer_stacktrace: _Optional[str] = ...) -> None: ...

class WeightedHarness(_message.Message):
    __slots__ = ["harness_name", "package_name", "task_id", "weight"]
    HARNESS_NAME_FIELD_NUMBER: _ClassVar[int]
    PACKAGE_NAME_FIELD_NUMBER: _ClassVar[int]
    TASK_ID_FIELD_NUMBER: _ClassVar[int]
    WEIGHT_FIELD_NUMBER: _ClassVar[int]
    harness_name: str
    package_name: str
    task_id: str
    weight: float
    def __init__(self, weight: _Optional[float] = ..., package_name: _Optional[str] = ..., harness_name: _Optional[str] = ..., task_id: _Optional[str] = ...) -> None: ...
