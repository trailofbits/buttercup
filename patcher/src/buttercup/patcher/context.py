from dataclasses import dataclass
from typing import TypedDict, NotRequired


@dataclass
class ContextCodeSnippet(TypedDict):
    """Code snippet for ContextOutput."""

    file_path: str
    "Path to the vulnerable file, relative to (CP path / 'src')"

    function_name: NotRequired[str]
    "Name of the vulnerable function related to changed_lines"

    code: NotRequired[str]
    "Code of the vulnerable function"

    code_context: NotRequired[str]
    "Additional code context around the vulnerable line/code"


@dataclass
class ContextLineSnippet(TypedDict):
    """Line snippet for ContextOutput."""

    file_path: str
    "Path to the vulnerable file, relative to (CP path / 'src')"

    add_lines: list[int]
    "Lines added/moved to file_path in a commit. (0-based)"

    del_lines: list[int]
    "Lines removed to file_path in a commit. (0-based)"
