"""Tests for the Quality Engineer agent's patch validation functionality."""

import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch
import os
from langgraph.types import Command
from langgraph.constants import END
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableSequence
from buttercup.patcher.agents.common import (
    PatcherAgentState,
    PatcherAgentName,
    PatchAttempt,
    PatchStatus,
    PatchOutput,
)
from buttercup.patcher.agents.qe import QEAgent, PatchValidationState
from buttercup.patcher.agents.config import PatcherConfig
from buttercup.common.challenge_task import ChallengeTask, ChallengeTaskError
from buttercup.patcher.patcher import PatchInput
from buttercup.patcher.utils import PatchInputPoV
from buttercup.common.project_yaml import Language
import subprocess


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
            )
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
            work_dir=tmp_path / "work_dir", tasks_storage=tmp_path / "tasks_storage"
        ).model_dump(),
    }


def test_validate_patch_node_no_patch(
    qe_agent: QEAgent, patcher_agent_state: PatcherAgentState, mock_runnable_config: dict
):
    """Test validate_patch_node when there is no patch to validate."""
    with pytest.raises(RuntimeError, match="No patch to validate"):
        qe_agent.validate_patch_node(patcher_agent_state, mock_runnable_config)


def test_validate_patch_node_invalid_patched_code(
    qe_agent: QEAgent, patcher_agent_state: PatcherAgentState, mock_runnable_config: dict
):
    """Test validate_patch_node when the patched code is invalid."""
    patch_attempt = PatchAttempt(
        patch=PatchOutput(patch="mypath", task_id="test-task-id", internal_patch_id="test-submission"),
        status=PatchStatus.SUCCESS,
        build_succeeded=True,
        pov_fixed=True,
        tests_passed=True,
    )
    patcher_agent_state.patch_attempts = [patch_attempt]

    # Mock the chain to return an invalid response
    qe_agent.check_harness_changes_chain = MagicMock()
    state = PatchValidationState(
        messages=[AIMessage(content="<is_valid>false</is_valid>")],
        work_dir=mock_runnable_config["configurable"]["work_dir"],
        challenge_task_dir=qe_agent.challenge.task_dir,
        patch=patch_attempt,
    )
    qe_agent.check_harness_changes_chain.invoke.return_value = state

    # Mock ProjectYaml for language validation
    with patch("buttercup.patcher.agents.qe.ProjectYaml") as mock_project_yaml:
        mock_yaml = MagicMock()
        mock_yaml.unified_language = Language.C
        mock_project_yaml.return_value = mock_yaml

        command = qe_agent.validate_patch_node(patcher_agent_state, mock_runnable_config)

        assert isinstance(command, Command)
        assert command.goto == PatcherAgentName.REFLECTION.value
        assert "patch_attempts" in command.update
        assert command.update["patch_attempts"].status == PatchStatus.VALIDATION_FAILED


def test_validate_patch_node_invalid_patched_language(
    qe_agent: QEAgent, patcher_agent_state: PatcherAgentState, mock_runnable_config: dict
):
    """Test validate_patch_node when the patched language is invalid."""
    patch_attempt = PatchAttempt(
        patch=PatchOutput(patch="mypath", task_id="test-task-id", internal_patch_id="test-submission"),
        status=PatchStatus.SUCCESS,
        build_succeeded=True,
        pov_fixed=True,
        tests_passed=True,
    )
    patcher_agent_state.patch_attempts = [patch_attempt]

    # Mock the chain to return a valid response for code but invalid for language
    qe_agent.check_harness_changes_chain = MagicMock()
    state = PatchValidationState(
        messages=[AIMessage(content="<is_valid>true</is_valid>")],
        work_dir=mock_runnable_config["configurable"]["work_dir"],
        challenge_task_dir=qe_agent.challenge.task_dir,
        patch=patch_attempt,
    )
    qe_agent.check_harness_changes_chain.invoke.return_value = state

    # Mock ProjectYaml for language validation
    with (
        patch("buttercup.patcher.agents.qe.ProjectYaml") as mock_project_yaml,
        patch.object(qe_agent, "_is_valid_patched_language", return_value=False),
    ):
        mock_yaml = MagicMock()
        mock_yaml.unified_language = Language.C
        mock_project_yaml.return_value = mock_yaml

        command = qe_agent.validate_patch_node(patcher_agent_state, mock_runnable_config)

        assert isinstance(command, Command)
        assert command.goto == PatcherAgentName.REFLECTION.value
        assert "patch_attempts" in command.update
        assert command.update["patch_attempts"].status == PatchStatus.VALIDATION_FAILED


def test_validate_patch_node_success(
    qe_agent: QEAgent, patcher_agent_state: PatcherAgentState, mock_runnable_config: dict
):
    """Test validate_patch_node when validation succeeds."""
    patch_attempt = PatchAttempt(
        patch=PatchOutput(patch="mypath", task_id="test-task-id", internal_patch_id="test-submission"),
        status=PatchStatus.SUCCESS,
        build_succeeded=True,
        pov_fixed=True,
        tests_passed=True,
    )
    patcher_agent_state.patch_attempts = [patch_attempt]

    # Mock the chain to return a valid response
    qe_agent.check_harness_changes_chain = MagicMock()
    state = PatchValidationState(
        messages=[AIMessage(content="<is_valid>true</is_valid>")],
        work_dir=mock_runnable_config["configurable"]["work_dir"],
        challenge_task_dir=qe_agent.challenge.task_dir,
        patch=patch_attempt,
    )
    qe_agent.check_harness_changes_chain.invoke.return_value = state

    # Mock ProjectYaml for language validation
    with (
        patch("buttercup.patcher.agents.qe.ProjectYaml") as mock_project_yaml,
        patch.object(qe_agent, "_is_valid_patched_language", return_value=True),
    ):
        mock_yaml = MagicMock()
        mock_yaml.unified_language = Language.C
        mock_project_yaml.return_value = mock_yaml

        command = qe_agent.validate_patch_node(patcher_agent_state, mock_runnable_config)

        assert isinstance(command, Command)
        assert command.goto == END


def test_validate_patch_node_missing_is_valid_tag(
    qe_agent: QEAgent, patcher_agent_state: PatcherAgentState, mock_runnable_config: dict
):
    """Test validate_patch_node when the LLM response doesn't contain the is_valid tag."""
    patch_attempt = PatchAttempt(
        patch=PatchOutput(patch="mypath", task_id="test-task-id", internal_patch_id="test-submission"),
        status=PatchStatus.SUCCESS,
        build_succeeded=True,
        pov_fixed=True,
        tests_passed=True,
    )
    patcher_agent_state.patch_attempts = [patch_attempt]

    # Mock the chain to return a response without is_valid tag
    qe_agent.check_harness_changes_chain = MagicMock()
    state = PatchValidationState(
        messages=[AIMessage(content="<think>I analyzed the code but forgot to add the is_valid tag</think>")],
        work_dir=mock_runnable_config["configurable"]["work_dir"],
        challenge_task_dir=qe_agent.challenge.task_dir,
        patch=patch_attempt,
    )
    qe_agent.check_harness_changes_chain.invoke.return_value = state

    # Mock ProjectYaml for language validation
    with patch("buttercup.patcher.agents.qe.ProjectYaml") as mock_project_yaml:
        mock_yaml = MagicMock()
        mock_yaml.unified_language = Language.C
        mock_project_yaml.return_value = mock_yaml

        command = qe_agent.validate_patch_node(patcher_agent_state, mock_runnable_config)

        assert isinstance(command, Command)
        assert command.goto == PatcherAgentName.REFLECTION.value
        assert "patch_attempts" in command.update
        assert command.update["patch_attempts"].status == PatchStatus.VALIDATION_FAILED


def test_validate_patch_node_invalid_is_valid_value(
    qe_agent: QEAgent, patcher_agent_state: PatcherAgentState, mock_runnable_config: dict
):
    """Test validate_patch_node when the LLM returns an invalid value in the is_valid tag."""
    patch_attempt = PatchAttempt(
        patch=PatchOutput(patch="mypath", task_id="test-task-id", internal_patch_id="test-submission"),
        status=PatchStatus.SUCCESS,
        build_succeeded=True,
        pov_fixed=True,
        tests_passed=True,
    )
    patcher_agent_state.patch_attempts = [patch_attempt]

    # Mock the chain to return a response with invalid is_valid value
    qe_agent.check_harness_changes_chain = MagicMock()
    state = PatchValidationState(
        messages=[AIMessage(content="<is_valid>maybe</is_valid>")],
        work_dir=mock_runnable_config["configurable"]["work_dir"],
        challenge_task_dir=qe_agent.challenge.task_dir,
        patch=patch_attempt,
    )
    qe_agent.check_harness_changes_chain.invoke.return_value = state

    # Mock ProjectYaml for language validation
    with patch("buttercup.patcher.agents.qe.ProjectYaml") as mock_project_yaml:
        mock_yaml = MagicMock()
        mock_yaml.unified_language = Language.C
        mock_project_yaml.return_value = mock_yaml

        command = qe_agent.validate_patch_node(patcher_agent_state, mock_runnable_config)

        assert isinstance(command, Command)
        assert command.goto == PatcherAgentName.REFLECTION.value
        assert "patch_attempts" in command.update
        assert command.update["patch_attempts"].status == PatchStatus.VALIDATION_FAILED


def test_is_valid_patched_language_success(
    qe_agent: QEAgent, patcher_agent_state: PatcherAgentState, mock_runnable_config: dict
):
    """Test _is_valid_patched_language when all files are in the correct language."""
    patch_attempt = PatchAttempt(
        patch=PatchOutput(
            patch="""diff --git a/src/main.c b/src/main.c
--- a/src/main.c
+++ b/src/main.c
@@ -1,3 +1,3 @@
 def main():
-    return 0
+    return 1
 }

""",
            task_id="test-task-id",
            internal_patch_id="test-submission",
        ),
        status=PatchStatus.SUCCESS,
        build_succeeded=True,
        pov_fixed=True,
        tests_passed=True,
    )
    patcher_agent_state.patch_attempts = [patch_attempt]

    # Mock subprocess.run, ProjectYaml and Path.exists
    with (
        patch("subprocess.run") as mock_run,
        patch("buttercup.patcher.agents.qe.ProjectYaml") as mock_project_yaml,
        patch("pathlib.Path.exists") as mock_exists,
    ):
        # Mock ProjectYaml to return expected language
        mock_yaml = MagicMock()
        mock_yaml.unified_language = Language.C
        mock_project_yaml.return_value = mock_yaml

        # Mock successful language check
        mock_run.return_value = MagicMock(returncode=0)

        # Mock file existence check
        mock_exists.return_value = True

        assert qe_agent._is_valid_patched_language(patch_attempt) is True

        # Verify subprocess.run was called with correct arguments
        mock_run.assert_called_once()
        args, _ = mock_run.call_args
        cmd_args = args[0]  # First argument is the command list
        expected_path = Path(qe_agent.challenge.get_source_path()) / "src/main.c"

        # Verify command structure
        assert len(cmd_args) == 5  # binary + 4 arguments
        assert cmd_args[1] == "--language"
        assert cmd_args[2] == "c"  # Language from ProjectYaml
        assert cmd_args[3] == "--path"
        assert cmd_args[4] == str(expected_path)


def test_is_valid_patched_language_wrong_language(
    qe_agent: QEAgent, patcher_agent_state: PatcherAgentState, mock_runnable_config: dict
):
    """Test _is_valid_patched_language when a file is in the wrong language."""
    patch_attempt = PatchAttempt(
        patch=PatchOutput(
            patch="""diff --git a/src/main.py b/src/main.py
--- a/src/main.py
+++ b/src/main.py
@@ -1,3 +1,3 @@
 def main():
-    return 0
+    return 1
 }

""",
            task_id="test-task-id",
            internal_patch_id="test-submission",
        ),
        status=PatchStatus.SUCCESS,
        build_succeeded=True,
        pov_fixed=True,
        tests_passed=True,
    )
    patcher_agent_state.patch_attempts = [patch_attempt]

    # Mock subprocess.run, ProjectYaml and Path.exists
    with (
        patch("subprocess.run") as mock_run,
        patch("buttercup.patcher.agents.qe.ProjectYaml") as mock_project_yaml,
        patch("pathlib.Path.exists") as mock_exists,
    ):
        # Mock ProjectYaml to return expected language
        mock_yaml = MagicMock()
        mock_yaml.unified_language = Language.C
        mock_project_yaml.return_value = mock_yaml

        # Mock language check failure
        mock_run.return_value = MagicMock(returncode=1, stderr="Not valid C code")

        # Mock file existence check
        mock_exists.return_value = True

        assert qe_agent._is_valid_patched_language(patch_attempt) is False
        mock_run.assert_called_once()
        args, _ = mock_run.call_args
        cmd_args = args[0]
        expected_path = Path(qe_agent.challenge.get_source_path()) / "src/main.py"

        assert len(cmd_args) == 5
        assert cmd_args[1] == "--language"
        assert cmd_args[2] == "c"
        assert cmd_args[3] == "--path"
        assert cmd_args[4] == str(expected_path)


def test_is_valid_patched_language_missing_binary(
    qe_agent: QEAgent, patcher_agent_state: PatcherAgentState, mock_runnable_config: dict
):
    """Test _is_valid_patched_language when the language identifier binary is missing."""
    patch_attempt = PatchAttempt(
        patch=PatchOutput(
            patch="""diff --git a/src/main.py b/src/main.py
--- a/src/main.py
+++ b/src/main.py
@@ -1,3 +1,3 @@
 def main():
-    return 0
+    return 1
 }

""",
            task_id="test-task-id",
            internal_patch_id="test-submission",
        ),
        status=PatchStatus.SUCCESS,
        build_succeeded=True,
        pov_fixed=True,
        tests_passed=True,
    )
    patcher_agent_state.patch_attempts = [patch_attempt]

    # Mock ProjectYaml and Path
    with (
        patch("buttercup.patcher.agents.qe.ProjectYaml") as mock_project_yaml,
        patch("pathlib.Path") as mock_path,
    ):
        # Mock ProjectYaml to return expected language
        mock_yaml = MagicMock()
        mock_yaml.unified_language = Language.C
        mock_project_yaml.return_value = mock_yaml

        # Create a mock Path instance
        mock_path_instance = MagicMock()
        mock_path.return_value = mock_path_instance

        # Mock exists method to return False for language identifier binary
        def exists_side_effect():
            return not str(mock_path_instance).endswith("language-identifier")

        mock_path_instance.exists.side_effect = exists_side_effect

        assert qe_agent._is_valid_patched_language(patch_attempt) is False


def test_is_valid_patched_language_missing_file(
    qe_agent: QEAgent, patcher_agent_state: PatcherAgentState, mock_runnable_config: dict
):
    """Test _is_valid_patched_language when a modified file doesn't exist."""
    patch_attempt = PatchAttempt(
        patch=PatchOutput(
            patch="""diff --git a/src/main.py b/src/main.py
--- a/src/main.py
+++ b/src/main.py
@@ -1,3 +1,3 @@
 def main():
-    return 0
+    return 1
 }

""",
            task_id="test-task-id",
            internal_patch_id="test-submission",
        ),
        status=PatchStatus.SUCCESS,
        build_succeeded=True,
        pov_fixed=True,
        tests_passed=True,
    )
    patcher_agent_state.patch_attempts = [patch_attempt]

    # Mock ProjectYaml and Path
    with (
        patch("buttercup.patcher.agents.qe.ProjectYaml") as mock_project_yaml,
        patch("pathlib.Path") as mock_path,
    ):
        # Mock ProjectYaml to return expected language
        mock_yaml = MagicMock()
        mock_yaml.unified_language = Language.C
        mock_project_yaml.return_value = mock_yaml

        # Create a mock Path instance
        mock_path_instance = MagicMock()
        mock_path.return_value = mock_path_instance

        # Mock exists method to return True only for language identifier binary
        def exists_side_effect():
            return str(mock_path_instance).endswith("language-identifier")

        mock_path_instance.exists.side_effect = exists_side_effect

        assert qe_agent._is_valid_patched_language(patch_attempt) is False


def test_is_valid_patched_language_subprocess_error(
    qe_agent: QEAgent, patcher_agent_state: PatcherAgentState, mock_runnable_config: dict
):
    """Test _is_valid_patched_language when subprocess.run raises an error."""
    patch_attempt = PatchAttempt(
        patch=PatchOutput(
            patch="""diff --git a/src/main.c b/src/main.c
--- a/src/main.c
+++ b/src/main.c
@@ -1,3 +1,3 @@
 def main():
-    return 0
+    return 1
 }

""",
            task_id="test-task-id",
            internal_patch_id="test-submission",
        ),
        status=PatchStatus.SUCCESS,
        build_succeeded=True,
        pov_fixed=True,
        tests_passed=True,
    )
    patcher_agent_state.patch_attempts = [patch_attempt]

    # Mock subprocess.run, ProjectYaml and Path.exists
    with (
        patch("subprocess.run") as mock_run,
        patch("buttercup.patcher.agents.qe.ProjectYaml") as mock_project_yaml,
        patch("pathlib.Path.exists") as mock_exists,
    ):
        # Mock ProjectYaml to return expected language
        mock_yaml = MagicMock()
        mock_yaml.unified_language = Language.C
        mock_project_yaml.return_value = mock_yaml

        # Mock subprocess error
        mock_run.side_effect = subprocess.CalledProcessError(1, "cmd", stderr="Error")

        # Mock file existence check
        mock_exists.return_value = True

        assert qe_agent._is_valid_patched_language(patch_attempt) is False
        mock_run.assert_called_once()
        args, _ = mock_run.call_args
        cmd_args = args[0]
        expected_path = Path(qe_agent.challenge.get_source_path()) / "src/main.c"

        assert len(cmd_args) == 5
        assert cmd_args[1] == "--language"
        assert cmd_args[2] == "c"
        assert cmd_args[3] == "--path"
        assert cmd_args[4] == str(expected_path)


def test_run_pov_node_various_outcomes(qe_agent, patcher_agent_state, mock_runnable_config):
    """Test run_pov_node with different PoV and reproduce_pov outcomes."""

    # Setup: PatchAttempt with built_challenges for two sanitizers
    def get_clean_patch_attempt():
        return PatchAttempt(
            patch=PatchOutput(
                patch="diff --git a/a b/a\n", task_id="test-task-id", internal_patch_id="test-submission"
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
