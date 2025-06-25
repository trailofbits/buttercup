"""Various utility functions for the patching engine."""

import re
import random
from typing import Any, cast
from functools import lru_cache
from enum import Enum
from buttercup.program_model.codequery import CodeQueryPersistent
from langchain_core.exceptions import OutputParserException
from langchain_core.messages import AIMessage
from langchain_core.runnables import Runnable, RunnableConfig
from buttercup.common.challenge_task import ChallengeTask
from typing import Callable
from pathlib import Path
from pydantic import BaseModel

VALID_PATCH_EXTENSIONS = (".c", ".h", ".in", ".java")

CHAIN_CALL_TYPE = Callable[[Callable, Runnable, dict[str, Any], RunnableConfig | None, Any], Any]


class PatchInputPoV(BaseModel):
    challenge_task_dir: Path
    sanitizer: str
    pov: Path
    pov_token: str
    sanitizer_output: str | None = None
    engine: str
    harness_name: str


class PatchInput(BaseModel):
    """Input for the patching process."""

    task_id: str
    internal_patch_id: str
    povs: list[PatchInputPoV]

    def __getitem__(self, key: str) -> Any:
        return self.get(key)

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)


class PatchOutput(BaseModel):
    """Output for the Patch Agent."""

    task_id: str
    internal_patch_id: str
    patch: str


class TruncatePosition(str, Enum):
    """Position to truncate the output."""

    START = "start"
    MIDDLE = "middle"
    END = "end"


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


def _map_container_path_to_local_path(challenge: ChallengeTask, file_path: Path) -> Path | None:
    """Map a container path (e.g. /src/libjpeg-turbo/jcapimin.c) to a path
    relative to the challenge source (e.g. jcapimin.c)."""
    if not file_path.is_absolute():
        file_path = challenge.workdir_from_dockerfile().joinpath(file_path).resolve()

    if file_path.parts[1] != "src":
        return None

    # There should be at least 4 parts in the path:
    # - /
    # - src
    # - <src-dir>
    # - <in-src-dir-file-path>
    if len(file_path.parts) < 4:
        return None

    rel_path = Path(*file_path.parts[3:])
    rel_challenge_path = challenge.get_source_path().joinpath(rel_path)
    if not rel_challenge_path.exists():
        return None

    return rel_path


def find_file_in_source_dir(challenge: ChallengeTask, file_path: Path) -> Path | None:
    """Find a file path in the challenge source directory."""
    # Strategy 1: Path as is
    res = _map_container_path_to_local_path(challenge, file_path)
    if res:
        return res

    # Strategy 2: Just prefix `/` to the path
    if not file_path.is_absolute():
        res = _map_container_path_to_local_path(challenge, Path("/" + file_path.as_posix()))
        if res:
            return res

    # Strategy 3: Search recursively in source directory
    if file_path.is_absolute():
        file_path = file_path.relative_to(Path("/"))

    res = list(challenge.get_source_path().rglob(file_path.as_posix()))
    if res:
        return cast(Path, res[0].relative_to(challenge.get_source_path()))

    # Strategy 4: Search recursively by removing the first parts of the path
    try:
        if file_path.parts and file_path.parts[0] == "src" and len(file_path.parts) > 3:
            for idx in range(2, len(file_path.parts) - 2):
                parts = file_path.parts[idx:]
                res = list(challenge.get_source_path().rglob(Path(*parts).as_posix()))
                if res:
                    return cast(Path, res[0].relative_to(challenge.get_source_path()))
    except Exception:
        return None

    return None


def pick_temperature() -> float:
    """Pick a temperature for the LLM."""
    return random.choices([0.1, 0.2, 0.3, 0.4, 0.5], weights=[0.1, 0.15, 0.5, 0.15, 0.1])[0]


def truncate_output(
    output: str | None, max_length: int, truncate_position: TruncatePosition = TruncatePosition.MIDDLE
) -> str:
    """Truncate the output to the maximum length.
    If the output is longer than the maximum length, truncate it in the middle and add
    ellipses to indicate that the output was truncated.
    """
    if output is None:
        return ""

    if len(output) <= max_length:
        return output

    if truncate_position == TruncatePosition.START:
        return "\n[...TRUNCATED...]\n" + output[-max_length:]
    elif truncate_position == TruncatePosition.MIDDLE:
        return output[: max_length // 2] + "\n[...TRUNCATED...]\n" + output[-max_length // 2 :]
    elif truncate_position == TruncatePosition.END:
        return output[:max_length] + "\n[...TRUNCATED...]\n"


@lru_cache(maxsize=100)
def get_challenge(task_dir: Path, task_dir_ro: Path | None = None) -> ChallengeTask:
    if task_dir_ro:
        return ChallengeTask(task_dir, local_task_dir=task_dir_ro)

    return ChallengeTask(task_dir, local_task_dir=task_dir)


@lru_cache(maxsize=100)
def get_codequery(task_dir: Path, work_dir: Path) -> CodeQueryPersistent:
    challenge = get_challenge(task_dir)
    return CodeQueryPersistent(challenge, work_dir=work_dir)
