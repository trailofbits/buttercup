"""Various utility functions for the patching engine."""

import re
from dataclasses import dataclass
from typing import Any
from pathlib import Path

from buttercup.patcher.context import ContextCodeSnippet
from langchain_core.exceptions import OutputParserException
from langchain_core.messages import AIMessage
from langchain_core.runnables import Runnable, RunnableConfig
from typing import Callable

VALID_PATCH_EXTENSIONS = (".c", ".h", ".in", ".java")

CHAIN_CALL_TYPE = Callable[[Runnable, Callable, dict[str, Any], RunnableConfig | None, Any], Any]


@dataclass
class PatchInput:
    """Input for the patching process."""

    challenge_task_dir: Path
    task_id: str
    vulnerability_id: str
    project_name: str
    harness_name: str
    engine: str
    sanitizer: str
    pov: bytes | Path
    sanitizer_output: str | None = None
    vulnerable_functions: list[ContextCodeSnippet] | None = None

    def __getitem__(self, key: str) -> Any:
        return self.get(key)

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)


def extract_md(content: AIMessage | str) -> str:
    """Extract the markdown from the AI message."""
    if isinstance(content, AIMessage):
        content = content.content  # type: ignore[assignment]

    if not isinstance(content, str):
        raise OutputParserException("extract_md: content is not a string")

    match = re.search(r"```([A-Za-z]*)\n(.*?)```", content, re.DOTALL)
    if match is not None:
        content = match.group(2)

    return content.strip("`")


def decode_bytes(b: bytes | None) -> str | None:
    """Decode bytes to string."""
    if b is None:
        return None

    return b.decode("utf-8", errors="ignore")
