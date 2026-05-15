from google.protobuf.internal import containers as _containers
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class BuildType(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    FUZZER: _ClassVar[BuildType]
    COVERAGE: _ClassVar[BuildType]
    TRACER_NO_DIFF: _ClassVar[BuildType]
    PATCH: _ClassVar[BuildType]

class SubmissionResult(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    NONE: _ClassVar[SubmissionResult]
    ACCEPTED: _ClassVar[SubmissionResult]
    PASSED: _ClassVar[SubmissionResult]
    FAILED: _ClassVar[SubmissionResult]
    DEADLINE_EXCEEDED: _ClassVar[SubmissionResult]
    ERRORED: _ClassVar[SubmissionResult]
    INCONCLUSIVE: _ClassVar[SubmissionResult]
FUZZER: BuildType
COVERAGE: BuildType
TRACER_NO_DIFF: BuildType
PATCH: BuildType
NONE: SubmissionResult
ACCEPTED: SubmissionResult
PASSED: SubmissionResult
FAILED: SubmissionResult
DEADLINE_EXCEEDED: SubmissionResult
ERRORED: SubmissionResult
INCONCLUSIVE: SubmissionResult

class Task(_message.Message):
    __slots__ = ("message_id", "message_time", "task_id", "task_type", "sources", "deadline", "cancelled", "project_name", "focus", "metadata")
    class TaskType(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = ()
        TASK_TYPE_FULL: _ClassVar[Task.TaskType]
        TASK_TYPE_DELTA: _ClassVar[Task.TaskType]
    TASK_TYPE_FULL: Task.TaskType
    TASK_TYPE_DELTA: Task.TaskType
    class MetadataEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: str
        def __init__(self, key: _Optional[str] = ..., value: _Optional[str] = ...) -> None: ...
    MESSAGE_ID_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_TIME_FIELD_NUMBER: _ClassVar[int]
    TASK_ID_FIELD_NUMBER: _ClassVar[int]
    TASK_TYPE_FIELD_NUMBER: _ClassVar[int]
    SOURCES_FIELD_NUMBER: _ClassVar[int]
    DEADLINE_FIELD_NUMBER: _ClassVar[int]
    CANCELLED_FIELD_NUMBER: _ClassVar[int]
    PROJECT_NAME_FIELD_NUMBER: _ClassVar[int]
    FOCUS_FIELD_NUMBER: _ClassVar[int]
    METADATA_FIELD_NUMBER: _ClassVar[int]
    message_id: str
    message_time: int
    task_id: str
    task_type: Task.TaskType
    sources: _containers.RepeatedCompositeFieldContainer[SourceDetail]
    deadline: int
    cancelled: bool
    project_name: str
    focus: str
    metadata: _containers.ScalarMap[str, str]
    def __init__(self, message_id: _Optional[str] = ..., message_time: _Optional[int] = ..., task_id: _Optional[str] = ..., task_type: _Optional[_Union[Task.TaskType, str]] = ..., sources: _Optional[_Iterable[_Union[SourceDetail, _Mapping]]] = ..., deadline: _Optional[int] = ..., cancelled: bool = ..., project_name: _Optional[str] = ..., focus: _Optional[str] = ..., metadata: _Optional[_Mapping[str, str]] = ...) -> None: ...

class SourceDetail(_message.Message):
    __slots__ = ("sha256", "source_type", "url")
    class SourceType(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = ()
        SOURCE_TYPE_REPO: _ClassVar[SourceDetail.SourceType]
        SOURCE_TYPE_FUZZ_TOOLING: _ClassVar[SourceDetail.SourceType]
        SOURCE_TYPE_DIFF: _ClassVar[SourceDetail.SourceType]
    SOURCE_TYPE_REPO: SourceDetail.SourceType
    SOURCE_TYPE_FUZZ_TOOLING: SourceDetail.SourceType
    SOURCE_TYPE_DIFF: SourceDetail.SourceType
    SHA256_FIELD_NUMBER: _ClassVar[int]
    SOURCE_TYPE_FIELD_NUMBER: _ClassVar[int]
    URL_FIELD_NUMBER: _ClassVar[int]
    sha256: str
    source_type: SourceDetail.SourceType
    url: str
    def __init__(self, sha256: _Optional[str] = ..., source_type: _Optional[_Union[SourceDetail.SourceType, str]] = ..., url: _Optional[str] = ...) -> None: ...

class TaskDownload(_message.Message):
    __slots__ = ("task",)
    TASK_FIELD_NUMBER: _ClassVar[int]
    task: Task
    def __init__(self, task: _Optional[_Union[Task, _Mapping]] = ...) -> None: ...

class TaskReady(_message.Message):
    __slots__ = ("task",)
    TASK_FIELD_NUMBER: _ClassVar[int]
    task: Task
    def __init__(self, task: _Optional[_Union[Task, _Mapping]] = ...) -> None: ...

class TaskDelete(_message.Message):
    __slots__ = ("task_id", "all", "received_at")
    TASK_ID_FIELD_NUMBER: _ClassVar[int]
    ALL_FIELD_NUMBER: _ClassVar[int]
    RECEIVED_AT_FIELD_NUMBER: _ClassVar[int]
    task_id: str
    all: bool
    received_at: float
    def __init__(self, task_id: _Optional[str] = ..., all: bool = ..., received_at: _Optional[float] = ...) -> None: ...

class BuildRequest(_message.Message):
    __slots__ = ("engine", "sanitizer", "task_dir", "task_id", "build_type", "apply_diff", "patch", "internal_patch_id")
    ENGINE_FIELD_NUMBER: _ClassVar[int]
    SANITIZER_FIELD_NUMBER: _ClassVar[int]
    TASK_DIR_FIELD_NUMBER: _ClassVar[int]
    TASK_ID_FIELD_NUMBER: _ClassVar[int]
    BUILD_TYPE_FIELD_NUMBER: _ClassVar[int]
    APPLY_DIFF_FIELD_NUMBER: _ClassVar[int]
    PATCH_FIELD_NUMBER: _ClassVar[int]
    INTERNAL_PATCH_ID_FIELD_NUMBER: _ClassVar[int]
    engine: str
    sanitizer: str
    task_dir: str
    task_id: str
    build_type: BuildType
    apply_diff: bool
    patch: str
    internal_patch_id: str
    def __init__(self, engine: _Optional[str] = ..., sanitizer: _Optional[str] = ..., task_dir: _Optional[str] = ..., task_id: _Optional[str] = ..., build_type: _Optional[_Union[BuildType, str]] = ..., apply_diff: bool = ..., patch: _Optional[str] = ..., internal_patch_id: _Optional[str] = ...) -> None: ...

class BuildOutput(_message.Message):
    __slots__ = ("engine", "sanitizer", "task_dir", "task_id", "build_type", "apply_diff", "internal_patch_id")
    ENGINE_FIELD_NUMBER: _ClassVar[int]
    SANITIZER_FIELD_NUMBER: _ClassVar[int]
    TASK_DIR_FIELD_NUMBER: _ClassVar[int]
    TASK_ID_FIELD_NUMBER: _ClassVar[int]
    BUILD_TYPE_FIELD_NUMBER: _ClassVar[int]
    APPLY_DIFF_FIELD_NUMBER: _ClassVar[int]
    INTERNAL_PATCH_ID_FIELD_NUMBER: _ClassVar[int]
    engine: str
    sanitizer: str
    task_dir: str
    task_id: str
    build_type: BuildType
    apply_diff: bool
    internal_patch_id: str
    def __init__(self, engine: _Optional[str] = ..., sanitizer: _Optional[str] = ..., task_dir: _Optional[str] = ..., task_id: _Optional[str] = ..., build_type: _Optional[_Union[BuildType, str]] = ..., apply_diff: bool = ..., internal_patch_id: _Optional[str] = ...) -> None: ...

class WeightedHarness(_message.Message):
    __slots__ = ("weight", "package_name", "harness_name", "task_id")
    WEIGHT_FIELD_NUMBER: _ClassVar[int]
    PACKAGE_NAME_FIELD_NUMBER: _ClassVar[int]
    HARNESS_NAME_FIELD_NUMBER: _ClassVar[int]
    TASK_ID_FIELD_NUMBER: _ClassVar[int]
    weight: float
    package_name: str
    harness_name: str
    task_id: str
    def __init__(self, weight: _Optional[float] = ..., package_name: _Optional[str] = ..., harness_name: _Optional[str] = ..., task_id: _Optional[str] = ...) -> None: ...

class Crash(_message.Message):
    __slots__ = ("target", "harness_name", "crash_input_path", "stacktrace", "crash_token")
    TARGET_FIELD_NUMBER: _ClassVar[int]
    HARNESS_NAME_FIELD_NUMBER: _ClassVar[int]
    CRASH_INPUT_PATH_FIELD_NUMBER: _ClassVar[int]
    STACKTRACE_FIELD_NUMBER: _ClassVar[int]
    CRASH_TOKEN_FIELD_NUMBER: _ClassVar[int]
    target: BuildOutput
    harness_name: str
    crash_input_path: str
    stacktrace: str
    crash_token: str
    def __init__(self, target: _Optional[_Union[BuildOutput, _Mapping]] = ..., harness_name: _Optional[str] = ..., crash_input_path: _Optional[str] = ..., stacktrace: _Optional[str] = ..., crash_token: _Optional[str] = ...) -> None: ...

class TracedCrash(_message.Message):
    __slots__ = ("crash", "tracer_stacktrace")
    CRASH_FIELD_NUMBER: _ClassVar[int]
    TRACER_STACKTRACE_FIELD_NUMBER: _ClassVar[int]
    crash: Crash
    tracer_stacktrace: str
    def __init__(self, crash: _Optional[_Union[Crash, _Mapping]] = ..., tracer_stacktrace: _Optional[str] = ...) -> None: ...

class ConfirmedVulnerability(_message.Message):
    __slots__ = ("crashes", "internal_patch_id")
    CRASHES_FIELD_NUMBER: _ClassVar[int]
    INTERNAL_PATCH_ID_FIELD_NUMBER: _ClassVar[int]
    crashes: _containers.RepeatedCompositeFieldContainer[TracedCrash]
    internal_patch_id: str
    def __init__(self, crashes: _Optional[_Iterable[_Union[TracedCrash, _Mapping]]] = ..., internal_patch_id: _Optional[str] = ...) -> None: ...

class Patch(_message.Message):
    __slots__ = ("task_id", "internal_patch_id", "patch")
    TASK_ID_FIELD_NUMBER: _ClassVar[int]
    INTERNAL_PATCH_ID_FIELD_NUMBER: _ClassVar[int]
    PATCH_FIELD_NUMBER: _ClassVar[int]
    task_id: str
    internal_patch_id: str
    patch: str
    def __init__(self, task_id: _Optional[str] = ..., internal_patch_id: _Optional[str] = ..., patch: _Optional[str] = ...) -> None: ...

class IndexRequest(_message.Message):
    __slots__ = ("build_type", "package_name", "sanitizer", "task_dir", "task_id")
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

class IndexOutput(_message.Message):
    __slots__ = ("build_type", "package_name", "sanitizer", "task_dir", "task_id")
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

class FunctionCoverage(_message.Message):
    __slots__ = ("function_name", "function_paths", "total_lines", "covered_lines")
    FUNCTION_NAME_FIELD_NUMBER: _ClassVar[int]
    FUNCTION_PATHS_FIELD_NUMBER: _ClassVar[int]
    TOTAL_LINES_FIELD_NUMBER: _ClassVar[int]
    COVERED_LINES_FIELD_NUMBER: _ClassVar[int]
    function_name: str
    function_paths: _containers.RepeatedScalarFieldContainer[str]
    total_lines: int
    covered_lines: int
    def __init__(self, function_name: _Optional[str] = ..., function_paths: _Optional[_Iterable[str]] = ..., total_lines: _Optional[int] = ..., covered_lines: _Optional[int] = ...) -> None: ...

class SubmissionEntryPatch(_message.Message):
    __slots__ = ("patch", "internal_patch_id", "competition_patch_id", "build_outputs", "result")
    PATCH_FIELD_NUMBER: _ClassVar[int]
    INTERNAL_PATCH_ID_FIELD_NUMBER: _ClassVar[int]
    COMPETITION_PATCH_ID_FIELD_NUMBER: _ClassVar[int]
    BUILD_OUTPUTS_FIELD_NUMBER: _ClassVar[int]
    RESULT_FIELD_NUMBER: _ClassVar[int]
    patch: str
    internal_patch_id: str
    competition_patch_id: str
    build_outputs: _containers.RepeatedCompositeFieldContainer[BuildOutput]
    result: SubmissionResult
    def __init__(self, patch: _Optional[str] = ..., internal_patch_id: _Optional[str] = ..., competition_patch_id: _Optional[str] = ..., build_outputs: _Optional[_Iterable[_Union[BuildOutput, _Mapping]]] = ..., result: _Optional[_Union[SubmissionResult, str]] = ...) -> None: ...

class Bundle(_message.Message):
    __slots__ = ("task_id", "competition_pov_id", "competition_patch_id", "competition_sarif_id", "bundle_id")
    TASK_ID_FIELD_NUMBER: _ClassVar[int]
    COMPETITION_POV_ID_FIELD_NUMBER: _ClassVar[int]
    COMPETITION_PATCH_ID_FIELD_NUMBER: _ClassVar[int]
    COMPETITION_SARIF_ID_FIELD_NUMBER: _ClassVar[int]
    BUNDLE_ID_FIELD_NUMBER: _ClassVar[int]
    task_id: str
    competition_pov_id: str
    competition_patch_id: str
    competition_sarif_id: str
    bundle_id: str
    def __init__(self, task_id: _Optional[str] = ..., competition_pov_id: _Optional[str] = ..., competition_patch_id: _Optional[str] = ..., competition_sarif_id: _Optional[str] = ..., bundle_id: _Optional[str] = ...) -> None: ...

class CrashWithId(_message.Message):
    __slots__ = ("crash", "competition_pov_id", "result")
    CRASH_FIELD_NUMBER: _ClassVar[int]
    COMPETITION_POV_ID_FIELD_NUMBER: _ClassVar[int]
    RESULT_FIELD_NUMBER: _ClassVar[int]
    crash: TracedCrash
    competition_pov_id: str
    result: SubmissionResult
    def __init__(self, crash: _Optional[_Union[TracedCrash, _Mapping]] = ..., competition_pov_id: _Optional[str] = ..., result: _Optional[_Union[SubmissionResult, str]] = ...) -> None: ...

class SubmissionEntry(_message.Message):
    __slots__ = ("stop", "crashes", "bundles", "patches", "patch_idx", "patch_submission_attempts")
    STOP_FIELD_NUMBER: _ClassVar[int]
    CRASHES_FIELD_NUMBER: _ClassVar[int]
    BUNDLES_FIELD_NUMBER: _ClassVar[int]
    PATCHES_FIELD_NUMBER: _ClassVar[int]
    PATCH_IDX_FIELD_NUMBER: _ClassVar[int]
    PATCH_SUBMISSION_ATTEMPTS_FIELD_NUMBER: _ClassVar[int]
    stop: bool
    crashes: _containers.RepeatedCompositeFieldContainer[CrashWithId]
    bundles: _containers.RepeatedCompositeFieldContainer[Bundle]
    patches: _containers.RepeatedCompositeFieldContainer[SubmissionEntryPatch]
    patch_idx: int
    patch_submission_attempts: int
    def __init__(self, stop: bool = ..., crashes: _Optional[_Iterable[_Union[CrashWithId, _Mapping]]] = ..., bundles: _Optional[_Iterable[_Union[Bundle, _Mapping]]] = ..., patches: _Optional[_Iterable[_Union[SubmissionEntryPatch, _Mapping]]] = ..., patch_idx: _Optional[int] = ..., patch_submission_attempts: _Optional[int] = ...) -> None: ...

class POVReproduceRequest(_message.Message):
    __slots__ = ("task_id", "internal_patch_id", "harness_name", "sanitizer", "pov_path")
    TASK_ID_FIELD_NUMBER: _ClassVar[int]
    INTERNAL_PATCH_ID_FIELD_NUMBER: _ClassVar[int]
    HARNESS_NAME_FIELD_NUMBER: _ClassVar[int]
    SANITIZER_FIELD_NUMBER: _ClassVar[int]
    POV_PATH_FIELD_NUMBER: _ClassVar[int]
    task_id: str
    internal_patch_id: str
    harness_name: str
    sanitizer: str
    pov_path: str
    def __init__(self, task_id: _Optional[str] = ..., internal_patch_id: _Optional[str] = ..., harness_name: _Optional[str] = ..., sanitizer: _Optional[str] = ..., pov_path: _Optional[str] = ...) -> None: ...

class POVReproduceResponse(_message.Message):
    __slots__ = ("request", "did_crash")
    REQUEST_FIELD_NUMBER: _ClassVar[int]
    DID_CRASH_FIELD_NUMBER: _ClassVar[int]
    request: POVReproduceRequest
    did_crash: bool
    def __init__(self, request: _Optional[_Union[POVReproduceRequest, _Mapping]] = ..., did_crash: bool = ...) -> None: ...
