"""LLM-based Patcher Agent module"""

from __future__ import annotations

import operator
from pathlib import Path
from os import PathLike
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

    relevant_code_snippets: Annotated[set[ContextCodeSnippet], operator.or_] = Field(default_factory=set)
    diff_analysis: str | None = None
    root_cause: str | None = None

    ctx_request_limit: bool = Field(default=False)

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

    code_snippet_requests: list[CodeSnippetRequest] = Field(default_factory=list)
    prev_node: str


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


class CodeSnippetRequest(BaseModel):
    """Code snippet request"""

    request: str = Field(description="Detailed explanation of what code snippet is needed")

    @classmethod
    def parse(cls, msg: str) -> list[CodeSnippetRequest]:
        """Parse the code snippet request from the message"""
        CODE_SNIPPET_REQUEST_RE = re.compile("<code_request>(.*?)</code_request>", re.DOTALL | re.IGNORECASE)
        code_snippet_requests_matches = CODE_SNIPPET_REQUEST_RE.findall(msg)
        if not code_snippet_requests_matches:
            return []

        return [cls(request=request.strip()) for request in code_snippet_requests_matches]


class ContextCodeSnippet(BaseModel):
    """Code snippet from the Challenge Task. This is the base unit used by the
    patcher to build patches. Changes are applied to this units."""

    key: CodeSnippetKey
    "Key of the code snippet, used to uniquely identify the code snippet"

    code: str
    "Code of the code snippet"

    code_context: str | None = None
    "Additional context around the code snippet, e.g. lines information, etc."

    def __str__(self) -> str:
        context = (
            f"""
    <code_context>
    {self.code_context}
    </code_context>
"""
            if self.code_context
            else ""
        )
        return f"""<code_snippet>
<file_path>{self.key.file_path}</file_path>
<identifier>{self.key.identifier}</identifier>
<code>
{self.code}
</code>{context}
</code_snippet>
"""

    def __hash__(self) -> int:
        """Hash the code snippet"""
        return hash((type(self),) + tuple(self.__dict__.values()))


@dataclass
class PatcherAgentBase:
    """Patcher Agent."""

    challenge: ChallengeTask
    input: PatchInput
    chain_call: CHAIN_CALL_TYPE

    def rebase_src_path(self, path: str | PathLike) -> Path:
        """Rebase the /src paths to be relative to the task directory"""
        path = Path(path)
        if not path.is_absolute():
            return path

        path = path.resolve()
        src_repo_path = Path(f"/src/{self.challenge.project_name}/")
        src_path = Path("/src")

        if path.is_relative_to(src_repo_path):
            extra_path = path.relative_to(src_repo_path)
            return self.challenge.get_source_subpath().joinpath(extra_path)  # type: ignore[no-any-return]

        if path.is_relative_to(src_path):
            extra_path = path.relative_to(src_path)
            if self.challenge.get_oss_fuzz_path().joinpath(extra_path).exists():
                return self.challenge.get_oss_fuzz_path().joinpath(extra_path)  # type: ignore[no-any-return]

            path = extra_path

        return path

    def get_code_snippet_requests(
        self, response: str, update_state: dict, ctx_request_limit: bool, *, current_node: str, default_goto: str
    ) -> tuple[str, dict]:
        """Get the code snippet request from the response."""
        if ctx_request_limit:
            return default_goto, update_state

        code_snippet_requests = CodeSnippetRequest.parse(response)
        if not code_snippet_requests:
            return default_goto, update_state

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
