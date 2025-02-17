from google.protobuf.internal import containers as _containers
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from typing import ClassVar as _ClassVar, Iterable as _Iterable, Mapping as _Mapping, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class BuildOutput(_message.Message):
    __slots__ = ["apply_diff", "build_type", "engine", "package_name", "sanitizer", "task_dir", "task_id"]
    APPLY_DIFF_FIELD_NUMBER: _ClassVar[int]
    BUILD_TYPE_FIELD_NUMBER: _ClassVar[int]
    ENGINE_FIELD_NUMBER: _ClassVar[int]
    PACKAGE_NAME_FIELD_NUMBER: _ClassVar[int]
    SANITIZER_FIELD_NUMBER: _ClassVar[int]
    TASK_DIR_FIELD_NUMBER: _ClassVar[int]
    TASK_ID_FIELD_NUMBER: _ClassVar[int]
    apply_diff: bool
    build_type: str
    engine: str
    package_name: str
    sanitizer: str
    task_dir: str
    task_id: str
    def __init__(self, package_name: _Optional[str] = ..., engine: _Optional[str] = ..., sanitizer: _Optional[str] = ..., task_dir: _Optional[str] = ..., task_id: _Optional[str] = ..., build_type: _Optional[str] = ..., apply_diff: bool = ...) -> None: ...

class BuildRequest(_message.Message):
    __slots__ = ["apply_diff", "build_type", "engine", "package_name", "sanitizer", "task_dir", "task_id"]
    APPLY_DIFF_FIELD_NUMBER: _ClassVar[int]
    BUILD_TYPE_FIELD_NUMBER: _ClassVar[int]
    ENGINE_FIELD_NUMBER: _ClassVar[int]
    PACKAGE_NAME_FIELD_NUMBER: _ClassVar[int]
    SANITIZER_FIELD_NUMBER: _ClassVar[int]
    TASK_DIR_FIELD_NUMBER: _ClassVar[int]
    TASK_ID_FIELD_NUMBER: _ClassVar[int]
    apply_diff: bool
    build_type: str
    engine: str
    package_name: str
    sanitizer: str
    task_dir: str
    task_id: str
    def __init__(self, package_name: _Optional[str] = ..., engine: _Optional[str] = ..., sanitizer: _Optional[str] = ..., task_dir: _Optional[str] = ..., task_id: _Optional[str] = ..., build_type: _Optional[str] = ..., apply_diff: bool = ...) -> None: ...

class ConfirmedVulnerability(_message.Message):
    __slots__ = ["crash", "vuln_id"]
    CRASH_FIELD_NUMBER: _ClassVar[int]
    VULN_ID_FIELD_NUMBER: _ClassVar[int]
    crash: Crash
    vuln_id: str
    def __init__(self, crash: _Optional[_Union[Crash, _Mapping]] = ..., vuln_id: _Optional[str] = ...) -> None: ...

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

class SystemState(_message.Message):
    __slots__ = ["tasks"]
    TASKS_FIELD_NUMBER: _ClassVar[int]
    tasks: TasksState
    def __init__(self, tasks: _Optional[_Union[TasksState, _Mapping]] = ...) -> None: ...

class SystemStatus(_message.Message):
    __slots__ = ["details", "ready", "state", "version"]
    class DetailsEntry(_message.Message):
        __slots__ = ["key", "value"]
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: str
        def __init__(self, key: _Optional[str] = ..., value: _Optional[str] = ...) -> None: ...
    DETAILS_FIELD_NUMBER: _ClassVar[int]
    READY_FIELD_NUMBER: _ClassVar[int]
    STATE_FIELD_NUMBER: _ClassVar[int]
    VERSION_FIELD_NUMBER: _ClassVar[int]
    details: _containers.ScalarMap[str, str]
    ready: bool
    state: SystemState
    version: str
    def __init__(self, ready: bool = ..., state: _Optional[_Union[SystemState, _Mapping]] = ..., version: _Optional[str] = ..., details: _Optional[_Mapping[str, str]] = ...) -> None: ...

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

class TasksState(_message.Message):
    __slots__ = ["canceled", "errored", "pending", "running", "succeeded"]
    CANCELED_FIELD_NUMBER: _ClassVar[int]
    ERRORED_FIELD_NUMBER: _ClassVar[int]
    PENDING_FIELD_NUMBER: _ClassVar[int]
    RUNNING_FIELD_NUMBER: _ClassVar[int]
    SUCCEEDED_FIELD_NUMBER: _ClassVar[int]
    canceled: int
    errored: int
    pending: int
    running: int
    succeeded: int
    def __init__(self, canceled: _Optional[int] = ..., errored: _Optional[int] = ..., pending: _Optional[int] = ..., running: _Optional[int] = ..., succeeded: _Optional[int] = ...) -> None: ...

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
