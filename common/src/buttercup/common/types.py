from dataclasses import dataclass


@dataclass
class FuzzConfiguration:
    corpus_dir: str
    target_path: str
    engine: str
    sanitizer: str


@dataclass
class BuildConfiguration:
    project_id: str
    engine: str
    sanitizer: str
    source_path: str | None


FUZZER_RUNNER_HEALTH_ENDPOINT = "/health"
FUZZER_RUNNER_FUZZ_ENDPOINT = "/fuzz"
FUZZER_RUNNER_MERGE_CORPUS_ENDPOINT = "/merge-corpus"
FUZZER_RUNNER_TASKS_ENDPOINT = "/tasks"
FUZZER_RUNNER_TASK_ENDPOINT = "/tasks/{task_id}"
