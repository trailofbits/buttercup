"""Tests for the Reflection Agent."""

import pytest
from pathlib import Path
import shutil
import subprocess
from unittest.mock import MagicMock, patch
import os
from langchain_core.language_models import BaseChatModel
from langchain_core.runnables import Runnable, RunnableSequence
from langgraph.types import Command
from langgraph.constants import END

from buttercup.patcher.agents.reflection import ReflectionAgent
from buttercup.patcher.agents.common import (
    PatcherAgentState,
    PatcherAgentName,
    PatchStatus,
    PatchAttempt,
    PatchOutput,
    ExecutionInfo,
)
from buttercup.patcher.patcher import PatchInput
from buttercup.patcher.utils import PatchInputPoV
from buttercup.common.challenge_task import ChallengeTask
from buttercup.common.task_meta import TaskMeta
from buttercup.patcher.agents.config import PatcherConfig


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
def mock_reflection_prompt(mock_llm: MagicMock):
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
def mock_llm_functions(mock_llm: MagicMock, mock_reflection_prompt: MagicMock):
    """Mock LLM creation functions and environment variables."""
    with (
        patch.dict(os.environ, {"BUTTERCUP_LITELLM_HOSTNAME": "http://test-host", "BUTTERCUP_LITELLM_KEY": "test-key"}),
        patch("buttercup.common.llm.create_default_llm", return_value=mock_llm),
        patch("buttercup.common.llm.create_llm", return_value=mock_llm),
        patch("langgraph.prebuilt.chat_agent_executor._get_prompt_runnable", return_value=mock_llm),
    ):
        import buttercup.patcher.agents.reflection

        buttercup.patcher.agents.reflection.PROMPT = mock_reflection_prompt
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
    challenge = ChallengeTask(
        read_only_task_dir=task_dir,
        local_task_dir=task_dir,
    )
    challenge.restore = lambda: None
    return challenge


@pytest.fixture
def reflection_agent(mock_challenge: ChallengeTask, tmp_path: Path) -> ReflectionAgent:
    """Create a ReflectionAgent instance."""
    patch_input = PatchInput(
        challenge_task_dir=mock_challenge.task_dir,
        task_id=mock_challenge.task_meta.task_id,
        internal_patch_id="1",
        povs=[
            PatchInputPoV(
                challenge_task_dir=mock_challenge.task_dir,
                sanitizer="address",
                pov=Path("pov-path-mock"),
                pov_token="pov-token-mock",
                sanitizer_output="sanitizer-output-mock",
                engine="libfuzzer",
                harness_name="mock-harness",
            )
        ],
    )
    return ReflectionAgent(
        challenge=mock_challenge,
        input=patch_input,
        chain_call=lambda _, runnable, args, config, default: runnable.invoke(args, config=config),
    )


@pytest.fixture
def mock_runnable_config(tmp_path: Path) -> dict:
    """Create a mock runnable config."""
    return {
        "configurable": PatcherConfig(
            work_dir=tmp_path / "work_dir",
            tasks_storage=tmp_path / "tasks_storage",
            thread_id="test-thread-id",
            max_patch_retries=3,
        ).model_dump(),
    }


def test_reflect_on_patch_success(reflection_agent: ReflectionAgent, mock_runnable_config: dict) -> None:
    """Test reflection when patch is successful."""
    state = PatcherAgentState(
        context=reflection_agent.input,
        patch_attempts=[
            PatchAttempt(
                patch=PatchOutput(
                    task_id="task-id-challenge-task",
                    internal_patch_id="1",
                    patch="mock patch",
                ),
                status=PatchStatus.SUCCESS,
            ),
        ],
        execution_info=ExecutionInfo(
            prev_node=PatcherAgentName.CREATE_PATCH,
        ),
    )

    result = reflection_agent.reflect_on_patch(state, mock_runnable_config)
    assert isinstance(result, Command)
    assert result.goto == END


def test_reflect_on_patch_max_patch_attempts(reflection_agent: ReflectionAgent, mock_runnable_config: dict) -> None:
    """Test reflection when max patch attempts is reached."""
    config = PatcherConfig.from_configurable(mock_runnable_config)
    state = PatcherAgentState(
        context=reflection_agent.input,
        patch_attempts=[
            PatchAttempt(
                patch=PatchOutput(
                    task_id="task-id-challenge-task",
                    internal_patch_id="1",
                    patch=f"mock patch {i}",
                ),
                status=PatchStatus.CREATION_FAILED,
            )
            for i in range(config.max_patch_retries + 1)
        ],
        execution_info=ExecutionInfo(
            prev_node=PatcherAgentName.CREATE_PATCH,
        ),
    )

    result = reflection_agent.reflect_on_patch(state, mock_runnable_config)
    assert isinstance(result, Command)
    assert result.goto == END


def test_reflect_on_patch_pending(reflection_agent: ReflectionAgent, mock_runnable_config: dict) -> None:
    """Test reflection when patch is in pending status."""
    state = PatcherAgentState(
        context=reflection_agent.input,
        patch_attempts=[
            PatchAttempt(
                patch=PatchOutput(
                    task_id="task-id-challenge-task",
                    internal_patch_id="1",
                    patch="mock patch",
                ),
                status=PatchStatus.PENDING,
            ),
        ],
        execution_info=ExecutionInfo(
            prev_node=PatcherAgentName.CREATE_PATCH,
        ),
    )

    result = reflection_agent.reflect_on_patch(state, mock_runnable_config)
    assert isinstance(result, Command)
    assert result.goto == PatcherAgentName.ROOT_CAUSE_ANALYSIS.value


def test_reflect_on_patch_zero_retries(reflection_agent: ReflectionAgent, tmp_path: Path) -> None:
    """Test reflection with zero max retries configuration."""
    config = {
        "configurable": PatcherConfig(
            work_dir=tmp_path / "work_dir",
            tasks_storage=tmp_path / "tasks_storage",
            thread_id="test-thread-id",
            max_patch_retries=0,
        ).model_dump(),
    }

    state = PatcherAgentState(
        context=reflection_agent.input,
        patch_attempts=[
            PatchAttempt(
                patch=PatchOutput(
                    task_id="task-id-challenge-task",
                    internal_patch_id="1",
                    patch="mock patch",
                ),
                status=PatchStatus.CREATION_FAILED,
            ),
        ],
        execution_info=ExecutionInfo(
            prev_node=PatcherAgentName.CREATE_PATCH,
        ),
    )

    result = reflection_agent.reflect_on_patch(state, config)
    assert isinstance(result, Command)
    assert result.goto == END


def test_reflect_on_patch_high_retries(reflection_agent: ReflectionAgent, tmp_path: Path, mock_llm: MagicMock) -> None:
    """Test reflection with high max retries configuration."""
    config = {
        "configurable": PatcherConfig(
            work_dir=tmp_path / "work_dir",
            tasks_storage=tmp_path / "tasks_storage",
            thread_id="test-thread-id",
            max_patch_retries=100,
        ).model_dump(),
    }

    mock_llm.invoke.return_value = """<reflection_result>
<failure_reason>Test failure reason</failure_reason>
<failure_category>incomplete_fix</failure_category>
<pattern_identified>No clear pattern identified</pattern_identified>
<partial_success>False</partial_success>
<next_component>root_cause_analysis</next_component>
<component_guidance>Test guidance</component_guidance>
</reflection_result>"""

    state = PatcherAgentState(
        context=reflection_agent.input,
        patch_attempts=[
            PatchAttempt(
                patch=PatchOutput(
                    task_id="task-id-challenge-task",
                    internal_patch_id="1",
                    patch="mock patch",
                ),
                status=PatchStatus.CREATION_FAILED,
            ),
        ],
        execution_info=ExecutionInfo(
            prev_node=PatcherAgentName.CREATE_PATCH,
        ),
    )

    result = reflection_agent.reflect_on_patch(state, config)
    assert isinstance(result, Command)
    assert result.goto == PatcherAgentName.ROOT_CAUSE_ANALYSIS.value


def test_reflect_on_patch_invalid_component(reflection_agent: ReflectionAgent, mock_runnable_config: dict) -> None:
    """Test reflection when LLM returns an invalid next component."""
    # Mock the LLM to return an invalid component
    reflection_agent.llm.invoke.return_value = """<reflection_result>
<failure_reason>Test failure reason</failure_reason>
<failure_category>incomplete_fix</failure_category>
<pattern_identified>No clear pattern identified</pattern_identified>
<partial_success>False</partial_success>
<next_component>INVALID_COMPONENT</next_component>
<component_guidance>Test guidance</component_guidance>
</reflection_result>"""

    state = PatcherAgentState(
        context=reflection_agent.input,
        patch_attempts=[
            PatchAttempt(
                patch=PatchOutput(
                    task_id="task-id-challenge-task",
                    internal_patch_id="1",
                    patch="mock patch",
                ),
                status=PatchStatus.CREATION_FAILED,
            ),
        ],
        execution_info=ExecutionInfo(
            prev_node=PatcherAgentName.CREATE_PATCH,
        ),
    )

    result = reflection_agent.reflect_on_patch(state, mock_runnable_config)
    assert isinstance(result, Command)
    # Should default to root cause analysis when invalid component is returned
    assert result.goto == PatcherAgentName.ROOT_CAUSE_ANALYSIS.value
