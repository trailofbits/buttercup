"""LLM-based Patcher Agent module"""

from __future__ import annotations

import operator
from pathlib import Path
from typing import Annotated
from dataclasses import dataclass
from pydantic import BaseModel, Field
from buttercup.patcher.context import ContextCodeSnippet
from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from buttercup.patcher.utils import PatchInput, PatchOutput, CHAIN_CALL_TYPE
from buttercup.common.challenge_task import ChallengeTask
from enum import Enum
import re


class PatcherAgentName(Enum):
    COMMIT_ANALYSIS = "commit_analysis_node"
    CONTEXT_RETRIEVER = "context_retriever_node"
    ROOT_CAUSE_ANALYSIS = "root_cause_analysis"
    CREATE_PATCH = "create_patch"
    REVIEW_PATCH = "review_patch"
    BUILD_PATCH = "build_patch"
    BUILD_FAILURE_ANALYSIS = "build_failure_analysis"
    RUN_POV = "run_pov"
    RUN_TESTS = "run_tests"


class PatcherAgentState(BaseModel):
    """State for the Patcher Agent."""

    context: PatchInput
    messages: Annotated[list[BaseMessage], add_messages]

    relevant_code_snippets: Annotated[list[ContextCodeSnippet], operator.add] = Field(default_factory=list)
    commit_analysis: str | None = None
    root_cause: str | None = None

    patches: list[PatchOutput] = Field(default_factory=list)
    patch_tries: int = Field(default=0)

    patch_review: str | None = None
    patch_review_tries: int = Field(default=0)

    build_succeeded: bool = Field(default=False)
    build_stdout: bytes | None = None
    build_stderr: bytes | None = None
    build_analysis: str | None = None

    pov_fixed: bool = Field(default=False)
    pov_stdout: bytes | None = None
    pov_stderr: bytes | None = None

    tests_passed: bool = Field(default=False)
    tests_stdout: bytes | None = None
    tests_stderr: bytes | None = None

    prev_node: str | None = None
    code_snippet_requests: list[CodeSnippetKey] = Field(default_factory=list)

    def get_successful_patch(self) -> PatchOutput | None:
        """Get the successful patch."""
        if self.build_succeeded and self.pov_fixed and self.tests_passed and self.patches:
            return self.patches[-1]

        return None

    def get_last_patch(self) -> PatchOutput | None:
        """Get the last patch."""
        if self.patches:
            return self.patches[-1]

        return None


class CodeSnippetKey(BaseModel):
    """Code snippet key"""

    file_path: str | None = Field(description="The file path of the code snippet")
    function_name: str | None = Field(description="The function name of the code snippet")

    def __hash__(self) -> int:
        """Hash the code snippet key"""
        return hash((self.file_path, self.function_name))

    def __eq__(self, other: object) -> bool:
        """Check if the code snippet key is equal to another object"""
        if not isinstance(other, CodeSnippetKey):
            return False
        return self.file_path == other.file_path and self.function_name == other.function_name


@dataclass
class PatcherAgentBase:
    """Patcher Agent."""

    challenge: ChallengeTask
    input: PatchInput
    chain_call: CHAIN_CALL_TYPE

    def rebase_src_path(self, path: str) -> str:
        """Rebase the src path to the project name."""
        if path.startswith(f"/src/{self.challenge.project_name}/"):
            path = path[len(f"/src/{self.challenge.project_name}/") :]
        elif path == f"/src/{self.challenge.project_name}":
            path = "."
        elif path.startswith(f"src/{self.challenge.project_name}"):
            path = path[len(f"src/{self.challenge.project_name}") :]
        elif path.startswith(f"src/{self.challenge.project_name}"):
            path = path[len(f"src/{self.challenge.project_name}") :]

        if path.startswith("/"):
            path = Path(path).relative_to("/")

        return path

    def get_code_snippet_requests(self, response: str, *, current_node: str, default_goto: str) -> tuple[str, dict]:
        """Get the code snippet request from the response."""

        CODE_SNIPPET_REQUEST = re.compile(
            r"""# CODE SNIPPET REQUESTS:
.*?
(File path: (.*?)
Function name: (.*?))+
```""",
            re.DOTALL | re.IGNORECASE,
        )
        matches = CODE_SNIPPET_REQUEST.search(response)
        if not matches:
            return default_goto, {}

        # Extract all file path and function name pairs
        pair_pattern = re.compile(r"File path: (.*?)\nFunction name: (.*?)(?:\n|$)", re.DOTALL)
        code_snippet_requests = pair_pattern.findall(matches.group(0))

        if len(code_snippet_requests) == 0:
            return default_goto, {}

        code_snippet_requests = [
            CodeSnippetKey(file_path=request[0], function_name=request[1]) for request in code_snippet_requests
        ]
        return PatcherAgentName.CONTEXT_RETRIEVER.value, {
            "code_snippet_requests": code_snippet_requests,
            "prev_node": current_node,
        }


# Prompt snippets used by various agents

CONTEXT_PROJECT_TMPL = "Project name: {project_name}"

CONTEXT_COMMIT_TMPL = """Commit introducing the vulnerability:
```
{commit_content}
```
"""
CONTEXT_COMMIT_ANALYSIS_TMPL = """Analysis of the commit introducing the \
vulnerability. This just describe the vulnerability at the time it was \
introduced, but it may contain partially inaccurate information.
```
{commit_analysis}
```
"""
CONTEXT_ROOT_CAUSE_TMPL = """Vulnerability Root cause analysis:
```
{root_cause}
```
"""

CONTEXT_SANITIZER_TMPL = """Sanitizer: {sanitizer}
Sanitizer output:
```
{sanitizer_output}
```
"""

CONTEXT_EXTRA_CODE_TMPL = """Extra context:
```
{code_context}
```
"""

CONTEXT_VULNERABLE_CODE_TMPL = """Vulnerable code:
```
{vulnerable_function}
```
"""

CONTEXT_VULNERABLE_FILE_TMPL = """Vulnerable file: {vulnerable_file}"""

CONTEXT_CODE_SNIPPET_TMPL = """# Relevant code snippet
File path: {file_path}
Function name: {function_name}
Code:
```
{code}
```
Extra context:
```
{code_context}
```
"""
