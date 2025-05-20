"""LLM-based Patcher Agent module"""

from __future__ import annotations

from typing import Annotated
from dataclasses import dataclass
from pydantic import BaseModel, Field
from buttercup.patcher.utils import PatchInput, PatchOutput, CHAIN_CALL_TYPE
from buttercup.common.challenge_task import ChallengeTask
from enum import Enum
import re
import uuid


def add_or_mod_patch(patches: list[PatchAttempt], patch: PatchAttempt | list[PatchAttempt]) -> list[PatchAttempt]:
    """Add or modify a patch."""

    def single_patch(patch: PatchAttempt) -> None:
        replaced = False
        for idx, p in enumerate(patches):
            if p.id == patch.id:
                patches[idx] = patch
                replaced = True
                break

        if not replaced:
            patches.append(patch)

    if isinstance(patch, list):
        for p in patch:
            single_patch(p)
    else:
        single_patch(patch)

    return patches


def add_code_snippet(
    existing_code_snippets: set[ContextCodeSnippet], new_code_snippets: set[ContextCodeSnippet]
) -> set[ContextCodeSnippet]:
    """Add a code snippet to the list."""
    res = list(existing_code_snippets)
    for new_code_snippet in new_code_snippets:
        to_add = True
        for existing_code_snippet in existing_code_snippets:
            if new_code_snippet.key.file_path == existing_code_snippet.key.file_path:
                # Check if the new code snippet is a subset of the existing code snippet
                if (
                    new_code_snippet.start_line >= existing_code_snippet.start_line
                    and new_code_snippet.end_line <= existing_code_snippet.end_line
                ):
                    to_add = False
                    break

                # If the new code is a super set of the existing code snippet,
                # remove the existing one and keep the new one
                if (
                    existing_code_snippet.start_line >= new_code_snippet.start_line
                    and existing_code_snippet.end_line <= new_code_snippet.end_line
                ):
                    res.remove(existing_code_snippet)

        if to_add:
            res.append(new_code_snippet)

    return set(res)


class PatcherAgentName(Enum):
    CONTEXT_RETRIEVER = "context_retriever_node"
    ROOT_CAUSE_ANALYSIS = "root_cause_analysis"
    PATCH_STRATEGY = "patch_strategy_node"
    CREATE_PATCH = "create_patch"
    BUILD_PATCH = "build_patch"
    RUN_POV = "run_pov"
    RUN_TESTS = "run_tests"
    INITIAL_CODE_SNIPPET_REQUESTS = "initial_code_snippet_requests"
    REFLECTION = "reflection"
    INPUT_PROCESSING = "input_processing"


class PatchStatus(Enum):
    PENDING = "pending"
    APPLY_FAILED = "apply_failed"
    CREATION_FAILED = "creation_failed"
    DUPLICATED = "duplicated"
    BUILD_FAILED = "build_failed"
    POV_FAILED = "pov_failed"
    TESTS_FAILED = "tests_failed"
    SUCCESS = "success"


class PatchAnalysis(BaseModel):
    """Patch analysis"""

    failure_category: str | None = None
    failure_analysis: str | None = None
    resolution_component: PatcherAgentName | None = None
    partial_success: bool | None = None


class PatchStrategy(BaseModel):
    """Patch strategy"""

    full: str | None = None
    summary: str | None = None


class PatchAttempt(BaseModel):
    """Patch attempt"""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))

    strategy: str | None = None

    description: str | None = None
    patch: PatchOutput | None = Field(default=None)
    patch_str: str | None = None
    patch_review: str | None = None

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

    status: PatchStatus = Field(default=PatchStatus.PENDING)
    analysis: PatchAnalysis | None = Field(default=None)


class ReflectionResult(BaseModel):
    """Reflection result"""

    decision: PatcherAgentName
    result: str


class ExecutionInfo(BaseModel):
    """Execution info"""

    root_cause_analysis_tries: int = Field(default=0)
    patch_creation_tries: int = Field(default=0)
    reflection_decision: PatcherAgentName | None = None
    reflection_guidance: str | None = None
    prev_node: PatcherAgentName | None = None
    code_snippet_requests: list[CodeSnippetRequest] = Field(default_factory=list)


class RootCauseAnalysis(BaseModel):
    """Structured analysis of a security vulnerability's root cause and characteristics.
    This class captures the key aspects needed to fully understand a vulnerability,
    including its classification, trigger conditions, affected components, and security implications.
    The analysis is used to guide the autonomous patching process."""

    code_snippet_requests: str | None = Field(default=None)
    classification: str | None = Field(default=None)
    root_cause: str | None = Field(default=None)
    affected_variables: str | None = Field(default=None)
    trigger_conditions: str | None = Field(default=None)
    data_flow_analysis: str | None = Field(default=None)
    security_constraints: str | None = Field(default=None)

    def __str__(self) -> str:
        """String representation of the RootCauseAnalysis"""
        return f"""<root_cause_analysis>
<code_snippet_requests>{self.code_snippet_requests}</code_snippet_requests>
<classification>{self.classification}</classification>
<root_cause>{self.root_cause}</root_cause>
<affected_variables>{self.affected_variables}</affected_variables>
<trigger_conditions>{self.trigger_conditions}</trigger_conditions>
<data_flow_analysis>{self.data_flow_analysis}</data_flow_analysis>
<security_constraints>{self.security_constraints}</security_constraints>
</root_cause_analysis>
"""


class PatcherAgentState(BaseModel):
    """State for the Patcher Agent."""

    context: PatchInput

    cleaned_stacktrace: str | None = None

    relevant_code_snippets: Annotated[set[ContextCodeSnippet], add_code_snippet] = Field(default_factory=set)
    root_cause: RootCauseAnalysis | None = None

    patch_strategy: PatchStrategy | None = None
    patch_attempts: Annotated[list[PatchAttempt], add_or_mod_patch] = Field(default_factory=list)
    execution_info: ExecutionInfo = Field(default_factory=ExecutionInfo)

    def get_successful_patch(self) -> PatchOutput | None:
        """Get the successful patch."""
        if not self.patch_attempts:
            return None

        last_patch = self.patch_attempts[-1]
        if last_patch.build_succeeded and last_patch.pov_fixed and last_patch.tests_passed:
            return last_patch.patch

        return None

    def get_last_patch_attempt(self) -> PatchAttempt | None:
        """Get the last patch."""
        if self.patch_attempts:
            return self.patch_attempts[-1]

        return None


class ContextRetrieverState(BaseModel):
    """State for the Context Retriever Agent."""

    relevant_code_snippets: set[ContextCodeSnippet] = Field(default_factory=set)
    code_snippet_requests: list[CodeSnippetRequest] = Field(default_factory=list)
    prev_node: str
    execution_info: ExecutionInfo = Field(default_factory=ExecutionInfo)


class CodeSnippetKey(BaseModel):
    """Code snippet key"""

    identifier: str = Field(default_factory=lambda: str(uuid.uuid4()))
    file_path: str | None = Field(description="The file path of the code snippet")

    def __hash__(self) -> int:
        """Hash the code snippet key"""
        return hash((self.identifier, self.file_path))

    def __eq__(self, other: object) -> bool:
        """Check if the code snippet key is equal to another object"""
        if not isinstance(other, CodeSnippetKey):
            return False
        return self.identifier == other.identifier and self.file_path == other.file_path


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

    start_line: int
    "Start line of the code snippet"

    end_line: int
    "End line of the code snippet"

    description: str | None = None
    "Description of the code snippet, e.g. 'Definition of function X', 'Class Y', 'Definition of type Z', etc."

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
<identifier>{self.key.identifier}</identifier>
<file_path>{self.key.file_path}</file_path>
<description>{self.description}</description>
<start_line>{self.start_line}</start_line>
<end_line>{self.end_line}</end_line>
<code>
{self.code}
</code>{context}
</code_snippet>
"""

    def __hash__(self) -> int:
        """Hash the code snippet"""
        return hash((type(self),) + tuple([self.key.file_path, self.code, self.code_context]))

    def __eq__(self, other: object) -> bool:
        """Check if the code snippet is equal to another object (by file path, code and code context)"""
        if not isinstance(other, ContextCodeSnippet):
            return False

        return (
            self.key.file_path == other.key.file_path
            and self.code == other.code
            and self.code_context == other.code_context
        )


@dataclass
class PatcherAgentBase:
    """Patcher Agent."""

    challenge: ChallengeTask
    input: PatchInput
    chain_call: CHAIN_CALL_TYPE
