from __future__ import annotations

from enum import Enum
from typing import Dict, List
from pydantic import BaseModel


class SourceType(str, Enum):
    repo = "repo"
    fuzz_tooling = "fuzz-tooling"
    diff = "diff"


class TaskType(str, Enum):
    full = "full"
    delta = "delta"


class SourceDetail(BaseModel):
    sha256: str
    type: SourceType
    url: str


class TaskDetail(BaseModel):
    deadline: int
    focus: str
    harnesses_included: bool
    metadata: Dict[str, str]
    project_name: str
    source: List[SourceDetail]
    task_id: str
    type: TaskType


class Task(BaseModel):
    message_id: str
    message_time: int
    tasks: List[TaskDetail]
