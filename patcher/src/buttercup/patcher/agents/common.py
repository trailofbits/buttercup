"""LLM-based Patcher Agent module"""

from __future__ import annotations

import operator
from pathlib import Path
from typing import Annotated
from dataclasses import dataclass
from pydantic import BaseModel, Field
from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from buttercup.patcher.utils import PatchInput, PatchOutput, CHAIN_CALL_TYPE
from buttercup.common.challenge_task import ChallengeTask
from enum import Enum
import re


class PatcherAgentName(Enum):
    DIFF_ANALYSIS = "diff_analysis_node"
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
    diff_analysis: str | None = None
    root_cause: str | None = None

    patches: list[PatchOutput] = Field(default_factory=list)
    patch_tries: int = Field(default=0)

    patch_review: str | None = None
    patch_review_tries: int = Field(default=0)

    build_succeeded: bool | None = None
    build_stdout: bytes | None = None
    build_stderr: bytes | None = None
    build_analysis: str | None = None

    pov_fixed: bool | None = None
    pov_stdout: bytes | None = None
    pov_stderr: bytes | None = None

    tests_passed: bool | None = None
    tests_stdout: bytes | None = None
    tests_stderr: bytes | None = None

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


class ContextRetrieverState(BaseModel):
    """State for the Context Retriever Agent."""

    code_snippet_requests: list[CodeSnippetKey] = Field(default_factory=list)
    prev_node: str | None = None


class CodeSnippetKey(BaseModel):
    """Code snippet key"""

    file_path: str | None = Field(description="The file path of the code snippet")
    identifier: str | None = Field(description="The identifier of the code snippet")

    def __hash__(self) -> int:
        """Hash the code snippet key"""
        return hash((self.file_path, self.identifier))

    def __eq__(self, other: object) -> bool:
        """Check if the code snippet key is equal to another object"""
        if not isinstance(other, CodeSnippetKey):
            return False
        return self.file_path == other.file_path and self.identifier == other.identifier


class ContextCodeSnippet(BaseModel):
    """Code snippet from the Challenge Task. This is the base unit used by the
    patcher to build patches. Changes are applied to this units."""

    key: CodeSnippetKey
    "Key of the code snippet, used to uniquely identify the code snippet"

    code: str
    "Code of the code snippet"

    code_context: str | None = None
    "Additional context around the code snippet, e.g. lines information, etc."


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
            path = str(Path(path).relative_to("/"))

        if path == "":
            path = "."

        return str(path)

    def get_code_snippet_requests(
        self, response: str, update_state: dict, *, current_node: str, default_goto: str
    ) -> tuple[str, dict]:
        """Get the code snippet request from the response."""

        CODE_SNIPPET_REQUEST = re.compile(
            r"""# CODE SNIPPET REQUESTS:
.*?
(File path: (.*?)
Identifier: (.*?))+
```""",
            re.DOTALL | re.IGNORECASE,
        )
        matches = CODE_SNIPPET_REQUEST.search(response)
        if not matches:
            return default_goto, update_state

        # Extract all file path and identifier pairs
        pair_pattern = re.compile(r"File path: (.*?)\nIdentifier: (.*?)(?:\n|$)", re.DOTALL)
        code_snippet_requests = pair_pattern.findall(matches.group(0))

        if len(code_snippet_requests) == 0:
            return default_goto, update_state

        code_snippet_requests = [
            CodeSnippetKey(file_path=request[0], identifier=request[1]) for request in code_snippet_requests
        ]
        return PatcherAgentName.CONTEXT_RETRIEVER.value, {
            "code_snippet_requests": code_snippet_requests,
            "prev_node": current_node,
        }


# Prompt snippets used by various agents

CONTEXT_PROJECT_TMPL = "Project name: {project_name}"

CONTEXT_DIFF_TMPL = """Diff introducing the vulnerability:
```
{diff_content}
```
"""
CONTEXT_DIFF_ANALYSIS_TMPL = """Analysis of the diff introducing the \
vulnerability.
```
{diff_analysis}
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
Identifier: {identifier}
Code:
```
{code}
```
Extra context:
```
{code_context}
```
"""

CODE_SNIPPET_REQUEST_ITEM_TMPL = """File path: <file_path{i}>
Identifier: <identifier{i}>
"""

CODE_SNIPPET_REQUEST_TMPL = """```
# CODE SNIPPET REQUESTS:

{code_snippet_request_tmpl}
[...]
```
"""


def get_code_snippet_request_tmpl(n: int) -> str:
    """Get the code snippet request template."""
    examples = [CODE_SNIPPET_REQUEST_ITEM_TMPL.format(i=i) for i in range(1, n + 1)]
    return CODE_SNIPPET_REQUEST_TMPL.format(code_snippet_request_tmpl="\n".join(examples))
