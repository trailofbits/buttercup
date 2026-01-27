"""Tests for the Quality Engineer agent's patch validation functionality."""

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from buttercup.common.challenge_task import ChallengeTask, ChallengeTaskError
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableSequence
from langgraph.types import Command

from buttercup.patcher.agents.common import (
    PatchAttempt,
    PatcherAgentName,
    PatcherAgentState,
    PatchOutput,
    PatchStatus,
)
from buttercup.patcher.agents.config import PatcherConfig
from buttercup.patcher.agents.qe import QEAgent
from buttercup.patcher.patcher import PatchInput
from buttercup.patcher.utils import PatchInputPoV


@pytest.fixture
def mock_llm():
    """Create a mock LLM for testing."""
    llm = MagicMock(spec=BaseChatModel)
    llm.__or__.return_value = llm
    return llm


@pytest.fixture(autouse=True)
def mock_llm_functions(mock_llm: MagicMock):
    """Mock LLM creation functions and environment variables."""
    with (
        patch.dict(os.environ, {"BUTTERCUP_LITELLM_HOSTNAME": "http://test-host", "BUTTERCUP_LITELLM_KEY": "test-key"}),
        patch("buttercup.common.llm.create_default_llm", return_value=mock_llm),
        patch("buttercup.common.llm.create_llm", return_value=mock_llm),
        patch("langgraph.prebuilt.chat_agent_executor._get_prompt_runnable", return_value=mock_llm),
    ):
        import buttercup.patcher.agents.qe

        # Create a mock chain that returns a boolean
        mock_chain = MagicMock(spec=RunnableSequence)
        mock_chain.invoke.return_value = {"messages": [AIMessage(content="<is_valid>true</is_valid>")]}

        # Mock the chain creation and output parser
        buttercup.patcher.agents.qe.QEAgent._parse_check_harness_changes_output = (
            lambda self: lambda x: x["messages"][-1].content.strip().lower() == "true"
        )
        buttercup.patcher.agents.qe.QEAgent.check_harness_changes_chain = mock_chain
        yield


@pytest.fixture
def mock_challenge() -> ChallengeTask:
    """Create a mock challenge task for testing."""
    challenge = MagicMock(spec=ChallengeTask)
    challenge.name = "test-project"
    challenge.task_dir = Path("/tmp/test-project")
    return challenge


@pytest.fixture
def mock_patch_input(tmp_path: Path) -> PatchInput:
    """Create a mock patch input for testing."""
    return PatchInput(
        challenge_task_dir=tmp_path,
        task_id="test-task-id",
        internal_patch_id="test-submission",
        povs=[
            PatchInputPoV(
                challenge_task_dir=tmp_path,
                sanitizer="address",
                pov=tmp_path / "pov.c",
                pov_token="test-token",
                sanitizer_output="test-sanitizer-output",
                engine="libfuzzer",
                harness_name="test-harness",
            ),
        ],
    )


@pytest.fixture
def qe_agent(mock_challenge: ChallengeTask, mock_patch_input: PatchInput) -> QEAgent:
    """Create a QE agent instance for testing."""
    return QEAgent(
        challenge=mock_challenge,
        input=mock_patch_input,
        chain_call=lambda _, runnable, args, config, default: runnable.invoke(args, config=config),
    )


@pytest.fixture
def patcher_agent_state(mock_patch_input: PatchInput) -> PatcherAgentState:
    """Create a PatcherAgentState instance."""
    return PatcherAgentState(
        context=mock_patch_input,
        messages=[],
        relevant_code_snippets=[],
    )


@pytest.fixture
def mock_runnable_config(tmp_path: Path) -> dict:
    """Create a mock runnable config."""
    return {
        "configurable": PatcherConfig(
            work_dir=tmp_path / "work_dir",
            tasks_storage=tmp_path / "tasks_storage",
        ).model_dump(),
    }


def test_run_pov_node_various_outcomes(qe_agent, patcher_agent_state, mock_runnable_config):
    """Test run_pov_node with different PoV and reproduce_pov outcomes."""

    # Setup: PatchAttempt with built_challenges for two sanitizers
    def get_clean_patch_attempt():
        return PatchAttempt(
            patch=PatchOutput(
                patch="diff --git a/a b/a\n",
                task_id="test-task-id",
                internal_patch_id="test-submission",
            ),
            status=PatchStatus.SUCCESS,
            build_succeeded=True,
            pov_fixed=None,
            tests_passed=None,
            built_challenges={},
        )

    def get_clean_state():
        patch_attempt = get_clean_patch_attempt()
        patcher_agent_state.patch_attempts = [patch_attempt]
        return patcher_agent_state

    patcher_agent_state = get_clean_state()
    patch_attempt = patcher_agent_state.patch_attempts[0]

    # Mock configuration
    config = mock_runnable_config

    # Add task_meta to mock challenge
    qe_agent.challenge.task_meta = MagicMock()
    qe_agent.challenge.task_meta.task_id = "test-task-id"

    # Prepare two PoVs
    pov1 = PatchInputPoV(
        challenge_task_dir=qe_agent.challenge.task_dir,
        sanitizer="address",
        pov=Path("/tmp/pov1"),
        pov_token="token1",
        sanitizer_output="output1",
        engine="libfuzzer",
        harness_name="harness1",
    )
    pov2 = PatchInputPoV(
        challenge_task_dir=qe_agent.challenge.task_dir,
        sanitizer="memory",
        pov=Path("/tmp/pov2"),
        pov_token="token2",
        sanitizer_output="output2",
        engine="libfuzzer",
        harness_name="harness2",
    )
    patcher_agent_state.context.povs = [pov1, pov2]

    # Mock _get_pov_variants to return both povs and a variant
    pov_variant = PatchInputPoV(
        challenge_task_dir=qe_agent.challenge.task_dir,
        sanitizer="address",
        pov=Path("/tmp/pov1_variant"),
        pov_token="token1",
        sanitizer_output="output1",
        engine="libfuzzer",
        harness_name="harness1",
    )
    with patch.object(qe_agent, "_get_pov_variants", return_value=[pov1, pov2, pov_variant]):
        # Mock node_local.make_locally_available to just return the path
        with patch("buttercup.common.node_local.make_locally_available", side_effect=lambda p: p):
            # Mock PatchAttempt.get_built_challenge to return a mock challenge for each sanitizer
            mock_challenge1 = MagicMock()
            mock_challenge2 = MagicMock()
            with patch.object(
                PatchAttempt,
                "get_built_challenge",
                side_effect=lambda sanitizer: {"address": mock_challenge1, "memory": mock_challenge2}.get(sanitizer),
            ):
                # Case 1: All PoVs run and do not crash
                mock_pov_output = MagicMock()
                mock_pov_output.did_run.return_value = True
                mock_pov_output.did_crash.return_value = False
                mock_challenge1.reproduce_pov.return_value = mock_pov_output
                mock_challenge2.reproduce_pov.return_value = mock_pov_output

                result = qe_agent.run_pov_node(patcher_agent_state, config)
                assert isinstance(result, Command)
                assert result.goto == PatcherAgentName.RUN_TESTS.value
                assert patch_attempt.pov_fixed is True

                # Case 2: First PoV does not run, second runs and does not crash
                patcher_agent_state = get_clean_state()
                patch_attempt = patcher_agent_state.patch_attempts[0]
                mock_pov_output.did_run.side_effect = [False, True, True]
                mock_pov_output.did_crash.side_effect = [False, False, False]
                result = qe_agent.run_pov_node(patcher_agent_state, config)
                assert result.goto == PatcherAgentName.RUN_TESTS.value

                # Case 3: First PoV runs and crashes
                patcher_agent_state = get_clean_state()
                patch_attempt = patcher_agent_state.patch_attempts[0]
                mock_pov_output = MagicMock()
                mock_pov_output.did_run.return_value = True
                mock_pov_output.did_crash.return_value = True
                mock_pov_output.command_result.output = b"crash output"
                mock_pov_output.command_result.error = b"crash error"
                mock_challenge1.reproduce_pov.return_value = mock_pov_output
                mock_challenge2.reproduce_pov.return_value = mock_pov_output
                result = qe_agent.run_pov_node(patcher_agent_state, config)
                assert result.goto == PatcherAgentName.REFLECTION.value
                assert patch_attempt.pov_fixed is False
                assert patch_attempt.pov_stdout == b"crash output"
                assert patch_attempt.pov_stderr == b"crash error"

                # Case 4: ChallengeTaskError is raised
                def raise_challenge_task_error(*args, **kwargs):
                    raise ChallengeTaskError("fail test")

                patcher_agent_state = get_clean_state()
                patch_attempt = patcher_agent_state.patch_attempts[0]
                mock_challenge1.reproduce_pov.side_effect = raise_challenge_task_error
                mock_challenge2.reproduce_pov.side_effect = raise_challenge_task_error  # Make both challenges fail
                result = qe_agent.run_pov_node(patcher_agent_state, config)
                assert result.goto == PatcherAgentName.ROOT_CAUSE_ANALYSIS.value
                assert patch_attempt.pov_fixed is False
                assert patch_attempt.pov_stdout is None
                assert patch_attempt.pov_stderr is None

                # Case 5: No PoVs could be run (all get_built_challenge returns None)
                with patch.object(PatchAttempt, "get_built_challenge", return_value=None):
                    patcher_agent_state = get_clean_state()
                    patch_attempt = patcher_agent_state.patch_attempts[0]
                    result = qe_agent.run_pov_node(patcher_agent_state, config)
                    assert result.goto == PatcherAgentName.ROOT_CAUSE_ANALYSIS.value
                    assert patch_attempt.pov_fixed is False
