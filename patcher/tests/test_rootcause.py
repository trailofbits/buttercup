"""Tests for the RootCause agent."""

from typing import Iterator
import pytest
from pathlib import Path
import shutil
import subprocess
from unittest.mock import MagicMock, patch
import os
from langchain_core.language_models import BaseChatModel
from langchain_core.runnables import Runnable, RunnableSequence
from langgraph.types import Command

from buttercup.patcher.agents.rootcause import RootCauseAgent
from buttercup.patcher.agents.common import (
    PatcherAgentState,
    PatcherAgentName,
    RootCauseAnalysis,
    ContextCodeSnippet,
    CodeSnippetKey,
)
from buttercup.patcher.patcher import PatchInput
from buttercup.common.challenge_task import ChallengeTask
from buttercup.common.task_meta import TaskMeta


original_subprocess_run = subprocess.run


def mock_docker_run(challenge_task: ChallengeTask):
    def wrapped(args, *rest, **kwargs):
        if args[0] == "docker":
            # Mock docker cp command by copying source path to container src dir
            if args[1] == "cp":
                container_dst_dir = Path(args[3]) / "src" / challenge_task.task_meta.project_name
                container_dst_dir.mkdir(parents=True, exist_ok=True)
                # Copy source files to container src dir
                src_path = challenge_task.get_source_path()
                shutil.copytree(src_path, container_dst_dir, dirs_exist_ok=True)
            elif args[1] == "create":
                pass
            elif args[1] == "rm":
                pass

            return subprocess.CompletedProcess(args, returncode=0)
        return original_subprocess_run(args, *rest, **kwargs)

    return wrapped


@pytest.fixture
def mock_llm():
    llm = MagicMock(spec=BaseChatModel)
    llm.with_fallbacks.return_value = llm
    llm.configurable_fields.return_value = llm
    return llm


@pytest.fixture
def mock_root_cause_prompt(mock_llm: MagicMock):
    prompt = MagicMock(spec=Runnable)

    def mock_or(other):
        global current
        if other == mock_llm:
            current = mock_llm
            current.__or__.side_effect = mock_or
            return current

        current = RunnableSequence(current, other)
        return current

    prompt.__or__.side_effect = mock_or
    return prompt


@pytest.fixture(autouse=True)
def mock_llm_functions(mock_llm: MagicMock, mock_root_cause_prompt: MagicMock):
    """Mock LLM creation functions and environment variables."""
    with (
        patch.dict(os.environ, {"BUTTERCUP_LITELLM_HOSTNAME": "http://test-host", "BUTTERCUP_LITELLM_KEY": "test-key"}),
        patch("buttercup.common.llm.create_default_llm", return_value=mock_llm),
        patch("buttercup.common.llm.create_llm", return_value=mock_llm),
        patch("langgraph.prebuilt.chat_agent_executor._get_prompt_runnable", return_value=mock_llm),
    ):
        import buttercup.patcher.agents.rootcause

        buttercup.patcher.agents.rootcause.ROOT_CAUSE_PROMPT = mock_root_cause_prompt
        yield


@pytest.fixture
def task_dir(tmp_path: Path) -> Path:
    """Create a mock challenge task directory structure."""
    # Create the main directories
    tmp_path = tmp_path / "test-challenge-task"
    oss_fuzz = tmp_path / "fuzz-tooling" / "my-oss-fuzz"
    source = tmp_path / "src" / "my-source"
    diffs = tmp_path / "diff" / "my-diff"

    oss_fuzz.mkdir(parents=True, exist_ok=True)
    source.mkdir(parents=True, exist_ok=True)
    diffs.mkdir(parents=True, exist_ok=True)

    # Create project.yaml file
    project_yaml_path = oss_fuzz / "projects" / "example_project" / "project.yaml"
    project_yaml_path.parent.mkdir(parents=True, exist_ok=True)
    project_yaml_path.write_text("""name: example_project
language: c
""")

    # Create some mock patch files
    (diffs / "patch1.diff").write_text("mock patch 1")
    (diffs / "patch2.diff").write_text("mock patch 2")

    # Create a mock helper.py file
    helper_path = oss_fuzz / "infra/helper.py"
    helper_path.parent.mkdir(parents=True, exist_ok=True)
    helper_path.write_text("import sys;\nsys.exit(0)\n")

    # Create a mock test.c file
    (source / "test.c").write_text("int foo() { return 0; }\nint main() { int a = foo(); return a; }")
    (source / "test.h").write_text("struct ebitmap_t { int a; };")

    TaskMeta(
        project_name="example_project",
        focus="my-source",
        task_id="task-id-challenge-task",
        metadata={"task_id": "task-id-challenge-task", "round_id": "testing", "team_id": "tob"},
    ).save(tmp_path)

    return tmp_path


@pytest.fixture
def mock_challenge(task_dir: Path) -> ChallengeTask:
    """Create a mock challenge task for testing."""
    return ChallengeTask(
        read_only_task_dir=task_dir,
        local_task_dir=task_dir,
    )


@pytest.fixture
def root_cause_agent(mock_challenge: ChallengeTask, mock_llm: MagicMock, tmp_path: Path) -> Iterator[RootCauseAgent]:
    """Create a RootCauseAgent instance."""
    patch_input = PatchInput(
        challenge_task_dir=mock_challenge.task_dir,
        task_id=mock_challenge.task_meta.task_id,
        submission_index="1",
        harness_name="mock-harness",
        pov=Path("pov-path-mock"),
        pov_variants_path=Path("pov-variants-path-mock"),
        pov_token="pov-token-mock",
        sanitizer_output="sanitizer-output-mock",
        engine="libfuzzer",
        sanitizer="address",
    )
    agent = RootCauseAgent(
        challenge=mock_challenge,
        input=patch_input,
        chain_call=lambda _, runnable, args, config, default: runnable.invoke(args, config=config),
    )
    yield agent


@pytest.fixture
def mock_runnable_config(tmp_path: Path) -> dict:
    """Create a mock runnable config."""
    return {
        "configurable": {
            "thread_id": "test-thread-id",
            "work_dir": tmp_path / "work_dir",
        },
    }


def test_analyze_vulnerability_success(
    root_cause_agent: RootCauseAgent, mock_llm: MagicMock, mock_runnable_config: dict
) -> None:
    """Test successful vulnerability analysis."""
    # Create a test state with code snippets
    state = PatcherAgentState(
        context=root_cause_agent.input,
        relevant_code_snippets=[
            ContextCodeSnippet(
                key=CodeSnippetKey(file_path="/src/example_project/test.c", identifier="main"),
                start_line=1,
                end_line=1,
                code="int main() { int a = foo(); return a; }",
                code_context="",
            ),
        ],
    )

    # Mock LLM response with a complete root cause analysis
    mock_llm.invoke.return_value = """
<vulnerability_analysis>
<code_snippet_requests></code_snippet_requests>
<classification>Buffer Overflow / Stack Overflow</classification>
<root_cause>The vulnerability occurs due to insufficient bounds checking in the buffer copy operation.</root_cause>
<affected_variables>buffer, size</affected_variables>
<trigger_conditions>Input size exceeds buffer capacity</trigger_conditions>
<data_flow_analysis>Data is read from input, Data is copied to buffer without bounds check</data_flow_analysis>
<security_constraints>Buffer size must be validated before copy</security_constraints>
</vulnerability_analysis>
    """

    result = root_cause_agent.analyze_vulnerability(state)

    assert isinstance(result, Command)
    assert result.goto == PatcherAgentName.CREATE_PATCH.value
    assert "root_cause" in result.update
    assert isinstance(result.update["root_cause"], RootCauseAnalysis)
    assert result.update["root_cause"].classification == "Buffer Overflow / Stack Overflow"
    assert (
        result.update["root_cause"].root_cause
        == "The vulnerability occurs due to insufficient bounds checking in the buffer copy operation."
    )
    assert result.update["root_cause"].affected_variables == "buffer, size"
    assert result.update["root_cause"].trigger_conditions == "Input size exceeds buffer capacity"
    assert (
        result.update["root_cause"].data_flow_analysis
        == "Data is read from input, Data is copied to buffer without bounds check"
    )
    assert result.update["root_cause"].security_constraints == "Buffer size must be validated before copy"


def test_analyze_vulnerability_missing_info(
    root_cause_agent: RootCauseAgent, mock_llm: MagicMock, mock_runnable_config: dict
) -> None:
    """Test vulnerability analysis that requires additional information."""
    state = PatcherAgentState(
        context=root_cause_agent.input,
        relevant_code_snippets=[
            ContextCodeSnippet(
                key=CodeSnippetKey(file_path="/src/example_project/test.c", identifier="main"),
                start_line=1,
                end_line=1,
                code="int main() { int a = foo(); return a; }",
                code_context="",
            ),
        ],
    )

    # Mock LLM response requesting more information
    mock_llm.invoke.return_value = """
<vulnerability_analysis>
<code_snippet_requests>Need to see the implementation of foo() to understand the vulnerability</code_snippet_requests>
<classification></classification>
<root_cause></root_cause>
<affected_variables></affected_variables>
<trigger_conditions></trigger_conditions>
<data_flow_analysis></data_flow_analysis>
<security_constraints></security_constraints>
</vulnerability_analysis>
    """

    result = root_cause_agent.analyze_vulnerability(state)

    assert isinstance(result, Command)
    assert result.goto == PatcherAgentName.REFLECTION.value
    assert "root_cause" in result.update
    assert isinstance(result.update["root_cause"], RootCauseAnalysis)
    assert (
        result.update["root_cause"].code_snippet_requests
        == "Need to see the implementation of foo() to understand the vulnerability"
    )


def test_analyze_vulnerability_no_root_cause(
    root_cause_agent: RootCauseAgent, mock_llm: MagicMock, mock_runnable_config: dict
) -> None:
    """Test vulnerability analysis when no root cause is found."""
    state = PatcherAgentState(
        context=root_cause_agent.input,
        relevant_code_snippets=[
            ContextCodeSnippet(
                key=CodeSnippetKey(file_path="/src/example_project/test.c", identifier="main"),
                start_line=1,
                end_line=1,
                code="int main() { int a = foo(); return a; }",
                code_context="",
            ),
        ],
    )

    # Mock LLM response returning None
    mock_llm.invoke.return_value = None

    with pytest.raises(Exception):
        root_cause_agent.analyze_vulnerability(state)


def test_analyze_vulnerability_malformed_response(
    root_cause_agent: RootCauseAgent, mock_llm: MagicMock, mock_runnable_config: dict
) -> None:
    """Test vulnerability analysis with malformed LLM response."""
    state = PatcherAgentState(
        context=root_cause_agent.input,
        relevant_code_snippets=[
            ContextCodeSnippet(
                key=CodeSnippetKey(file_path="/src/example_project/test.c", identifier="main"),
                start_line=1,
                end_line=1,
                code="int main() { int a = foo(); return a; }",
                code_context="",
            ),
        ],
    )

    # Mock LLM response with invalid data
    mock_llm.invoke.return_value = "Invalid response format"

    result = root_cause_agent.analyze_vulnerability(state)

    assert isinstance(result, Command)
    assert result.goto == PatcherAgentName.CREATE_PATCH.value
    assert "root_cause" in result.update
    assert isinstance(result.update["root_cause"], RootCauseAnalysis)
    assert result.update["root_cause"].root_cause == "Invalid response format"


def test_analyze_vulnerability_empty_snippets(
    root_cause_agent: RootCauseAgent, mock_llm: MagicMock, mock_runnable_config: dict
) -> None:
    """Test vulnerability analysis with no code snippets."""
    state = PatcherAgentState(
        context=root_cause_agent.input,
        relevant_code_snippets=[],
    )

    # Mock LLM response requesting more information
    mock_llm.invoke.return_value = """
<vulnerability_analysis>
<code_snippet_requests>Need code snippets to analyze the vulnerability</code_snippet_requests>
<classification></classification>
<root_cause></root_cause>
<affected_variables></affected_variables>
<trigger_conditions></trigger_conditions>
<data_flow_analysis></data_flow_analysis>
<security_constraints></security_constraints>
</vulnerability_analysis>
    """

    result = root_cause_agent.analyze_vulnerability(state)

    assert isinstance(result, Command)
    assert result.goto == PatcherAgentName.REFLECTION.value
    assert "root_cause" in result.update
    assert isinstance(result.update["root_cause"], RootCauseAnalysis)
    assert result.update["root_cause"].code_snippet_requests == "Need code snippets to analyze the vulnerability"


def test_analyze_vulnerability_malformed_but_structured_response(
    root_cause_agent: RootCauseAgent, mock_llm: MagicMock, mock_runnable_config: dict
) -> None:
    """Test vulnerability analysis with malformed but structured LLM response."""
    state = PatcherAgentState(
        context=root_cause_agent.input,
        relevant_code_snippets=[
            ContextCodeSnippet(
                key=CodeSnippetKey(file_path="/src/example_project/test.c", identifier="main"),
                start_line=1,
                end_line=1,
                code="int main() { int a = foo(); return a; }",
                code_context="",
            ),
        ],
    )

    # Mock LLM response with malformed but JSON-like data
    mock_llm.invoke.return_value = """
<vulnerability_analysis>
<classification>Buffer Overflow / Stack Overflow</classification>
<root_cause>The vulnerability occurs in the buffer copy operation where there is insufficient bounds checking. The code fails to validate the input size before copying data into a fixed-size buffer.</root_cause>
<affected_variables>buffer: The destination buffer that gets overflowed, size: The input size parameter that isn't properly validated, input_data: The source data being copied</affected_variables>
<trigger_conditions>Input size exceeds buffer capacity, No bounds checking before copy operation, Input validation is missing</trigger_conditions>
<data_flow_analysis>Data is read from input, Data is copied to buffer without bounds check</data_flow_analysis>
<security_constraints>Buffer size must be validated before copy</security_constraints>
</vulnerability_analysis>
    """

    result = root_cause_agent.analyze_vulnerability(state)

    assert isinstance(result, Command)
    assert result.goto == PatcherAgentName.CREATE_PATCH.value
    assert "root_cause" in result.update
    assert isinstance(result.update["root_cause"], RootCauseAnalysis)

    root_cause = result.update["root_cause"]
    assert "Buffer Overflow / Stack Overflow" in root_cause.classification
    assert "insufficient bounds checking" in root_cause.root_cause.lower()
    assert "buffer" in root_cause.affected_variables
    assert "size" in root_cause.affected_variables
    assert "input_data" in root_cause.affected_variables
    assert "Input size exceeds buffer capacity" in root_cause.trigger_conditions
    assert "No bounds checking before copy operation" in root_cause.trigger_conditions
    assert "Input validation is missing" in root_cause.trigger_conditions
    assert "Data is read from input" in root_cause.data_flow_analysis
    assert "Data is copied to buffer without bounds check" in root_cause.data_flow_analysis
    assert "Buffer size must be validated before copy" in root_cause.security_constraints
