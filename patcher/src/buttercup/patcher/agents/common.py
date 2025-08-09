"""LLM-based Patcher Agent module"""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from buttercup.common.llm import ButtercupLLM, create_default_llm_with_temperature
from typing import Annotated, Sequence
from buttercup.common.clusterfuzz_parser import CrashInfo
from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from langgraph.managed import RemainingSteps
from dataclasses import dataclass, field
from langchain_core.runnables import Runnable
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from pydantic import BaseModel, Field
from buttercup.patcher.utils import (
    PatchInput,
    PatchOutput,
    CHAIN_CALL_TYPE,
    PatchInputPoV,
    truncate_output,
    TruncatePosition,
)
from buttercup.common.challenge_task import ChallengeTask
from langgraph.prebuilt.chat_agent_executor import AgentStatePydantic
import re
import uuid
import logging

MAX_STACKTRACE_LENGTH = 15000

logger = logging.getLogger(__name__)


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
            if patches:
                patches[-1].clean_built_challenges()

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
                    and existing_code_snippet in res
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
    FIND_TESTS = "find_tests"
    PATCH_VALIDATION = "patch_validation"


class PatchStatus(Enum):
    PENDING = "pending"
    APPLY_FAILED = "apply_failed"
    CREATION_FAILED = "creation_failed"
    DUPLICATED = "duplicated"
    BUILD_FAILED = "build_failed"
    POV_FAILED = "pov_failed"
    TESTS_FAILED = "tests_failed"
    SUCCESS = "success"
    VALIDATION_FAILED = "validation_failed"


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

    # Store built challenge task directories for each sanitizer to avoid rebuilding
    built_challenges: dict[str, Path] = Field(default_factory=dict)

    status: PatchStatus = Field(default=PatchStatus.PENDING)
    analysis: PatchAnalysis | None = Field(default=None)

    def get_built_challenge(self, sanitizer: str) -> ChallengeTask | None:
        """Get the built challenge task for a given sanitizer"""
        if sanitizer in self.built_challenges:
            built_task_dir = self.built_challenges[sanitizer]
            return ChallengeTask(
                read_only_task_dir=built_task_dir,
                local_task_dir=built_task_dir,
            )

        return None

    def clean_built_challenges(self) -> None:
        """Clean the built challenges"""
        to_remove = []
        for key, task_dir in self.built_challenges.items():
            try:
                ChallengeTask(task_dir, local_task_dir=task_dir).cleanup()
                to_remove.append(key)
            except Exception:
                logger.warning("Failed to clean up built challenge %s", task_dir, exc_info=True)

        for key in to_remove:
            self.built_challenges.pop(key)


class ReflectionResult(BaseModel):
    """Reflection result"""

    decision: PatcherAgentName
    result: str


class ExecutionInfo(BaseModel):
    """Execution info"""

    root_cause_analysis_tries: int = Field(default=0)
    patch_strategy_tries: int = Field(default=0)
    tests_tries: int = Field(default=0)
    reflection_decision: PatcherAgentName | None = None
    reflection_guidance: str | None = None
    prev_node: PatcherAgentName | None = None
    code_snippet_requests: list[CodeSnippetRequest] = Field(default_factory=list)


class BaseCtxState(AgentStatePydantic):
    """Base state for the context retriever agents"""

    challenge_task_dir: Path
    work_dir: Path
    challenge_task_dir_ro: Path | None = None


class PatcherAgentState(BaseModel):
    """State for the Patcher Agent."""

    context: PatchInput

    tests_instructions: str | None = None

    relevant_code_snippets: Annotated[set[ContextCodeSnippet], add_code_snippet] = Field(default_factory=set)
    root_cause: str | None = None

    patch_strategy: PatchStrategy | None = None
    patch_attempts: Annotated[list[PatchAttempt], add_or_mod_patch] = Field(default_factory=list)
    execution_info: ExecutionInfo = Field(default_factory=ExecutionInfo)

    # Needed to use in create_react_agent
    messages: Annotated[Sequence[BaseMessage], add_messages] = Field(default_factory=list)
    remaining_steps: RemainingSteps = 25

    def get_successful_patch(self) -> PatchOutput | None:
        """Get the last successful patch.
        This gets a patch that builds, fixes the PoV and passes the tests, even if it does not seem to be valid."""
        if not self.patch_attempts:
            return None

        for patch_attempt in self.patch_attempts[::-1]:
            if patch_attempt.build_succeeded and patch_attempt.pov_fixed and patch_attempt.tests_passed:
                return patch_attempt.patch

        return None

    def get_last_patch_attempt(self) -> PatchAttempt | None:
        """Get the last patch."""
        if self.patch_attempts:
            return self.patch_attempts[-1]

        return None

    def clean_built_challenges(self) -> None:
        """Clean the built challenges"""
        for patch_attempt in self.patch_attempts:
            patch_attempt.clean_built_challenges()


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

    can_patch: bool = Field(default=True)

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
<can_patch>{self.can_patch}</can_patch>
<code>
{self.code}
</code>{context}
</code_snippet>
"""

    def commented_code(self, stacktraces: list[CrashInfo]) -> str:
        """Get a commented version of the code snippet"""
        stacktrace_lines = [
            (stackframe.filename, int(stackframe.fileline))
            for stacktrace in stacktraces
            for frame in stacktrace.frames
            for stackframe in frame
            if stackframe.filename is not None and stackframe.fileline is not None
        ]
        code = []
        for lineno, line in enumerate(self.code.split("\n"), start=self.start_line):
            if (self.key.file_path, lineno) in stacktrace_lines:
                code.append(f"{line} // LINE {lineno} | STACKTRACE INFO")
            else:
                code.append(line)

        return f"""<code_snippet>
<identifier>{self.key.identifier}</identifier>
<file_path>{self.key.file_path}</file_path>
<description>{self.description}</description>
<start_line>{self.start_line}</start_line>
<end_line>{self.end_line}</end_line>
<code>
{"\n".join(code)}
</code>
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


UNDERSTAND_CODE_SNIPPET_SYSTEM_MSG = """You are an AI agent in a multi-agent LLM-based autonomous patching system. Your task is to provide focused, detailed descriptions of code snippets based on specific areas of interest."""
UNDERSTAND_CODE_SNIPPET_USER_MSG = """Your role is to understand the provided code and provide a \
natural language description focusing specifically on the requested area of interest. \
The description should be detailed and relevant to the focus area, while still maintaining \
awareness of the broader context.

Here is the code:
<code>
{CODE}
</code>

Here is the focus area to analyze:
<focus_area>
{FOCUS_AREA}
</focus_area>

Provide a natural language description that specifically addresses the focus area, wrapped in <description> tags. \
The description should be detailed enough to help understand the specific functionality or behavior \
related to the focus area.
"""

UNDERSTAND_CODE_SNIPPET_PROMPT = ChatPromptTemplate.from_messages(
    [
        ("system", UNDERSTAND_CODE_SNIPPET_SYSTEM_MSG),
        ("user", UNDERSTAND_CODE_SNIPPET_USER_MSG),
    ]
)


def _create_understand_code_snippet_chain() -> Runnable:
    return (  # type: ignore[no-any-return]
        UNDERSTAND_CODE_SNIPPET_PROMPT
        | create_default_llm_with_temperature(model_name=ButtercupLLM.OPENAI_GPT_4_1.value)
        | StrOutputParser()
    )


@dataclass
class PatcherAgentBase:
    """Patcher Agent."""

    challenge: ChallengeTask
    input: PatchInput
    chain_call: CHAIN_CALL_TYPE

    understand_code_snippet_chain: Runnable = field(default_factory=_create_understand_code_snippet_chain, init=False)

    def _understand_code_snippet(self, state: PatcherAgentState, code_snippet_id: str, focus_area: str) -> str:
        """Understand a specific aspect of a code snippet based on a focus area.

        This function provides a detailed natural language description of the code snippet,
        specifically focusing on the requested area of interest. The focus area should be
        a clear description of what aspect of the code needs to be understood.

        Examples of good focus areas:
        - "What's the purpose of function X?"
        - "How is the memory buffer `secret` allocated and freed in this code?"
        - "How is the variable `secret` used in this code?"
        - "How does the code handle concurrent access to the shared resource `counter`?"
        - "What are the error handling mechanisms in the network code that deals with the first 100 bytes of the incoming message?"
        - "How does the code prevent SQL injection in the database query to extract the user's name?"
        - "How is the variable `s` checked for validity?"

        Args:
            code_snippet_id: The identifier of the code snippet to analyze
            focus_area: A specific area of interest to focus the analysis on. This should be
                a clear description of what aspect of the code needs to be understood.

        Returns:
            A natural language description of the code snippet, focused on the specified area.

        Raises:
            ValueError: If the code snippet with the given identifier is not found
        """
        code_snippet = next((cs for cs in state.relevant_code_snippets if cs.key.identifier == code_snippet_id), None)
        if not code_snippet:
            raise ValueError(f"Code snippet with identifier {code_snippet_id} not found")

        res = self.understand_code_snippet_chain.invoke(
            {
                "CODE": code_snippet.code,
                "FOCUS_AREA": focus_area,
            }
        )
        # Extract description from response
        match = re.search(r"<description>(.*?)</description>", res, re.DOTALL | re.IGNORECASE)
        if match is None:
            return "No description found"

        res = f"""<code_snippet_understanding>
<identifier>{code_snippet.key.identifier}</identifier>
<file_path>{code_snippet.key.file_path}</file_path>
<description>
{match.group(1).strip()}
</description>
</code_snippet_understanding>
"""
        return res


STACKTRACE_TMPL = """<stacktrace>
<sanitizer_name>{SANITIZER_NAME}</sanitizer_name>
<sanitizer_output>
{SANITIZER_OUTPUT}
</sanitizer_output>
</stacktrace>"""


def stacktrace_to_str(sanitizer: str, sanitizer_output: str | None) -> str:
    ansi_escape = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
    return STACKTRACE_TMPL.format(
        SANITIZER_NAME=sanitizer,
        SANITIZER_OUTPUT=truncate_output(
            ansi_escape.sub("", sanitizer_output or ""),
            MAX_STACKTRACE_LENGTH,
            TruncatePosition.START,
        ),
    )


def get_stacktraces_from_povs(povs: list[PatchInputPoV]) -> list[str]:
    return [stacktrace_to_str(pov.sanitizer, pov.sanitizer_output) for pov in povs]
