from google.protobuf.internal import containers as _containers
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from typing import ClassVar as _ClassVar, Iterable as _Iterable, Mapping as _Mapping, Optional as _Optional, Union as _Union

ACCEPTED: SubmissionResult
COVERAGE: BuildType
DEADLINE_EXCEEDED: SubmissionResult
DESCRIPTOR: _descriptor.FileDescriptor
ERRORED: SubmissionResult
FAILED: SubmissionResult
FUZZER: BuildType
INCONCLUSIVE: SubmissionResult
NONE: SubmissionResult
PASSED: SubmissionResult
PATCH: BuildType
TRACER_NO_DIFF: BuildType

class BuildOutput(_message.Message):
    __slots__ = ["apply_diff", "build_type", "engine", "internal_patch_id", "sanitizer", "task_dir", "task_id"]
    APPLY_DIFF_FIELD_NUMBER: _ClassVar[int]
    BUILD_TYPE_FIELD_NUMBER: _ClassVar[int]
    ENGINE_FIELD_NUMBER: _ClassVar[int]
    INTERNAL_PATCH_ID_FIELD_NUMBER: _ClassVar[int]
    SANITIZER_FIELD_NUMBER: _ClassVar[int]
    TASK_DIR_FIELD_NUMBER: _ClassVar[int]
    TASK_ID_FIELD_NUMBER: _ClassVar[int]
    apply_diff: bool
    build_type: BuildType
    engine: str
    internal_patch_id: str
    sanitizer: str
    task_dir: str
    task_id: str
    def __init__(self, engine: _Optional[str] = ..., sanitizer: _Optional[str] = ..., task_dir: _Optional[str] = ..., task_id: _Optional[str] = ..., build_type: _Optional[_Union[BuildType, str]] = ..., apply_diff: bool = ..., internal_patch_id: _Optional[str] = ...) -> None: ...

class BuildRequest(_message.Message):
    __slots__ = ["apply_diff", "build_type", "engine", "internal_patch_id", "patch", "sanitizer", "task_dir", "task_id"]
    APPLY_DIFF_FIELD_NUMBER: _ClassVar[int]
    BUILD_TYPE_FIELD_NUMBER: _ClassVar[int]
    ENGINE_FIELD_NUMBER: _ClassVar[int]
    INTERNAL_PATCH_ID_FIELD_NUMBER: _ClassVar[int]
    PATCH_FIELD_NUMBER: _ClassVar[int]
    SANITIZER_FIELD_NUMBER: _ClassVar[int]
    TASK_DIR_FIELD_NUMBER: _ClassVar[int]
    TASK_ID_FIELD_NUMBER: _ClassVar[int]
    apply_diff: bool
    build_type: BuildType
    engine: str
    internal_patch_id: str
    patch: str
    sanitizer: str
    task_dir: str
    task_id: str
    def __init__(self, engine: _Optional[str] = ..., sanitizer: _Optional[str] = ..., task_dir: _Optional[str] = ..., task_id: _Optional[str] = ..., build_type: _Optional[_Union[BuildType, str]] = ..., apply_diff: bool = ..., patch: _Optional[str] = ..., internal_patch_id: _Optional[str] = ...) -> None: ...

class Bundle(_message.Message):
    __slots__ = ["bundle_id", "competition_patch_id", "competition_pov_id", "competition_sarif_id", "task_id"]
    BUNDLE_ID_FIELD_NUMBER: _ClassVar[int]
    COMPETITION_PATCH_ID_FIELD_NUMBER: _ClassVar[int]
    COMPETITION_POV_ID_FIELD_NUMBER: _ClassVar[int]
    COMPETITION_SARIF_ID_FIELD_NUMBER: _ClassVar[int]
    TASK_ID_FIELD_NUMBER: _ClassVar[int]
    bundle_id: str
    competition_patch_id: str
    competition_pov_id: str
    competition_sarif_id: str
    task_id: str
    def __init__(self, task_id: _Optional[str] = ..., competition_pov_id: _Optional[str] = ..., competition_patch_id: _Optional[str] = ..., competition_sarif_id: _Optional[str] = ..., bundle_id: _Optional[str] = ...) -> None: ...

class ConfirmedVulnerability(_message.Message):
    __slots__ = ["crashes", "internal_patch_id"]
    CRASHES_FIELD_NUMBER: _ClassVar[int]
    INTERNAL_PATCH_ID_FIELD_NUMBER: _ClassVar[int]
    crashes: _containers.RepeatedCompositeFieldContainer[TracedCrash]
    internal_patch_id: str
    def __init__(self, crashes: _Optional[_Iterable[_Union[TracedCrash, _Mapping]]] = ..., internal_patch_id: _Optional[str] = ...) -> None: ...

class Crash(_message.Message):
    __slots__ = ["crash_input_path", "crash_token", "harness_name", "stacktrace", "target"]
    CRASH_INPUT_PATH_FIELD_NUMBER: _ClassVar[int]
    CRASH_TOKEN_FIELD_NUMBER: _ClassVar[int]
    HARNESS_NAME_FIELD_NUMBER: _ClassVar[int]
    STACKTRACE_FIELD_NUMBER: _ClassVar[int]
    TARGET_FIELD_NUMBER: _ClassVar[int]
    crash_input_path: str
    crash_token: str
    harness_name: str
    stacktrace: str
    target: BuildOutput
    def __init__(self, target: _Optional[_Union[BuildOutput, _Mapping]] = ..., harness_name: _Optional[str] = ..., crash_input_path: _Optional[str] = ..., stacktrace: _Optional[str] = ..., crash_token: _Optional[str] = ...) -> None: ...

class CrashWithId(_message.Message):
    __slots__ = ["competition_pov_id", "crash", "result"]
    COMPETITION_POV_ID_FIELD_NUMBER: _ClassVar[int]
    CRASH_FIELD_NUMBER: _ClassVar[int]
    RESULT_FIELD_NUMBER: _ClassVar[int]
    competition_pov_id: str
    crash: TracedCrash
    result: SubmissionResult
    def __init__(self, crash: _Optional[_Union[TracedCrash, _Mapping]] = ..., competition_pov_id: _Optional[str] = ..., result: _Optional[_Union[SubmissionResult, str]] = ...) -> None: ...

class FunctionCoverage(_message.Message):
    __slots__ = ["covered_lines", "function_name", "function_paths", "total_lines"]
    COVERED_LINES_FIELD_NUMBER: _ClassVar[int]
    FUNCTION_NAME_FIELD_NUMBER: _ClassVar[int]
    FUNCTION_PATHS_FIELD_NUMBER: _ClassVar[int]
    TOTAL_LINES_FIELD_NUMBER: _ClassVar[int]
    covered_lines: int
    function_name: str
    function_paths: _containers.RepeatedScalarFieldContainer[str]
    total_lines: int
    def __init__(self, function_name: _Optional[str] = ..., function_paths: _Optional[_Iterable[str]] = ..., total_lines: _Optional[int] = ..., covered_lines: _Optional[int] = ...) -> None: ...

class IndexOutput(_message.Message):
    __slots__ = ["build_type", "package_name", "sanitizer", "task_dir", "task_id"]
    BUILD_TYPE_FIELD_NUMBER: _ClassVar[int]
    PACKAGE_NAME_FIELD_NUMBER: _ClassVar[int]
    SANITIZER_FIELD_NUMBER: _ClassVar[int]
    TASK_DIR_FIELD_NUMBER: _ClassVar[int]
    TASK_ID_FIELD_NUMBER: _ClassVar[int]
    build_type: BuildType
    package_name: str
    sanitizer: str
    task_dir: str
    task_id: str
    def __init__(self, build_type: _Optional[_Union[BuildType, str]] = ..., package_name: _Optional[str] = ..., sanitizer: _Optional[str] = ..., task_dir: _Optional[str] = ..., task_id: _Optional[str] = ...) -> None: ...

class IndexRequest(_message.Message):
    __slots__ = ["build_type", "package_name", "sanitizer", "task_dir", "task_id"]
    BUILD_TYPE_FIELD_NUMBER: _ClassVar[int]
    PACKAGE_NAME_FIELD_NUMBER: _ClassVar[int]
    SANITIZER_FIELD_NUMBER: _ClassVar[int]
    TASK_DIR_FIELD_NUMBER: _ClassVar[int]
    TASK_ID_FIELD_NUMBER: _ClassVar[int]
    build_type: BuildType
    package_name: str
    sanitizer: str
    task_dir: str
    task_id: str
    def __init__(self, build_type: _Optional[_Union[BuildType, str]] = ..., package_name: _Optional[str] = ..., sanitizer: _Optional[str] = ..., task_dir: _Optional[str] = ..., task_id: _Optional[str] = ...) -> None: ...

class POVReproduceRequest(_message.Message):
    __slots__ = ["harness_name", "internal_patch_id", "pov_path", "sanitizer", "task_id"]
    HARNESS_NAME_FIELD_NUMBER: _ClassVar[int]
    INTERNAL_PATCH_ID_FIELD_NUMBER: _ClassVar[int]
    POV_PATH_FIELD_NUMBER: _ClassVar[int]
    SANITIZER_FIELD_NUMBER: _ClassVar[int]
    TASK_ID_FIELD_NUMBER: _ClassVar[int]
    harness_name: str
    internal_patch_id: str
    pov_path: str
    sanitizer: str
    task_id: str
    def __init__(self, task_id: _Optional[str] = ..., internal_patch_id: _Optional[str] = ..., harness_name: _Optional[str] = ..., sanitizer: _Optional[str] = ..., pov_path: _Optional[str] = ...) -> None: ...

class POVReproduceResponse(_message.Message):
    __slots__ = ["did_crash", "request"]
    DID_CRASH_FIELD_NUMBER: _ClassVar[int]
    REQUEST_FIELD_NUMBER: _ClassVar[int]
    did_crash: bool
    request: POVReproduceRequest
    def __init__(self, request: _Optional[_Union[POVReproduceRequest, _Mapping]] = ..., did_crash: bool = ...) -> None: ...

class Patch(_message.Message):
    __slots__ = ["internal_patch_id", "patch", "task_id"]
    INTERNAL_PATCH_ID_FIELD_NUMBER: _ClassVar[int]
    PATCH_FIELD_NUMBER: _ClassVar[int]
    TASK_ID_FIELD_NUMBER: _ClassVar[int]
    internal_patch_id: str
    patch: str
    task_id: str
    def __init__(self, task_id: _Optional[str] = ..., internal_patch_id: _Optional[str] = ..., patch: _Optional[str] = ...) -> None: ...

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

class SubmissionEntry(_message.Message):
    __slots__ = ["bundles", "crashes", "patch_idx", "patch_submission_attempts", "patches", "stop"]
    BUNDLES_FIELD_NUMBER: _ClassVar[int]
    CRASHES_FIELD_NUMBER: _ClassVar[int]
    PATCHES_FIELD_NUMBER: _ClassVar[int]
    PATCH_IDX_FIELD_NUMBER: _ClassVar[int]
    PATCH_SUBMISSION_ATTEMPTS_FIELD_NUMBER: _ClassVar[int]
    STOP_FIELD_NUMBER: _ClassVar[int]
    bundles: _containers.RepeatedCompositeFieldContainer[Bundle]
    crashes: _containers.RepeatedCompositeFieldContainer[CrashWithId]
    patch_idx: int
    patch_submission_attempts: int
    patches: _containers.RepeatedCompositeFieldContainer[SubmissionEntryPatch]
    stop: bool
    def __init__(self, stop: bool = ..., crashes: _Optional[_Iterable[_Union[CrashWithId, _Mapping]]] = ..., bundles: _Optional[_Iterable[_Union[Bundle, _Mapping]]] = ..., patches: _Optional[_Iterable[_Union[SubmissionEntryPatch, _Mapping]]] = ..., patch_idx: _Optional[int] = ..., patch_submission_attempts: _Optional[int] = ...) -> None: ...

class SubmissionEntryPatch(_message.Message):
    __slots__ = ["build_outputs", "competition_patch_id", "internal_patch_id", "patch", "result"]
    BUILD_OUTPUTS_FIELD_NUMBER: _ClassVar[int]
    COMPETITION_PATCH_ID_FIELD_NUMBER: _ClassVar[int]
    INTERNAL_PATCH_ID_FIELD_NUMBER: _ClassVar[int]
    PATCH_FIELD_NUMBER: _ClassVar[int]
    RESULT_FIELD_NUMBER: _ClassVar[int]
    build_outputs: _containers.RepeatedCompositeFieldContainer[BuildOutput]
    competition_patch_id: str
    internal_patch_id: str
    patch: str
    result: SubmissionResult
    def __init__(self, patch: _Optional[str] = ..., internal_patch_id: _Optional[str] = ..., competition_patch_id: _Optional[str] = ..., build_outputs: _Optional[_Iterable[_Union[BuildOutput, _Mapping]]] = ..., result: _Optional[_Union[SubmissionResult, str]] = ...) -> None: ...

class Task(_message.Message):
    __slots__ = ["cancelled", "deadline", "focus", "message_id", "message_time", "metadata", "project_name", "sources", "task_id", "task_type"]
    class TaskType(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = []
    class MetadataEntry(_message.Message):
        __slots__ = ["key", "value"]
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: str
        def __init__(self, key: _Optional[str] = ..., value: _Optional[str] = ...) -> None: ...
    CANCELLED_FIELD_NUMBER: _ClassVar[int]
    DEADLINE_FIELD_NUMBER: _ClassVar[int]
    FOCUS_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_ID_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_TIME_FIELD_NUMBER: _ClassVar[int]
    METADATA_FIELD_NUMBER: _ClassVar[int]
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
    metadata: _containers.ScalarMap[str, str]
    project_name: str
    sources: _containers.RepeatedCompositeFieldContainer[SourceDetail]
    task_id: str
    task_type: Task.TaskType
    def __init__(self, message_id: _Optional[str] = ..., message_time: _Optional[int] = ..., task_id: _Optional[str] = ..., task_type: _Optional[_Union[Task.TaskType, str]] = ..., sources: _Optional[_Iterable[_Union[SourceDetail, _Mapping]]] = ..., deadline: _Optional[int] = ..., cancelled: bool = ..., project_name: _Optional[str] = ..., focus: _Optional[str] = ..., metadata: _Optional[_Mapping[str, str]] = ...) -> None: ...

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

class BuildType(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = []

class SubmissionResult(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = []
