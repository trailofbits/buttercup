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
