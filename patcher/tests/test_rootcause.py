"""Tests for the RootCauseAgent."""

import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch
import os
from typing import Any, Callable

from langchain_core.runnables import Runnable, RunnableConfig
from langgraph.types import Command
from buttercup.common.challenge_task import ChallengeTask
from buttercup.common.task_meta import TaskMeta
from buttercup.patcher.agents.rootcause import RootCauseAgent
from buttercup.patcher.agents.common import PatcherAgentState, PatcherAgentName
from buttercup.patcher.patcher import PatchInput
from buttercup.patcher.agents.common import ContextCodeSnippet, CodeSnippetKey


@pytest.fixture
def mock_llm():
    return MagicMock()


@pytest.fixture
def mock_chain(mock_llm: MagicMock):
    res = MagicMock()
    res.with_fallbacks.return_value = mock_llm
    res.with_fallbacks.return_value.bind_tools.return_value = mock_llm
    return res


@pytest.fixture(autouse=True)
def mock_llm_functions(mock_chain: MagicMock):
    """Mock LLM creation functions and environment variables."""
    with (
        patch.dict(os.environ, {"BUTTERCUP_LITELLM_HOSTNAME": "http://test-host", "BUTTERCUP_LITELLM_KEY": "test-key"}),
        patch("buttercup.common.llm.create_default_llm", return_value=mock_chain),
        patch("buttercup.common.llm.create_llm", return_value=mock_chain),
    ):
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
    (source / "test.c").write_text("int main() { return 0; }")
    (source / "test.h").write_text("struct ebitmap_t { int a; };")

    TaskMeta(project_name="example_project", focus="my-source", task_id="task-id-challenge-task").save(tmp_path)

    return tmp_path


@pytest.fixture
def mock_challenge(task_dir: Path) -> ChallengeTask:
    """Create a mock challenge task for testing."""
    return ChallengeTask(
        read_only_task_dir=task_dir,
        local_task_dir=task_dir,
    )


def _chain_call(
    reduce_function: Callable,
    runnable: Runnable,
    args: dict[str, Any],
    config: RunnableConfig | None = None,
    default: Any = None,
) -> Any:
    return runnable.invoke(args, config=config)


@pytest.fixture
def mock_agent(mock_challenge: ChallengeTask, tmp_path: Path) -> RootCauseAgent:
    """Create a RootCauseAgent instance."""
    patch_input = PatchInput(
        challenge_task_dir=mock_challenge.task_dir,
        task_id=mock_challenge.task_meta.task_id,
        vulnerability_id="vuln-id-mock",
        harness_name="mock-harness",
        # not used by the context retriever
        pov=Path("pov-path-mock"),
        sanitizer_output="sanitizer-output-mock",
        engine="libfuzzer",
        sanitizer="address",
    )
    wdir = tmp_path / "work_dir"
    wdir.mkdir(parents=True)
    return RootCauseAgent(
        input=patch_input,
        chain_call=_chain_call,
        challenge=mock_challenge,
    )


@pytest.fixture
def patcher_agent_state(mock_agent: RootCauseAgent) -> PatcherAgentState:
    """Create a PatcherAgentState instance."""
    return PatcherAgentState(
        context=mock_agent.input,
        messages=[],
        relevant_code_snippets=[
            ContextCodeSnippet(
                key=CodeSnippetKey(file_path="src/test.c", identifier="main"),
                code="int main() { return 0; }",
            ),
        ],
    )


def test_rootcause_simple_request(mock_agent: RootCauseAgent, patcher_agent_state: PatcherAgentState) -> None:
    """Test that the agent requests a code snippet."""
    mock_agent.root_cause_chain = MagicMock()
    mock_agent.root_cause_chain.invoke.side_effect = [
        """
        <code_request>
        Find the function definition for main
        </code_request>
        """,
    ]

    result = mock_agent.analyze_vulnerability(patcher_agent_state)

    assert isinstance(result, Command)
    assert result.goto == PatcherAgentName.CONTEXT_RETRIEVER.value
    assert len(result.update["code_snippet_requests"]) == 1
    assert result.update["code_snippet_requests"][0].request == "Find the function definition for main"


def test_rootcause_multiple_requests(mock_agent: RootCauseAgent, patcher_agent_state: PatcherAgentState) -> None:
    """Test that the agent requests multiple code snippets."""
    mock_agent.root_cause_chain = MagicMock()
    mock_agent.root_cause_chain.invoke.side_effect = [
        """
        <code_request>
        Find the function definition for main
        </code_request>
    <code_request> Find the function definition for main2</code_request>
            <code_request>Find the function definition for main3   </code_request>
        <code_request>Find the function definition for 
        main4</code_request>
        <code_request>Find the function definition for main5</code_request>
        
<code_request>
        Find the function definition for main6
    </code_request>
        """,
    ]

    result = mock_agent.analyze_vulnerability(patcher_agent_state)

    assert isinstance(result, Command)
    assert result.goto == PatcherAgentName.CONTEXT_RETRIEVER.value
    assert len(result.update["code_snippet_requests"]) == 6
    assert result.update["code_snippet_requests"][0].request == "Find the function definition for main"
    assert result.update["code_snippet_requests"][1].request == "Find the function definition for main2"
    assert result.update["code_snippet_requests"][2].request == "Find the function definition for main3"
    assert result.update["code_snippet_requests"][3].request == "Find the function definition for \n        main4"
    assert result.update["code_snippet_requests"][4].request == "Find the function definition for main5"
    assert result.update["code_snippet_requests"][5].request == "Find the function definition for main6"


def test_no_code_snippet_requests(mock_agent: RootCauseAgent, patcher_agent_state: PatcherAgentState) -> None:
    """Test that no code snippets are requested if not asked by the LLM when there are some snippets already."""
    mock_agent.root_cause_chain = MagicMock()
    mock_agent.root_cause_chain.invoke.side_effect = ["This is my analysis."]

    result = mock_agent.analyze_vulnerability(patcher_agent_state)

    assert isinstance(result, Command)
    assert result.goto == PatcherAgentName.CREATE_PATCH.value
    assert "code_snippet_requests" not in result.update


@pytest.mark.skip("TODO: Implement this")
def test_cant_call_with_no_snippets(mock_agent: RootCauseAgent, patcher_agent_state: PatcherAgentState) -> None:
    """Test that the agent can't call with no snippets."""
    patcher_agent_state.relevant_code_snippets = []
    with pytest.raises(ValueError):
        mock_agent.analyze_vulnerability(patcher_agent_state)
