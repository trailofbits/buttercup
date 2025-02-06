"""LLM-based Patcher Agent module"""

import operator
from typing import Annotated, TypedDict

from buttercup.patcher.context import ContextCodeSnippet
from buttercup.patcher.utils import PatchInput
from buttercup.common.datastructures.msg_pb2 import Patch
from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


class PatcherAgentState(TypedDict):
    """State for the Patcher Agent."""

    context: PatchInput
    messages: Annotated[list[BaseMessage], add_messages]

    commit_analysis: str
    relevant_code_snippets: Annotated[list[ContextCodeSnippet], operator.add]
    root_cause: str

    patches: list[Patch]
    patch_tries: int | None

    patch_review: str | None
    patch_review_tries: int | None

    build_succeeded: bool | None
    build_stdout: bytes | None
    build_stderr: bytes | None
    build_analysis: str | None

    pov_fixed: bool | None
    pov_stdout: bytes | None
    pov_stderr: bytes | None

    tests_passed: bool | None
    tests_stdout: bytes | None
    tests_stderr: bytes | None


class FilterSnippetState(TypedDict):
    """State for the FilterSnippet Agent."""

    code_snippet: ContextCodeSnippet
    commit_analysis: str
    context: PatchInput


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
