"""Various utility functions for the patching engine."""

import re
from typing import Any

from langchain_core.exceptions import OutputParserException
from langchain_core.messages import AIMessage
from langchain_core.runnables import Runnable, RunnableConfig
from typing import Callable
from pathlib import Path
from pydantic import BaseModel

VALID_PATCH_EXTENSIONS = (".c", ".h", ".in", ".java")

CHAIN_CALL_TYPE = Callable[[Runnable, Callable, dict[str, Any], RunnableConfig | None, Any], Any]


class PatchInput(BaseModel):
    """Input for the patching process."""

    challenge_task_dir: Path
    task_id: str
    vulnerability_id: str
    harness_name: str
    engine: str
    sanitizer: str
    pov: bytes | Path
    sanitizer_output: str | None = None

    def __getitem__(self, key: str) -> Any:
        return self.get(key)

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)


class PatchOutput(BaseModel):
    """Output for the Patch Agent."""

    task_id: str
    vulnerability_id: str
    patch: str


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
