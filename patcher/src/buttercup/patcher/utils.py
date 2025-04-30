"""Various utility functions for the patching engine."""

import re
from typing import Any

from langchain_core.exceptions import OutputParserException
from langchain_core.messages import AIMessage
from langchain_core.runnables import Runnable, RunnableConfig
from buttercup.common.challenge_task import ChallengeTask
from typing import Callable
from pathlib import Path
from pydantic import BaseModel

VALID_PATCH_EXTENSIONS = (".c", ".h", ".in", ".java")

CHAIN_CALL_TYPE = Callable[[Callable, Runnable, dict[str, Any], RunnableConfig | None, Any], Any]


class PatchInput(BaseModel):
    """Input for the patching process."""

    challenge_task_dir: Path
    task_id: str
    submission_index: str
    harness_name: str
    engine: str
    sanitizer: str
    pov: Path
    pov_token: str
    pov_variants_path: Path
    sanitizer_output: str | None = None

    def __getitem__(self, key: str) -> Any:
        return self.get(key)

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)


class PatchOutput(BaseModel):
    """Output for the Patch Agent."""

    task_id: str
    submission_index: str
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


def get_diff_content(challenge: ChallengeTask) -> str:
    """Get the diff content for the challenge."""
    return "\n".join(diff.read_text() for diff in challenge.get_diffs())


def _map_container_path_to_local_path(challenge: ChallengeTask, file_path: Path) -> Path:
    """Map a container path (e.g. /src/libjpeg-turbo/jcapimin.c) to a path
    relative to the challenge source (e.g. jcapimin.c)."""
    if not file_path.is_absolute():
        file_path = challenge.workdir_from_dockerfile().joinpath(file_path).resolve()

    if file_path.parts[1] != "src":
        return None

    if len(file_path.parts) < 3:
        return None

    rel_path = Path(*file_path.parts[3:])
    rel_challenge_path = challenge.get_source_path().joinpath(rel_path)
    if not rel_challenge_path.exists():
        return None

    return rel_path


def find_file_in_source_dir(challenge: ChallengeTask, file_path: Path) -> Path | None:
    """Find a file path in the challenge source directory."""

    def _check_file_path(file_path: Path) -> Path | None:
        rel_path = _map_container_path_to_local_path(challenge, file_path)
        if rel_path:
            return rel_path

    # Strategy 1: Path as is
    res = _check_file_path(file_path)
    if res:
        return res

    # Strategy 2: Just prefix `/` to the path
    if not file_path.is_absolute():
        res = _check_file_path(Path("/" + file_path.as_posix()))
        if res:
            return res

    # # Strategy 3: Search recursively in source directory
    if file_path.is_absolute():
        file_path = file_path.relative_to(Path("/"))

    res = list(challenge.get_source_path().rglob(file_path.as_posix()))
    if res:
        return res[0].relative_to(challenge.get_source_path())

    return None
