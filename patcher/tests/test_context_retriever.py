"""Tests for the ContextRetrieverAgent."""

import pytest
import os
from unittest.mock import patch
from pydantic import BaseModel
from contextlib import contextmanager
from langchain_core.tools import tool
from pathlib import Path
import shutil
import subprocess
from langchain_core.tools import StructuredTool
from langchain_core.runnables import Runnable, RunnableSequence
from unittest.mock import MagicMock
from typing import Iterator

from langchain_core.language_models import BaseChatModel
from buttercup.patcher.agents.context_retriever import (
    ContextRetrieverAgent,
)

from buttercup.patcher.agents.common import (
    ContextRetrieverState,
    CodeSnippetRequest,
    PatcherAgentState,
    PatcherAgentName,
    ContextCodeSnippet,
    CodeSnippetKey,
)
from buttercup.patcher.patcher import PatchInput
from buttercup.patcher.utils import PatchInputPoV
from langgraph.types import Command
from buttercup.common.challenge_task import ChallengeTask, CommandResult
from buttercup.common.task_meta import TaskMeta
from langchain_core.messages import AIMessage
from langchain_core.messages.tool import ToolCall
from redis import Redis
from buttercup.patcher.agents.context_retriever import CUSTOM_TEST_MAP_NAME


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
def mock_agent_llm():
    llm = MagicMock(spec=BaseChatModel)
    llm.__or__.return_value = llm
    return llm


@pytest.fixture
def mock_cheap_llm():
    llm = MagicMock(spec=BaseChatModel)
    llm.with_fallbacks.return_value = llm
    llm.configurable_fields.return_value = llm
    llm.with_structured_output.return_value = llm

    llm.invoke.return_value = "FALSE"
    return llm


@pytest.fixture
def mock_duplicate_code_snippet_prompt(mock_cheap_llm: MagicMock):
    prompt = MagicMock(spec=Runnable)

    def mock_or(other):
        global current
        if other == mock_cheap_llm:
            current = mock_cheap_llm
            current.__or__.side_effect = mock_or
            return current

        current = RunnableSequence(current, other)
        return current

    prompt.__or__.side_effect = mock_or
    return prompt


@pytest.fixture
def mock_test_instructions_prompt():
    prompt = MagicMock(spec=Runnable)
    prompt.__or__.return_value = prompt
    return prompt


@pytest.fixture(autouse=True)
def mock_llm_functions(
    mock_agent_llm: MagicMock,
    mock_cheap_llm: MagicMock,
    mock_duplicate_code_snippet_prompt: MagicMock,
    mock_test_instructions_prompt: MagicMock,
):
    """Mock LLM creation functions and environment variables."""
    with (
        patch.dict(os.environ, {"BUTTERCUP_LITELLM_HOSTNAME": "http://test-host", "BUTTERCUP_LITELLM_KEY": "test-key"}),
        patch("buttercup.common.llm.create_default_llm", return_value=mock_cheap_llm),
        patch("buttercup.common.llm.create_llm", return_value=mock_cheap_llm),
        patch("langgraph.prebuilt.chat_agent_executor._get_prompt_runnable", return_value=mock_agent_llm),
    ):
        import buttercup.patcher.agents.context_retriever

        buttercup.patcher.agents.context_retriever.DUPLICATE_CODE_SNIPPET_PROMPT = mock_duplicate_code_snippet_prompt
        buttercup.patcher.agents.context_retriever.TEST_INSTRUCTIONS_PROMPT = mock_test_instructions_prompt
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
def example_libpng_oss_fuzz_task(tmp_path: Path) -> ChallengeTask:
    """Create a challenge task using a real OSS-Fuzz repository."""
    tmp_path = tmp_path / "libpng"
    tmp_path.mkdir(parents=True)

    oss_fuzz_dir = tmp_path / "fuzz-tooling"
    oss_fuzz_dir.mkdir(parents=True)
    source_dir = tmp_path / "src"
    source_dir.mkdir(parents=True)

    subprocess.run(
        [
            "git",
            "-C",
            str(oss_fuzz_dir),
            "clone",
            "git@github.com:aixcc-finals/oss-fuzz-aixcc.git",
        ],
        check=True,
    )
    subprocess.run(
        [
            "git",
            "-C",
            str(oss_fuzz_dir / "oss-fuzz-aixcc"),
            "checkout",
            "39d4001a08bde23d9f78188013a1836904d94e27",
            "--",
            "projects/libpng",
        ],
        check=True,
    )

    # Download selinux source code
    url = "git@github.com:aixcc-finals/example-libpng.git"
    subprocess.run(["git", "-C", str(source_dir), "clone", url], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(source_dir / "example-libpng"),
            "checkout",
            "a5bf8a9719a7203742fbdd413423b3802bfa0f5b",
        ],
        check=True,
    )

    # Create task metadata
    TaskMeta(
        project_name="libpng",
        focus="example-libpng",
        task_id="task-id-libpng",
        metadata={"task_id": "task-id-libpng", "round_id": "testing", "team_id": "tob"},
    ).save(tmp_path)

    challenge_task = ChallengeTask(
        read_only_task_dir=tmp_path,
        local_task_dir=tmp_path,
    )
    challenge_task.OSS_FUZZ_CONTAINER_ORG = "aixcc-afc"
    return challenge_task


@pytest.fixture
def selinux_oss_fuzz_task(tmp_path: Path) -> ChallengeTask:
    """Create a challenge task using a real OSS-Fuzz repository."""
    tmp_path = tmp_path / "selinux"
    tmp_path.mkdir(parents=True)

    oss_fuzz_dir = tmp_path / "fuzz-tooling"
    oss_fuzz_dir.mkdir(parents=True)
    source_dir = tmp_path / "src"
    source_dir.mkdir(parents=True)

    subprocess.run(
        [
            "git",
            "-C",
            str(oss_fuzz_dir),
            "clone",
            "https://github.com/google/oss-fuzz.git",
        ],
        check=True,
    )
    # Restore libjpeg-turbo project directory to specific commit
    subprocess.run(
        [
            "git",
            "-C",
            str(oss_fuzz_dir / "oss-fuzz"),
            "checkout",
            "ef2f42b3b10af381d3d55cc901fde0729e54573b",
            "--",
            "projects/selinux",
        ],
        check=True,
    )

    # Download selinux source code
    url = "https://github.com/SELinuxProject/selinux"
    subprocess.run(["git", "-C", str(source_dir), "clone", url], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(source_dir / "selinux"),
            "checkout",
            "c35919a703302bd571476f245d856174a1fe1926",
        ],
        check=True,
    )

    # Create task metadata
    TaskMeta(
        project_name="selinux",
        focus="selinux",
        task_id="task-id-selinux",
        metadata={"task_id": "task-id-selinux", "round_id": "testing", "team_id": "tob"},
    ).save(tmp_path)

    return ChallengeTask(
        read_only_task_dir=tmp_path,
        local_task_dir=tmp_path,
    )


@pytest.fixture
def selinux_agent(selinux_oss_fuzz_task: ChallengeTask, tmp_path: Path) -> ContextRetrieverAgent:
    """Create a ContextRetrieverAgent instance."""
    patch_input = PatchInput(
        challenge_task_dir=selinux_oss_fuzz_task.task_dir,
        task_id=selinux_oss_fuzz_task.task_meta.task_id,
        internal_patch_id="1",
        povs=[
            PatchInputPoV(
                challenge_task_dir=selinux_oss_fuzz_task.task_dir,
                sanitizer="address",
                pov=Path("pov-path-selinux"),
                pov_token="pov-token-selinux",
                sanitizer_output="sanitizer-output-selinux",
                engine="libfuzzer",
                harness_name="secilc-fuzzer",
            )
        ],
    )
    wdir = tmp_path / "work_dir"
    wdir.mkdir(parents=True)
    return ContextRetrieverAgent(
        input=patch_input,
        chain_call=lambda _, runnable, args, config, default: runnable.invoke(args, config=config),
        challenge=selinux_oss_fuzz_task,
    )


@pytest.fixture
def libpng_agent(example_libpng_oss_fuzz_task: ChallengeTask, tmp_path: Path) -> Iterator[ContextRetrieverAgent]:
    """Create a ContextRetrieverAgent instance."""
    patch_input = PatchInput(
        challenge_task_dir=example_libpng_oss_fuzz_task.task_dir,
        task_id=example_libpng_oss_fuzz_task.task_meta.task_id,
        internal_patch_id="1",
        povs=[
            PatchInputPoV(
                challenge_task_dir=example_libpng_oss_fuzz_task.task_dir,
                sanitizer="address",
                pov=Path("pov-path-libpng"),
                pov_token="pov-token-libpng",
                sanitizer_output="sanitizer-output-libpng",
                engine="libfuzzer",
                harness_name="libpng_read_fuzzer",
            )
        ],
    )
    wdir = tmp_path / "work_dir"
    wdir.mkdir(parents=True)
    with patch("buttercup.patcher.agents.context_retriever.grep", spec=StructuredTool) as mock_grep:

        class MockSchema(BaseModel):
            pass

        mock_grep.__name__ = "grep"
        mock_grep.name = "grep"
        mock_grep.get_input_schema.return_value = MockSchema
        mock_grep.get_output_schema.return_value = MockSchema
        mock_grep.return_direct = False

        res = ContextRetrieverAgent(
            input=patch_input,
            chain_call=lambda _, runnable, args, config, default: runnable.invoke(args, config=config),
            challenge=example_libpng_oss_fuzz_task,
        )
        res.mock_grep = mock_grep
        yield res


@pytest.fixture
def mock_patch_input(mock_challenge: ChallengeTask) -> Iterator[PatchInput]:
    """Create a mock PatchInput instance."""
    yield PatchInput(
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


@pytest.fixture
def mock_agent(
    mock_challenge: ChallengeTask, mock_patch_input: PatchInput, tmp_path: Path
) -> Iterator[ContextRetrieverAgent]:
    """Create a ContextRetrieverAgent instance."""
    wdir = tmp_path / "work_dir"
    wdir.mkdir(parents=True)
    with patch("subprocess.run", side_effect=mock_docker_run(mock_challenge)):

        def chain_call(_, runnable, args, config, default):
            return runnable.invoke(args, config=config)

        ctx_agent = ContextRetrieverAgent(
            input=mock_patch_input,
            chain_call=chain_call,
            challenge=mock_challenge,
        )
        ctx_agent._filter_code_snippets = lambda x, res, y: res
        yield ctx_agent


@pytest.fixture
def mock_tools() -> dict[str, MagicMock]:
    return {
        "get_callers": MagicMock(),
        "get_callees": MagicMock(),
    }


@pytest.fixture
def mock_agent_tools(
    mock_challenge: ChallengeTask, mock_patch_input: PatchInput, tmp_path: Path, mock_tools: dict[str, MagicMock]
) -> Iterator[ContextRetrieverAgent]:
    """Create a ContextRetrieverAgent instance."""

    @tool
    def get_callers(function_name: str, file_path: str) -> str:
        """Get the callers of a function."""
        mock_tools["get_callers"](function_name, file_path)

    @tool
    def get_callees(function_name: str, file_path: str) -> str:
        """Get the callees of a function."""
        mock_tools["get_callees"](function_name, file_path)

    wdir = tmp_path / "work_dir"
    wdir.mkdir(parents=True)
    with (
        patch("subprocess.run", side_effect=mock_docker_run(mock_challenge)),
        patch("buttercup.patcher.agents.context_retriever.get_callers", get_callers),
        patch("buttercup.patcher.agents.context_retriever.get_callees", get_callees),
    ):

        def chain_call(_, runnable, args, config, default):
            return runnable.invoke(args, config=config)

        ctx_agent = ContextRetrieverAgent(
            input=mock_patch_input,
            chain_call=chain_call,
            challenge=mock_challenge,
        )
        ctx_agent._filter_code_snippets = lambda x, res, y: res
        yield ctx_agent


@pytest.fixture
def mock_runnable_config(tmp_path: Path) -> dict:
    return {
        "configurable": {
            "thread_id": "test-thread-id",
            "work_dir": tmp_path / "work_dir",
            "tasks_storage": tmp_path / "tasks_storage",
            "max_concurrency": 1,
        },
    }


@pytest.mark.integration
def test_retrieve_context_basic(
    selinux_agent: ContextRetrieverAgent, mock_agent_llm: MagicMock, mock_runnable_config
) -> None:
    """Test basic context retrieval functionality."""
    # Create a test state with a simple request
    state = ContextRetrieverState(
        code_snippet_requests=[
            CodeSnippetRequest(
                request="Find function ebitmap_match_any",
            )
        ],
        prev_node="test_node",
    )

    # Execute the retrieve_context method
    mock_agent_llm.invoke.side_effect = [
        # First response: Agent decides to use grep to search for the function
        AIMessage(
            content="I'll search for the function using grep.",
            tool_calls=[
                ToolCall(
                    id="grep_call_1",
                    name="grep",
                    args={
                        "pattern": "ebitmap_match_any",
                    },
                )
            ],
        ),
        # Agent decides to get the function definition
        AIMessage(
            content="I found the function. Let me get its definition.",
            tool_calls=[
                ToolCall(
                    id="get_function_call_1",
                    name="get_function",
                    args={"function_name": "ebitmap_match_any", "file_path": "libsepol/src/ebitmap.c"},
                )
            ],
        ),
        AIMessage(
            content="Let's track the definition",
            tool_calls=[
                ToolCall(
                    id="track_snippet_call_1",
                    name="track_snippet",
                    args={
                        "file_path": "libsepol/src/ebitmap.c",
                        "start_line": None,
                        "end_line": None,
                        "type_name": None,
                        "function_name": "ebitmap_match_any",
                        "code_snippet_description": "ebitmap_match_any function definition",
                    },
                )
            ],
        ),
        AIMessage(
            content="I'm done <END>",
        ),
    ]
    result = selinux_agent.retrieve_context(state, mock_runnable_config)

    # Verify the result
    assert isinstance(result, Command)
    assert result.goto == "test_node"
    assert "relevant_code_snippets" in result.update
    assert len(result.update["relevant_code_snippets"]) == 1

    # Verify the code snippet content
    snippet = next(iter(result.update["relevant_code_snippets"]))
    assert "ebitmap_match_any" in snippet.code
    assert "const ebitmap_t *e1" in snippet.code


def test_missing_arg_tool_call(
    mock_agent: ContextRetrieverAgent, mock_agent_llm: MagicMock, mock_runnable_config
) -> None:
    """Test basic context retrieval functionality."""
    # Create a test state with a simple request
    state = ContextRetrieverState(
        code_snippet_requests=[
            CodeSnippetRequest(
                request="Find function main",
            )
        ],
        prev_node="test_node",
    )

    # Execute the retrieve_context method
    mock_agent_llm.invoke.side_effect = [
        AIMessage(
            content="I'll list the files in the project.",
            tool_calls=[
                ToolCall(
                    id="list_files_call_1",
                    name="ls",
                    args={},  # no args for list_files
                )
            ],
        ),
        AIMessage(
            content="Let me pass the path to ls",
            tool_calls=[
                ToolCall(
                    id="ls_call_1",
                    name="ls",
                    args={
                        "path": ".",
                    },
                )
            ],
        ),
        AIMessage(
            content="Let's get the definition",
            tool_calls=[
                ToolCall(
                    id="get_function_call_1",
                    name="get_function",
                    args={
                        "function_name": "main",
                        "file_path": "test.c",
                    },
                )
            ],
        ),
        AIMessage(
            content="Let's track the definition",
            tool_calls=[
                ToolCall(
                    id="track_snippet_call_1",
                    name="track_snippet",
                    args={
                        "file_path": "test.c",
                        "start_line": None,
                        "end_line": None,
                        "type_name": None,
                        "function_name": "main",
                        "code_snippet_description": "main function definition",
                    },
                )
            ],
        ),
        AIMessage(
            content="I'm done <END>",
        ),
    ]
    result = mock_agent.retrieve_context(state, mock_runnable_config)

    # Verify the result
    assert isinstance(result, Command)
    assert result.goto == "test_node"
    assert "relevant_code_snippets" in result.update
    assert len(result.update["relevant_code_snippets"]) == 1


def test_recursion_limit(mock_agent: ContextRetrieverAgent, mock_agent_llm: MagicMock, mock_runnable_config) -> None:
    """Test hitting the context request limit."""
    state = ContextRetrieverState(
        code_snippet_requests=[
            CodeSnippetRequest(
                request="Find function main",
            )
        ],
        prev_node="test_node",
    )

    mock_agent_llm.invoke.side_effect = [
        AIMessage(
            content="I'll list the files in the dir %s." % (i,),
            tool_calls=[
                ToolCall(
                    id="list_files_call_%s" % (i,),
                    name="ls",
                    args={
                        "path": str(i),
                    },
                )
            ],
        )
        for i in range(1, 1000)
    ]
    result = mock_agent.retrieve_context(state, mock_runnable_config)

    # Verify the result
    assert isinstance(result, Command)
    assert result.goto == "test_node"
    assert "relevant_code_snippets" in result.update
    assert len(result.update["relevant_code_snippets"]) == 0, (
        "Should not have any code snippets, we hit the recursion limit and never called the get_function/get_type tool"
    )


def test_recursion_limit_tmp_code_snippets(
    mock_agent: ContextRetrieverAgent, mock_agent_llm: MagicMock, mock_runnable_config
) -> None:
    """Test hitting the context request limit but getting some partial results."""
    state = ContextRetrieverState(
        code_snippet_requests=[
            CodeSnippetRequest(request="Find function main"),
        ],
        prev_node="test_node",
    )
    llm_invoke_side_effect = [
        AIMessage(
            content="I'll get the function definition.",
            tool_calls=[
                ToolCall(
                    id="get_function_call",
                    name="get_function",
                    args={
                        "function_name": "main",
                        "file_path": "test.c",
                    },
                )
            ],
        ),
        AIMessage(
            content="I'll track the function definition.",
            tool_calls=[
                ToolCall(
                    id="track_snippet_call",
                    name="track_snippet",
                    args={
                        "file_path": "test.c",
                        "start_line": None,
                        "end_line": None,
                        "type_name": None,
                        "function_name": "main",
                        "code_snippet_description": "main function definition",
                    },
                )
            ],
        ),
    ]
    llm_invoke_side_effect += [
        AIMessage(
            content="I'll list the files in the dir %s." % (i,),
            tool_calls=[
                ToolCall(
                    id="list_files_call_%s" % (i,),
                    name="ls",
                    args={
                        "path": str(i),
                    },
                )
            ],
        )
        for i in range(1, 1000)
    ]
    mock_agent_llm.invoke.side_effect = llm_invoke_side_effect
    result = mock_agent.retrieve_context(state, mock_runnable_config)

    assert isinstance(result, Command)
    assert result.goto == "test_node"
    assert "relevant_code_snippets" in result.update
    assert len(result.update["relevant_code_snippets"]) == 1
    code_snippet = next(iter(result.update["relevant_code_snippets"]))
    assert code_snippet.code == "int main() { int a = foo(); return a; }"


def test_dupped_code_snippets(
    mock_agent: ContextRetrieverAgent, mock_agent_llm: MagicMock, mock_runnable_config
) -> None:
    """Test that we don't return duplicate code snippets."""
    state = ContextRetrieverState(
        code_snippet_requests=[
            CodeSnippetRequest(request="Find function main"),
        ],
        prev_node="test_node",
    )
    mock_agent_llm.invoke.side_effect = [
        AIMessage(
            content="I'll get the function definition.",
            tool_calls=[
                ToolCall(
                    id="get_function_call",
                    name="get_function",
                    args={"function_name": "main", "file_path": "test.c"},
                )
            ],
        ),
        AIMessage(
            content="I'll track the function definition.",
            tool_calls=[
                ToolCall(
                    id="track_snippet_call",
                    name="track_snippet",
                    args={
                        "file_path": "test.c",
                        "start_line": None,
                        "end_line": None,
                        "type_name": None,
                        "function_name": "main",
                        "code_snippet_description": "main function definition",
                    },
                )
            ],
        ),
        AIMessage(
            content="I'm done <END>",
        ),
    ]
    result = mock_agent.retrieve_context(state, mock_runnable_config)
    assert isinstance(result, Command)
    assert result.goto == "test_node"
    assert "relevant_code_snippets" in result.update
    assert len(result.update["relevant_code_snippets"]) == 1
    code_snippet = next(iter(result.update["relevant_code_snippets"]))
    assert code_snippet.code == "int main() { int a = foo(); return a; }"

    mock_agent_llm.invoke.side_effect = [
        AIMessage(
            content="I'll get the function definition.",
            tool_calls=[
                ToolCall(
                    id="get_function_call",
                    name="get_function",
                    args={"function_name": "main", "file_path": "test.c"},
                )
            ],
        ),
        AIMessage(
            content="I'll track the function definition.",
            tool_calls=[
                ToolCall(
                    id="track_snippet_call",
                    name="track_snippet",
                    args={
                        "file_path": "test.c",
                        "start_line": None,
                        "end_line": None,
                        "type_name": None,
                        "function_name": "main",
                        "code_snippet_description": "main function definition",
                    },
                )
            ],
        ),
        AIMessage(
            content="I'll track the function definition.",
            tool_calls=[
                ToolCall(
                    id="track_snippet_call",
                    name="track_snippet",
                    args={
                        "file_path": "test.c",
                        "start_line": None,
                        "end_line": None,
                        "type_name": None,
                        "function_name": "main",
                        "code_snippet_description": "main function definition 2",
                    },
                )
            ],
        ),
        AIMessage(
            content="I'm done <END>",
        ),
    ]
    result = mock_agent.retrieve_context(state, mock_runnable_config)
    assert isinstance(result, Command)
    assert result.goto == "test_node"
    assert "relevant_code_snippets" in result.update
    assert len(result.update["relevant_code_snippets"]) == 1
    code_snippet = next(iter(result.update["relevant_code_snippets"]))
    assert code_snippet.code == "int main() { int a = foo(); return a; }"


def test_get_type(
    mock_agent: ContextRetrieverAgent, mock_cheap_llm: MagicMock, mock_agent_llm: MagicMock, mock_runnable_config
) -> None:
    """Test that we can get the type definition."""
    state = ContextRetrieverState(
        code_snippet_requests=[
            CodeSnippetRequest(request="Find type ebitmap_t"),
        ],
        prev_node="test_node",
    )
    mock_agent_llm.invoke.side_effect = [
        AIMessage(
            content="I'll get the type definition.",
            tool_calls=[
                ToolCall(
                    id="get_type_call",
                    name="get_type",
                    args={"type_name": "ebitmap_t", "file_path": "test.h"},
                )
            ],
        ),
        AIMessage(
            content="I'll get the type definition tracked.",
            tool_calls=[
                ToolCall(
                    id="track_snippet_call",
                    name="track_snippet",
                    args={
                        "file_path": "test.h",
                        "start_line": None,
                        "end_line": None,
                        "function_name": None,
                        "type_name": "ebitmap_t",
                        "code_snippet_description": "ebitmap_t type definition",
                    },
                )
            ],
        ),
        AIMessage(
            content="I'm done <END>",
        ),
    ]
    result = mock_agent.retrieve_context(state, mock_runnable_config)
    assert isinstance(result, Command)
    assert result.goto == "test_node"
    assert "relevant_code_snippets" in result.update
    assert len(result.update["relevant_code_snippets"]) == 1
    code_snippet = next(iter(result.update["relevant_code_snippets"]))
    assert code_snippet.code == "struct ebitmap_t { int a; }"


def test_get_definitions_no_paths(
    mock_agent: ContextRetrieverAgent, mock_agent_llm: MagicMock, mock_runnable_config
) -> None:
    """Test that we can get the type definition even if the file path is not provided."""
    state = ContextRetrieverState(
        code_snippet_requests=[
            CodeSnippetRequest(request="Find type ebitmap_t"),
        ],
        prev_node="test_node",
    )

    mock_agent_llm.invoke.side_effect = [
        AIMessage(
            content="I'll get the function definition.",
            tool_calls=[
                ToolCall(
                    id="get_function_call",
                    name="get_function",
                    args={"function_name": "main", "file_path": None},
                )
            ],
        ),
        AIMessage(
            content="I'll get the type definition.",
            tool_calls=[
                ToolCall(
                    id="get_type_call",
                    name="get_type",
                    args={"type_name": "ebitmap_t", "file_path": None},
                )
            ],
        ),
        AIMessage(
            content="I'll track the function definition.",
            tool_calls=[
                ToolCall(
                    id="track_snippet_call",
                    name="track_snippet",
                    args={
                        "file_path": "test.c",
                        "start_line": None,
                        "end_line": None,
                        "function_name": "main",
                        "type_name": None,
                        "code_snippet_description": "main function definition",
                    },
                )
            ],
        ),
        AIMessage(
            content="I'll track the type definition.",
            tool_calls=[
                ToolCall(
                    id="track_snippet_call",
                    name="track_snippet",
                    args={
                        "file_path": "test.h",
                        "start_line": None,
                        "end_line": None,
                        "function_name": None,
                        "type_name": "ebitmap_t",
                        "code_snippet_description": "ebitmap_t type definition",
                    },
                )
            ],
        ),
        AIMessage(
            content="I'm done <END>",
        ),
    ]
    result = mock_agent.retrieve_context(state, mock_runnable_config)
    assert isinstance(result, Command)
    assert result.goto == "test_node"
    assert "relevant_code_snippets" in result.update
    assert len(result.update["relevant_code_snippets"]) == 2
    code_snippets = result.update["relevant_code_snippets"]
    assert any(
        snippet.code == "int main() { int a = foo(); return a; }"
        and snippet.key.file_path == "/src/example_project/test.c"
        for snippet in code_snippets
    )
    assert any(
        snippet.code == "struct ebitmap_t { int a; }" and snippet.key.file_path == "/src/example_project/test.h"
        for snippet in code_snippets
    )


def test_get_callers(
    mock_agent_tools: ContextRetrieverAgent, mock_tools, mock_agent_llm: MagicMock, mock_runnable_config
) -> None:
    """Test that we can get the callers of a function."""
    state = ContextRetrieverState(
        code_snippet_requests=[
            CodeSnippetRequest(request="Find callers of foo"),
        ],
        prev_node="test_node",
    )
    mock_agent_llm.invoke.side_effect = [
        AIMessage(
            content="I'll get the callers of the function foo.",
            tool_calls=[
                ToolCall(
                    id="get_callers_call",
                    name="get_callers",
                    args={"function_name": "foo", "file_path": "test.c"},
                )
            ],
        ),
        AIMessage(
            content="I'm done <END>",
        ),
    ]
    result = mock_agent_tools.retrieve_context(state, mock_runnable_config)
    assert isinstance(result, Command)
    assert result.goto == "test_node"
    mock_tools["get_callers"].assert_called_once_with("foo", "test.c")


def test_get_callees(
    mock_agent_tools: ContextRetrieverAgent, mock_tools, mock_agent_llm: MagicMock, mock_runnable_config
) -> None:
    """Test that we can get the callees of a function."""
    state = ContextRetrieverState(
        code_snippet_requests=[
            CodeSnippetRequest(request="Find callees of main"),
        ],
        prev_node="test_node",
    )
    mock_agent_llm.invoke.side_effect = [
        AIMessage(
            content="I'll get the callees of the function main.",
            tool_calls=[
                ToolCall(
                    id="get_callees_call",
                    name="get_callees",
                    args={"function_name": "main", "file_path": "test.c"},
                )
            ],
        ),
        AIMessage(
            content="I'm done <END>",
        ),
    ]
    result = mock_agent_tools.retrieve_context(state, mock_runnable_config)
    assert isinstance(result, Command)
    assert result.goto == "test_node"
    mock_tools["get_callees"].assert_called_once_with("main", "test.c")


def test_low_recursion_limit_empty(
    mock_agent: ContextRetrieverAgent, mock_agent_llm: MagicMock, mock_runnable_config
) -> None:
    """Test that hitting a low recursion limit returns an empty set when no results were found."""
    state = ContextRetrieverState(
        code_snippet_requests=[
            CodeSnippetRequest(request="Find function main"),
        ],
        prev_node="test_node",
    )
    mock_agent_llm.invoke.side_effect = [
        AIMessage(
            content="I'll list the files in the dir %s." % (i,),
            tool_calls=[
                ToolCall(
                    id="list_files_call_%s" % (i,),
                    name="ls",
                    args={
                        "path": str(i),
                    },
                )
            ],
        )
        for i in range(1, 10)  # Small number to hit recursion limit quickly
    ]
    # Set a very low recursion limit
    mock_runnable_config["configurable"]["ctx_retriever_recursion_limit"] = 5
    result = mock_agent.retrieve_context(state, mock_runnable_config)

    assert isinstance(result, Command)
    assert result.goto == "test_node"
    assert "relevant_code_snippets" in result.update
    assert len(result.update["relevant_code_snippets"]) == 0, (
        "Should not have any code snippets, we hit the recursion limit and never called the get_function tool"
    )


def test_low_recursion_limit_with_results(
    mock_agent: ContextRetrieverAgent, mock_agent_llm: MagicMock, mock_runnable_config
) -> None:
    """Test that hitting a low recursion limit after getting some results still returns those results."""
    state = ContextRetrieverState(
        code_snippet_requests=[
            CodeSnippetRequest(request="Find function main"),
        ],
        prev_node="test_node",
    )
    llm_invoke_side_effect = [
        AIMessage(
            content="I'll get the function definition.",
            tool_calls=[
                ToolCall(
                    id="get_function_call",
                    name="get_function",
                    args={
                        "function_name": "main",
                        "file_path": "test.c",
                    },
                )
            ],
        ),
        AIMessage(
            content="I'll track the function definition.",
            tool_calls=[
                ToolCall(
                    id="track_snippet_call",
                    name="track_snippet",
                    args={
                        "file_path": "test.c",
                        "start_line": None,
                        "end_line": None,
                        "type_name": None,
                        "function_name": "main",
                        "code_snippet_description": "main function definition",
                    },
                )
            ],
        ),
        AIMessage(
            content="I'm done <END>",
        ),
    ]
    llm_invoke_side_effect += [
        AIMessage(
            content="I'll list the files in the dir %s." % (i,),
            tool_calls=[
                ToolCall(
                    id="list_files_call_%s" % (i,),
                    name="ls",
                    args={
                        "path": str(i),
                    },
                )
            ],
        )
        for i in range(1, 10)  # Small number to hit recursion limit quickly
    ]
    mock_agent_llm.invoke.side_effect = llm_invoke_side_effect
    # Set a very low recursion limit
    mock_runnable_config["configurable"]["ctx_retriever_recursion_limit"] = 5
    result = mock_agent.retrieve_context(state, mock_runnable_config)

    assert isinstance(result, Command)
    assert result.goto == "test_node"
    assert "relevant_code_snippets" in result.update
    assert len(result.update["relevant_code_snippets"]) == 1
    code_snippet = next(iter(result.update["relevant_code_snippets"]))
    assert code_snippet.code == "int main() { int a = foo(); return a; }"


def test_multiple_code_snippet_requests(
    mock_agent: ContextRetrieverAgent, mock_agent_llm: MagicMock, mock_runnable_config
) -> None:
    """Test handling multiple code snippet requests in a single state."""
    state = ContextRetrieverState(
        code_snippet_requests=[
            CodeSnippetRequest(request="Find function main"),
            CodeSnippetRequest(request="Find type ebitmap_t"),
        ],
        prev_node="test_node",
    )
    mock_agent_llm.invoke.side_effect = [
        # First request - get main function
        AIMessage(
            content="I'll get the function definition.",
            tool_calls=[
                ToolCall(
                    id="get_function_call_1",
                    name="get_function",
                    args={
                        "function_name": "main",
                        "file_path": "test.c",
                    },
                )
            ],
        ),
        AIMessage(
            content="I'll track the function definition.",
            tool_calls=[
                ToolCall(
                    id="track_snippet_call",
                    name="track_snippet",
                    args={
                        "file_path": "test.c",
                        "start_line": None,
                        "end_line": None,
                        "type_name": None,
                        "function_name": "main",
                        "code_snippet_description": "main function definition",
                    },
                )
            ],
        ),
        AIMessage(content="I'm done <END>"),
        # Second request - get ebitmap_t type
        AIMessage(
            content="I'll get the type definition.",
            tool_calls=[
                ToolCall(
                    id="get_type_call_1",
                    name="get_type",
                    args={
                        "type_name": "ebitmap_t",
                        "file_path": "test.h",
                    },
                )
            ],
        ),
        AIMessage(
            content="I'll track the type definition.",
            tool_calls=[
                ToolCall(
                    id="track_snippet_call",
                    name="track_snippet",
                    args={
                        "file_path": "test.h",
                        "start_line": None,
                        "end_line": None,
                        "function_name": None,
                        "type_name": "ebitmap_t",
                        "code_snippet_description": "ebitmap_t type definition",
                    },
                )
            ],
        ),
        AIMessage(content="I'm done <END>"),
    ]
    result = mock_agent.retrieve_context(state, mock_runnable_config)

    assert isinstance(result, Command)
    assert result.goto == "test_node"
    assert "relevant_code_snippets" in result.update
    assert len(result.update["relevant_code_snippets"]) == 2
    code_snippets = result.update["relevant_code_snippets"]
    assert any(
        snippet.code == "int main() { int a = foo(); return a; }"
        and snippet.key.file_path == "/src/example_project/test.c"
        for snippet in code_snippets
    )
    assert any(
        snippet.code == "struct ebitmap_t { int a; }" and snippet.key.file_path == "/src/example_project/test.h"
        for snippet in code_snippets
    )


def test_process_request_error_handling(
    mock_agent: ContextRetrieverAgent, mock_agent_llm: MagicMock, mock_runnable_config
) -> None:
    """Test error handling in process_request with different types of errors."""
    state = ContextRetrieverState(
        code_snippet_requests=[
            CodeSnippetRequest(request="Find function nonexistent"),
        ],
        prev_node="test_node",
    )
    # Simulate a ValueError from _get_function
    mock_agent_llm.invoke.side_effect = [
        AIMessage(
            content="I'll get the function definition.",
            tool_calls=[
                ToolCall(
                    id="get_function_call_1",
                    name="get_function",
                    args={
                        "function_name": "nonexistent",
                        "file_path": "test.c",
                    },
                )
            ],
        ),
    ]
    result = mock_agent.retrieve_context(state, mock_runnable_config)

    assert isinstance(result, Command)
    assert result.goto == "test_node"
    assert "relevant_code_snippets" in result.update
    assert len(result.update["relevant_code_snippets"]) == 0


def test_invalid_tool_call(mock_agent: ContextRetrieverAgent, mock_agent_llm: MagicMock, mock_runnable_config) -> None:
    """Test handling of invalid tool calls from the LLM."""
    state = ContextRetrieverState(
        code_snippet_requests=[
            CodeSnippetRequest(request="Find function main"),
        ],
        prev_node="test_node",
    )
    # LLM returns a tool call with missing required args
    mock_agent_llm.invoke.side_effect = [
        AIMessage(
            content="I'll get the function definition.",
            tool_calls=[
                ToolCall(
                    id="get_function_call_1",
                    name="get_function",
                    args={},  # Missing required args
                )
            ],
        ),
        AIMessage(content="I'm done <END>"),
    ]
    result = mock_agent.retrieve_context(state, mock_runnable_config)
    assert isinstance(result, Command)
    assert result.goto == "test_node"
    assert "relevant_code_snippets" in result.update
    assert len(result.update["relevant_code_snippets"]) == 0


def test_nonexistent_tool_call(
    mock_agent: ContextRetrieverAgent, mock_agent_llm: MagicMock, mock_runnable_config
) -> None:
    """Test handling of calls to non-existent tools."""
    state = ContextRetrieverState(
        code_snippet_requests=[
            CodeSnippetRequest(request="Find function main"),
        ],
        prev_node="test_node",
    )
    # LLM returns a call to a non-existent tool
    mock_agent_llm.invoke.side_effect = [
        AIMessage(
            content="I'll use a non-existent tool.",
            tool_calls=[
                ToolCall(
                    id="nonexistent_tool_call",
                    name="nonexistent_tool",
                    args={"arg1": "value1"},
                )
            ],
        ),
        AIMessage(content="I'm done <END>"),
    ]
    result = mock_agent.retrieve_context(state, mock_runnable_config)
    assert isinstance(result, Command)
    assert result.goto == "test_node"
    assert "relevant_code_snippets" in result.update
    assert len(result.update["relevant_code_snippets"]) == 0


def test_malformed_llm_response(
    mock_agent: ContextRetrieverAgent, mock_agent_llm: MagicMock, mock_runnable_config
) -> None:
    """Test handling of malformed LLM responses."""
    state = ContextRetrieverState(
        code_snippet_requests=[
            CodeSnippetRequest(request="Find function main"),
        ],
        prev_node="test_node",
    )
    # LLM returns a malformed response (no content, no tool calls)
    mock_agent_llm.invoke.side_effect = [
        AIMessage(content=""),  # Empty content
        AIMessage(content="I'm done <END>"),
    ]
    result = mock_agent.retrieve_context(state, mock_runnable_config)
    assert isinstance(result, Command)
    assert result.goto == "test_node"
    assert "relevant_code_snippets" in result.update
    assert len(result.update["relevant_code_snippets"]) == 0


def test_invalid_argument_types(
    mock_agent: ContextRetrieverAgent, mock_agent_llm: MagicMock, mock_runnable_config
) -> None:
    """Test handling of invalid argument types in tool calls."""
    state = ContextRetrieverState(
        code_snippet_requests=[
            CodeSnippetRequest(request="Find function main"),
        ],
        prev_node="test_node",
    )
    # LLM returns a tool call with invalid argument types
    mock_agent_llm.invoke.side_effect = [
        AIMessage(
            content="I'll get the function definition.",
            tool_calls=[
                ToolCall(
                    id="get_function_call_1",
                    name="get_function",
                    args={
                        "function_name": 123,  # Should be string
                        "file_path": ["test.c"],  # Should be string
                    },
                )
            ],
        ),
        AIMessage(content="I'm done <END>"),
    ]
    result = mock_agent.retrieve_context(state, mock_runnable_config)
    assert isinstance(result, Command)
    assert result.goto == "test_node"
    assert "relevant_code_snippets" in result.update
    assert len(result.update["relevant_code_snippets"]) == 0


def test_llm_error_recovery(mock_agent: ContextRetrieverAgent, mock_agent_llm: MagicMock, mock_runnable_config) -> None:
    """Test that the agent recovers from LLM errors and continues processing."""
    state = ContextRetrieverState(
        code_snippet_requests=[
            CodeSnippetRequest(request="Find function main"),
            CodeSnippetRequest(request="Find type ebitmap_t"),
        ],
        prev_node="test_node",
    )
    # First request fails, second succeeds
    mock_agent_llm.invoke.side_effect = [
        # First request - fails with invalid tool call
        AIMessage(
            content="I'll get the function definition.",
            tool_calls=[
                ToolCall(
                    id="get_function_call_1",
                    name="get_function",
                    args={},  # Missing required args
                )
            ],
        ),
        AIMessage(
            content="I'll track the function definition.",
            tool_calls=[
                ToolCall(
                    id="track_snippet_call",
                    name="track_snippet",
                    args={
                        "file_path": "test.c",
                        # Missing required args
                    },
                )
            ],
        ),
        AIMessage(content="I'm done <END>"),
        # Second request - succeeds
        AIMessage(
            content="I'll get the type definition.",
            tool_calls=[
                ToolCall(
                    id="get_type_call_1",
                    name="get_type",
                    args={
                        "type_name": "ebitmap_t",
                        "file_path": "test.h",
                    },
                )
            ],
        ),
        AIMessage(
            content="I'll track the type definition.",
            tool_calls=[
                ToolCall(
                    id="track_snippet_call",
                    name="track_snippet",
                    args={
                        "file_path": "test.h",
                        "start_line": None,
                        "end_line": None,
                        "function_name": None,
                        "type_name": "ebitmap_t",
                        "code_snippet_description": "ebitmap_t type definition",
                    },
                )
            ],
        ),
        AIMessage(content="I'm done <END>"),
    ]
    result = mock_agent.retrieve_context(state, mock_runnable_config)
    assert isinstance(result, Command)
    assert result.goto == "test_node"
    assert "relevant_code_snippets" in result.update
    # Should have one result from the successful request
    assert len(result.update["relevant_code_snippets"]) == 1
    code_snippet = next(iter(result.update["relevant_code_snippets"]))
    assert code_snippet.code == "struct ebitmap_t { int a; }"


@patch("buttercup.patcher.agents.context_retriever.get_challenge")
def test_get_initial_context_filters_llvm_frames(
    mock_get_challenge: MagicMock,
    mock_agent: ContextRetrieverAgent,
    mock_agent_llm: MagicMock,
    mock_runnable_config: dict,
) -> None:
    """Test that get_initial_context filters out llvm-project frames for non-llvm projects."""
    # Create a test state with a stacktrace containing llvm frames
    state = PatcherAgentState(
        context=PatchInput(
            challenge_task_dir=Path("/test/dir"),
            task_id="test-task",
            internal_patch_id="1",
            povs=[
                PatchInputPoV(
                    challenge_task_dir=Path("/test/dir"),
                    sanitizer="address",
                    pov=Path("test.pov"),
                    pov_token="test-token",
                    sanitizer_output="""==1==ERROR: AddressSanitizer: heap-buffer-overflow
 #0 0x123456 in test_func /src/test/file.c:10
 #1 0x234567 in llvm_func /src/llvm-project/compiler-rt/test.c:20
 #2 0x345678 in another_func /src/test/another.c:30""",
                    engine="libfuzzer",
                    harness_name="test-harness",
                )
            ],
        ),
        relevant_code_snippets=set(),
        execution_info={},
    )

    # Mock the challenge task to be a non-llvm project
    mock_get_challenge.return_value = MagicMock(project_name="test-project")

    mock_agent.process_request = MagicMock(
        side_effect=[
            [
                ContextCodeSnippet(
                    code="int test_func() { return 0; }",
                    key=CodeSnippetKey(file_path="/src/test/file.c", function_name="test_func"),
                    start_line=10,
                    end_line=10,
                )
            ],
            [
                ContextCodeSnippet(
                    code="int another_func() { return 0; }",
                    key=CodeSnippetKey(file_path="/src/test/another.c", function_name="another_func"),
                    start_line=30,
                    end_line=30,
                )
            ],
        ]
    )
    result = mock_agent.get_initial_context(state, mock_runnable_config)

    # Verify that only non-llvm frames were processed
    assert isinstance(result, Command)
    assert "relevant_code_snippets" in result.update
    # Should have 2 code snippets (test_func and another_func, but not llvm_func)
    assert len(result.update["relevant_code_snippets"]) == 2
    code_snippets = result.update["relevant_code_snippets"]
    assert any(
        snippet.code == "int test_func() { return 0; }" and snippet.key.file_path == "/src/test/file.c"
        for snippet in code_snippets
    )
    assert any(
        snippet.code == "int another_func() { return 0; }" and snippet.key.file_path == "/src/test/another.c"
        for snippet in code_snippets
    )


@patch("buttercup.patcher.agents.context_retriever.get_challenge")
def test_get_initial_context_includes_llvm_frames(
    mock_get_challenge: MagicMock,
    mock_agent: ContextRetrieverAgent,
    mock_agent_llm: MagicMock,
    mock_runnable_config: dict,
) -> None:
    """Test that get_initial_context includes llvm-project frames for llvm-project challenge."""
    # Create a test state with a stacktrace containing llvm frames
    state = PatcherAgentState(
        context=PatchInput(
            challenge_task_dir=Path("/test/dir"),
            task_id="test-task",
            internal_patch_id="1",
            povs=[
                PatchInputPoV(
                    challenge_task_dir=Path("/test/dir"),
                    sanitizer="address",
                    pov=Path("test.pov"),
                    pov_token="test-token",
                    sanitizer_output="""==1==ERROR: AddressSanitizer: heap-buffer-overflow
 #0 0x123456 in test_func /src/llvm-project/file.c:10
 #1 0x234567 in llvm_func /src/llvm-project/compiler-rt/test.c:20
 #2 0x345678 in another_func /src/llvm-project/another.c:30""",
                    engine="libfuzzer",
                    harness_name="test-harness",
                )
            ],
        ),
        relevant_code_snippets=set(),
        execution_info={},
    )

    # Mock the challenge task to be llvm-project
    mock_agent.challenge.task_meta.project_name = "llvm-project"
    mock_get_challenge.return_value = MagicMock(project_name="llvm-project")

    mock_agent.process_request = MagicMock(
        side_effect=[
            [
                ContextCodeSnippet(
                    code="int test_func() { return 0; }",
                    key=CodeSnippetKey(file_path="/src/test/file.c", function_name="test_func"),
                    start_line=10,
                    end_line=10,
                )
            ],
            [
                ContextCodeSnippet(
                    code="int llvm_func() { return 0; }",
                    key=CodeSnippetKey(file_path="/src/llvm-project/compiler-rt/test.c", function_name="llvm_func"),
                    start_line=20,
                    end_line=20,
                )
            ],
            [
                ContextCodeSnippet(
                    code="int another_func() { return 0; }",
                    key=CodeSnippetKey(file_path="/src/test/another.c", function_name="another_func"),
                    start_line=30,
                    end_line=30,
                )
            ],
        ]
    )

    result = mock_agent.get_initial_context(state, mock_runnable_config)

    # Verify that all frames were processed
    assert isinstance(result, Command)
    assert "relevant_code_snippets" in result.update
    # Should have all 3 code snippets
    assert len(result.update["relevant_code_snippets"]) == 3
    code_snippets = result.update["relevant_code_snippets"]
    assert any(
        snippet.code == "int test_func() { return 0; }" and snippet.key.file_path == "/src/test/file.c"
        for snippet in code_snippets
    )
    assert any(
        snippet.code == "int llvm_func() { return 0; }"
        and snippet.key.file_path == "/src/llvm-project/compiler-rt/test.c"
        for snippet in code_snippets
    )
    assert any(
        snippet.code == "int another_func() { return 0; }" and snippet.key.file_path == "/src/test/another.c"
        for snippet in code_snippets
    )


@patch("buttercup.patcher.agents.context_retriever.get_challenge")
def test_get_initial_context_respects_n_initial_stackframes(
    mock_get_challenge: MagicMock,
    mock_agent: ContextRetrieverAgent,
    mock_agent_llm: MagicMock,
    mock_runnable_config: dict,
) -> None:
    """Test that get_initial_context respects the n_initial_stackframes configuration."""
    # Create a test state with a stacktrace containing multiple frames
    state = PatcherAgentState(
        context=PatchInput(
            challenge_task_dir=Path("/test/dir"),
            task_id="test-task",
            internal_patch_id="1",
            povs=[
                PatchInputPoV(
                    challenge_task_dir=Path("/test/dir"),
                    sanitizer="address",
                    pov=Path("test.pov"),
                    pov_token="test-token",
                    sanitizer_output="""==1==ERROR: AddressSanitizer: heap-buffer-overflow
 #0 0x123456 in test_func1 /src/test/file1.c:10
 #1 0x234567 in test_func2 /src/test/file2.c:20
 #2 0x345678 in test_func3 /src/test/file3.c:30
 #3 0x456789 in test_func4 /src/test/file4.c:40""",
                    engine="libfuzzer",
                    harness_name="test-harness",
                )
            ],
        ),
        relevant_code_snippets=set(),
        execution_info={},
    )

    # Mock the challenge task
    mock_get_challenge.return_value = MagicMock(project_name="test-project")

    # Set n_initial_stackframes to 2 in the configuration
    mock_runnable_config["configurable"]["n_initial_stackframes"] = 2

    # Mock process_request to return code snippets for each function
    mock_agent.process_request = MagicMock(
        side_effect=[
            [
                ContextCodeSnippet(
                    code="int test_func1() { return 0; }",
                    key=CodeSnippetKey(file_path="/src/test/file1.c", function_name="test_func1"),
                    start_line=10,
                    end_line=10,
                )
            ],
            [
                ContextCodeSnippet(
                    code="int test_func2() { return 0; }",
                    key=CodeSnippetKey(file_path="/src/test/file2.c", function_name="test_func2"),
                    start_line=20,
                    end_line=20,
                )
            ],
            [
                ContextCodeSnippet(
                    code="int test_func3() { return 0; }",
                    key=CodeSnippetKey(file_path="/src/test/file3.c", function_name="test_func3"),
                    start_line=30,
                    end_line=30,
                )
            ],
            [
                ContextCodeSnippet(
                    code="int test_func4() { return 0; }",
                    key=CodeSnippetKey(file_path="/src/test/file4.c", function_name="test_func4"),
                    start_line=40,
                    end_line=40,
                )
            ],
        ]
    )

    result = mock_agent.get_initial_context(state, mock_runnable_config)

    # Verify that only the first 2 frames were processed
    assert isinstance(result, Command)
    assert "relevant_code_snippets" in result.update
    assert len(result.update["relevant_code_snippets"]) == 2

    # Verify the specific code snippets that were included
    code_snippets = result.update["relevant_code_snippets"]
    assert any(
        snippet.code == "int test_func1() { return 0; }" and snippet.key.file_path == "/src/test/file1.c"
        for snippet in code_snippets
    )
    assert any(
        snippet.code == "int test_func2() { return 0; }" and snippet.key.file_path == "/src/test/file2.c"
        for snippet in code_snippets
    )

    # Verify that process_request was called exactly twice
    assert mock_agent.process_request.call_count == 2


@patch("buttercup.patcher.agents.context_retriever.get_challenge")
def test_get_initial_context_handles_multiple_stackframes(
    mock_get_challenge: MagicMock,
    mock_agent: ContextRetrieverAgent,
    mock_agent_llm: MagicMock,
    mock_runnable_config: dict,
) -> None:
    """Test that get_initial_context correctly handles multiple stackframes in the same POV output."""
    # Create a test state with a stacktrace containing multiple stackframes
    # simulating a use-after-free scenario with allocation and crash frames
    state = PatcherAgentState(
        context=PatchInput(
            challenge_task_dir=Path("/test/dir"),
            task_id="test-task",
            internal_patch_id="1",
            povs=[
                PatchInputPoV(
                    challenge_task_dir=Path("/test/dir"),
                    sanitizer="address",
                    pov=Path("test.pov"),
                    pov_token="test-token",
                    sanitizer_output="""==1==ERROR: AddressSanitizer: heap-use-after-free
 #0 0x123456 in crash_func /src/test/crash.c:10
 #1 0x234567 in use_after_free /src/llvm-project/compiler-rt/uaf.c:20
 #2 0x345678 in free_memory /src/llvm-project/compiler-rt/memory.c:30
 
 ==2==ERROR: AddressSanitizer: heap-use-after-free
 #0 0x456789 in allocate_memory /src/test/memory.c:40
 #1 0x567890 in init_data /src/test/init.c:50
 #2 0x678901 in setup_test /src/test/setup.c:60
 #3 0x789012 in main /src/test/main.c:70
 #4 0x890123 in __libc_start_main /src/glibc/libc-start.c:308""",
                    engine="libfuzzer",
                    harness_name="test-harness",
                )
            ],
        ),
        relevant_code_snippets=set(),
        execution_info={},
    )

    # Mock the challenge task
    mock_get_challenge.return_value = MagicMock(project_name="test-project")

    # Set n_initial_stackframes to 2 in the configuration
    mock_runnable_config["configurable"]["n_initial_stackframes"] = 4

    # Mock process_request to return code snippets for each function
    mock_agent.process_request = MagicMock(
        side_effect=[
            # First stackframe (crash)
            [
                ContextCodeSnippet(
                    code="void crash_func() { /* crash */ }",
                    key=CodeSnippetKey(file_path="/src/test/crash.c", function_name="crash_func"),
                    start_line=10,
                    end_line=10,
                )
            ],
            # Second stackframe (allocation)
            [
                ContextCodeSnippet(
                    code="void* allocate_memory() { /* allocate */ }",
                    key=CodeSnippetKey(file_path="/src/test/memory.c", function_name="allocate_memory"),
                    start_line=40,
                    end_line=40,
                )
            ],
            [
                ContextCodeSnippet(
                    code="void init_data() { /* init */ }",
                    key=CodeSnippetKey(file_path="/src/test/init.c", function_name="init_data"),
                    start_line=50,
                    end_line=50,
                )
            ],
            [
                ContextCodeSnippet(
                    code="void setup_test() { /* setup */ }",
                    key=CodeSnippetKey(file_path="/src/test/setup.c", function_name="setup_test"),
                    start_line=60,
                    end_line=60,
                )
            ],
            [
                ContextCodeSnippet(
                    code="void main() { /* main */ }",
                    key=CodeSnippetKey(file_path="/src/test/main.c", function_name="main"),
                    start_line=70,
                    end_line=70,
                )
            ],
            [
                ContextCodeSnippet(
                    code="void __libc_start_main() { /* start main */ }",
                    key=CodeSnippetKey(file_path="/src/glibc/libc-start.c", function_name="__libc_start_main"),
                    start_line=308,
                    end_line=308,
                )
            ],
        ]
    )

    result = mock_agent.get_initial_context(state, mock_runnable_config)

    # Verify that we got code snippets from both stackframes
    assert isinstance(result, Command)
    assert "relevant_code_snippets" in result.update
    assert len(result.update["relevant_code_snippets"]) == 5, "1 from first stackframe, 4 from second stackframe"

    # Verify the specific code snippets that were included
    code_snippets = result.update["relevant_code_snippets"]
    assert any(
        snippet.code == "void crash_func() { /* crash */ }" and snippet.key.file_path == "/src/test/crash.c"
        for snippet in code_snippets
    )
    assert any(
        snippet.code == "void* allocate_memory() { /* allocate */ }" and snippet.key.file_path == "/src/test/memory.c"
        for snippet in code_snippets
    )
    assert any(
        snippet.code == "void init_data() { /* init */ }" and snippet.key.file_path == "/src/test/init.c"
        for snippet in code_snippets
    )
    assert any(
        snippet.code == "void setup_test() { /* setup */ }" and snippet.key.file_path == "/src/test/setup.c"
        for snippet in code_snippets
    )
    # Verify that process_request was called exactly 5 times (1 from first stackframe, 4 from second stackframe)
    assert mock_agent.process_request.call_count == 5


@patch("buttercup.patcher.agents.context_retriever.get_challenge")
def test_get_initial_context_multiple_povs(
    mock_get_challenge: MagicMock,
    mock_agent: ContextRetrieverAgent,
    mock_agent_llm: MagicMock,
    mock_runnable_config: dict,
) -> None:
    """Test that get_initial_context correctly handles multiple POVs in the PatchInput."""
    # Create a test state with multiple POVs, each with their own stacktrace
    state = PatcherAgentState(
        context=PatchInput(
            challenge_task_dir=Path("/test/dir"),
            task_id="test-task",
            internal_patch_id="1",
            povs=[
                # First POV - heap buffer overflow
                PatchInputPoV(
                    challenge_task_dir=Path("/test/dir"),
                    sanitizer="address",
                    pov=Path("test1.pov"),
                    pov_token="test-token-1",
                    sanitizer_output="""==1==ERROR: AddressSanitizer: heap-buffer-overflow
 #0 0x123456 in overflow_func /src/test/overflow.c:10
 #1 0x234567 in process_data /src/test/process.c:20
 #2 0x345678 in handle_input /src/test/input.c:30""",
                    engine="libfuzzer",
                    harness_name="test-harness-1",
                ),
                # Second POV - use after free
                PatchInputPoV(
                    challenge_task_dir=Path("/test/dir"),
                    sanitizer="address",
                    pov=Path("test2.pov"),
                    pov_token="test-token-2",
                    sanitizer_output="""==1==ERROR: AddressSanitizer: heap-use-after-free
 #0 0x456789 in uaf_func /src/test/uaf.c:40
 #1 0x567890 in free_memory /src/test/memory.c:50
 #2 0x678901 in cleanup /src/test/cleanup.c:60""",
                    engine="libfuzzer",
                    harness_name="test-harness-2",
                ),
            ],
        ),
        relevant_code_snippets=set(),
        execution_info={},
    )

    # Mock the challenge task
    mock_get_challenge.return_value = MagicMock(project_name="test-project")

    # Set n_initial_stackframes to 2 in the configuration
    mock_runnable_config["configurable"]["n_initial_stackframes"] = 2

    # Mock process_request to return code snippets for each function
    mock_agent.process_request = MagicMock(
        side_effect=[
            # First POV stackframes
            [
                ContextCodeSnippet(
                    code="void overflow_func() { /* overflow */ }",
                    key=CodeSnippetKey(file_path="/src/test/overflow.c", function_name="overflow_func"),
                    start_line=10,
                    end_line=10,
                )
            ],
            [
                ContextCodeSnippet(
                    code="void process_data() { /* process */ }",
                    key=CodeSnippetKey(file_path="/src/test/process.c", function_name="process_data"),
                    start_line=20,
                    end_line=20,
                )
            ],
            # Second POV stackframes
            [
                ContextCodeSnippet(
                    code="void uaf_func() { /* uaf */ }",
                    key=CodeSnippetKey(file_path="/src/test/uaf.c", function_name="uaf_func"),
                    start_line=40,
                    end_line=40,
                )
            ],
            [
                ContextCodeSnippet(
                    code="void free_memory() { /* free */ }",
                    key=CodeSnippetKey(file_path="/src/test/memory.c", function_name="free_memory"),
                    start_line=50,
                    end_line=50,
                )
            ],
        ]
    )

    result = mock_agent.get_initial_context(state, mock_runnable_config)

    # Verify that we got code snippets from both POVs
    assert isinstance(result, Command)
    assert "relevant_code_snippets" in result.update
    assert len(result.update["relevant_code_snippets"]) == 4, "2 from first POV, 2 from second POV"

    # Verify the specific code snippets that were included
    code_snippets = result.update["relevant_code_snippets"]
    assert any(
        snippet.code == "void overflow_func() { /* overflow */ }" and snippet.key.file_path == "/src/test/overflow.c"
        for snippet in code_snippets
    )
    assert any(
        snippet.code == "void process_data() { /* process */ }" and snippet.key.file_path == "/src/test/process.c"
        for snippet in code_snippets
    )
    assert any(
        snippet.code == "void uaf_func() { /* uaf */ }" and snippet.key.file_path == "/src/test/uaf.c"
        for snippet in code_snippets
    )
    assert any(
        snippet.code == "void free_memory() { /* free */ }" and snippet.key.file_path == "/src/test/memory.c"
        for snippet in code_snippets
    )

    # Verify that process_request was called exactly 4 times (2 from each POV)
    assert mock_agent.process_request.call_count == 4


@patch("buttercup.patcher.agents.context_retriever.get_challenge")
def test_get_initial_context_multiple_povs_deduplication(
    mock_get_challenge: MagicMock,
    mock_agent: ContextRetrieverAgent,
    mock_agent_llm: MagicMock,
    mock_runnable_config: dict,
) -> None:
    """Test that get_initial_context deduplicates code snippet requests when the same functions appear in multiple POVs."""
    # Create a test state with multiple POVs that share some functions in their stacktraces
    state = PatcherAgentState(
        context=PatchInput(
            challenge_task_dir=Path("/test/dir"),
            task_id="test-task",
            internal_patch_id="1",
            povs=[
                # First POV - heap buffer overflow
                PatchInputPoV(
                    challenge_task_dir=Path("/test/dir"),
                    sanitizer="address",
                    pov=Path("test1.pov"),
                    pov_token="test-token-1",
                    sanitizer_output="""==1==ERROR: AddressSanitizer: heap-buffer-overflow
 #0 0x123456 in crash_func /src/test/crash.c:10
 #1 0x234567 in process_data /src/test/process.c:20
 #2 0x345678 in handle_input /src/test/input.c:30""",
                    engine="libfuzzer",
                    harness_name="test-harness-1",
                ),
                # Second POV - use after free, shares some functions with first POV
                PatchInputPoV(
                    challenge_task_dir=Path("/test/dir"),
                    sanitizer="address",
                    pov=Path("test2.pov"),
                    pov_token="test-token-2",
                    sanitizer_output="""==1==ERROR: AddressSanitizer: heap-use-after-free
 #0 0x456789 in crash_func /src/test/crash.c:10
 #1 0x567890 in process_data /src/test/process.c:20
 #2 0x678901 in cleanup /src/test/cleanup.c:60""",
                    engine="libfuzzer",
                    harness_name="test-harness-2",
                ),
            ],
        ),
        relevant_code_snippets=set(),
        execution_info={},
    )

    # Mock the challenge task
    mock_get_challenge.return_value = MagicMock(project_name="test-project")

    # Set n_initial_stackframes to 3 in the configuration
    mock_runnable_config["configurable"]["n_initial_stackframes"] = 3

    # Mock process_request to return code snippets for each function
    # Note: We expect only 3 calls total, not 4, because crash_func and process_data appear in both POVs
    mock_agent.process_request = MagicMock(
        side_effect=[
            # First unique function from first POV
            [
                ContextCodeSnippet(
                    code="void crash_func() { /* crash */ }",
                    key=CodeSnippetKey(file_path="/src/test/crash.c", function_name="crash_func"),
                    start_line=10,
                    end_line=10,
                )
            ],
            # Second unique function from first POV
            [
                ContextCodeSnippet(
                    code="void process_data() { /* process */ }",
                    key=CodeSnippetKey(file_path="/src/test/process.c", function_name="process_data"),
                    start_line=20,
                    end_line=20,
                )
            ],
            # Third unique function from first POV
            [
                ContextCodeSnippet(
                    code="void handle_input() { /* handle input */ }",
                    key=CodeSnippetKey(file_path="/src/test/input.c", function_name="handle_input"),
                    start_line=60,
                    end_line=60,
                )
            ],
            # Unique function from second POV
            [
                ContextCodeSnippet(
                    code="void cleanup() { /* cleanup */ }",
                    key=CodeSnippetKey(file_path="/src/test/cleanup.c", function_name="cleanup"),
                    start_line=60,
                    end_line=60,
                )
            ],
        ]
    )

    result = mock_agent.get_initial_context(state, mock_runnable_config)

    # Verify that we got code snippets from both POVs, but without duplicates
    assert isinstance(result, Command)
    assert "relevant_code_snippets" in result.update
    assert len(result.update["relevant_code_snippets"]) == 4, "4 unique functions across both POVs"

    # Verify the specific code snippets that were included
    code_snippets = result.update["relevant_code_snippets"]
    assert any(
        snippet.code == "void crash_func() { /* crash */ }" and snippet.key.file_path == "/src/test/crash.c"
        for snippet in code_snippets
    )
    assert any(
        snippet.code == "void process_data() { /* process */ }" and snippet.key.file_path == "/src/test/process.c"
        for snippet in code_snippets
    )
    assert any(
        snippet.code == "void cleanup() { /* cleanup */ }" and snippet.key.file_path == "/src/test/cleanup.c"
        for snippet in code_snippets
    )

    # Verify that process_request was called exactly 3 times (once for each unique function)
    assert mock_agent.process_request.call_count == 4

    # Verify that process_request was called with the correct function names and file paths
    calls = mock_agent.process_request.call_args_list
    assert any(
        call.args[2].request.startswith("Implementation of `crash_func` in `/src/test/crash.c`") for call in calls
    )
    assert any(
        call.args[2].request.startswith("Implementation of `process_data` in `/src/test/process.c`") for call in calls
    )
    assert any(
        call.args[2].request.startswith("Implementation of `cleanup` in `/src/test/cleanup.c`") for call in calls
    )
    assert any(
        call.args[2].request.startswith("Implementation of `handle_input` in `/src/test/input.c`") for call in calls
    )


def test_find_tests_agent_success(
    mock_agent: ContextRetrieverAgent, mock_runnable_config: dict, mock_challenge: ChallengeTask
) -> None:
    """Test that the find tests agent successfully discovers and validates test instructions."""
    state = PatcherAgentState(
        context=PatchInput(
            challenge_task_dir=Path("/test/dir"),
            task_id="test-task",
            internal_patch_id="1",
            povs=[
                PatchInputPoV(
                    challenge_task_dir=Path("/test/dir"),
                    sanitizer="address",
                    pov=Path("test.pov"),
                    pov_token="test-token",
                    sanitizer_output="test output",
                    engine="libfuzzer",
                    harness_name="test-harness",
                )
            ],
        ),
        relevant_code_snippets=set(),
        execution_info={},
    )

    # Create a mock for find_tests_agent
    mock_find_tests_agent = MagicMock()
    mock_find_tests_agent.invoke.return_value = AIMessage(
        content="I found test instructions in the README.",
        tool_calls=[
            ToolCall(
                id="test_instructions_call_1",
                name="test_instructions",
                args={
                    "instructions": [
                        "cd /src",
                        "make test",
                    ],
                },
            )
        ],
    )
    # Mock the state with all required fields
    mock_find_tests_agent.get_state.return_value.values = {
        "tests_instructions": "#!/bin/bash\ncd /src\nmake test\n",
        "messages": [],  # Required field
        "challenge_task_dir": Path("/test/dir"),  # Required field
        "work_dir": mock_runnable_config["configurable"]["work_dir"],  # Required field
    }
    mock_agent.find_tests_agent = mock_find_tests_agent

    # Mock the docker command execution for test_instructions
    with (
        patch("buttercup.common.challenge_task.ChallengeTask.exec_docker_cmd") as mock_exec,
        patch("buttercup.common.challenge_task.ChallengeTask.get_clean_task") as mock_clean_task,
    ):

        @contextmanager
        def yield_challenge(*args, **kwargs):
            yield mock_challenge

        mock_clean_task.return_value = mock_challenge
        mock_challenge.apply_patch_diff = MagicMock(return_value=True)
        mock_challenge.get_rw_copy = MagicMock(side_effect=yield_challenge)
        mock_exec.return_value = CommandResult(
            success=True,
            returncode=0,
            output=b"Tests passed",
            error=b"",
        )

        result = mock_agent.find_tests_node(state, mock_runnable_config)

        # Verify the agent found and validated test instructions
        assert result.update["tests_instructions"] == "#!/bin/bash\ncd /src\nmake test\n"
        assert result.goto == PatcherAgentName.ROOT_CAUSE_ANALYSIS.value


def test_find_tests_agent_uses_existing_test_sh(mock_agent: ContextRetrieverAgent, mock_runnable_config: dict) -> None:
    """Test that the find tests agent uses an existing test.sh script if available."""
    state = PatcherAgentState(
        context=PatchInput(
            challenge_task_dir=Path("/test/dir"),
            task_id="test-task",
            internal_patch_id="1",
            povs=[
                PatchInputPoV(
                    challenge_task_dir=Path("/test/dir"),
                    sanitizer="address",
                    pov=Path("test.pov"),
                    pov_token="test-token",
                    sanitizer_output="test output",
                    engine="libfuzzer",
                    harness_name="test-harness",
                )
            ],
        ),
        relevant_code_snippets=set(),
        execution_info={},
    )

    # Create a mock test.sh file in the oss-fuzz project directory
    test_sh_content = "#!/bin/bash\ncd /src\n./run_tests.sh\n"
    with patch("pathlib.Path.exists", return_value=True), patch("pathlib.Path.read_text", return_value=test_sh_content):
        result = mock_agent.find_tests_node(state, mock_runnable_config)

        # Verify that the agent used the existing test.sh script
        assert result.update["tests_instructions"] == test_sh_content
        assert result.goto == PatcherAgentName.ROOT_CAUSE_ANALYSIS.value


@pytest.mark.integration
def test_grep_libpng(libpng_agent: ContextRetrieverAgent, mock_agent_llm: MagicMock, mock_runnable_config) -> None:
    """Test the grep command on Makefile in libpng."""
    state = ContextRetrieverState(
        code_snippet_requests=[
            CodeSnippetRequest(
                request="Grep 'check' in Makefile",
            )
        ],
        prev_node="test_node",
    )

    # Execute the retrieve_context method
    mock_agent_llm.invoke.side_effect = [
        # First response: Agent decides to use grep to search for the function
        AIMessage(
            content="I'll search for the string 'check' in Makefile using grep.",
            tool_calls=[
                ToolCall(
                    id="grep_call_1",
                    name="grep",
                    args={
                        "pattern": "check",
                        "file_path": "Makefile",
                    },
                )
            ],
        ),
        AIMessage(
            content="I'm done <END>",
        ),
    ]
    result = libpng_agent.retrieve_context(state, mock_runnable_config)

    # Verify the result
    assert isinstance(result, Command)
    assert result.goto == "test_node"

    # Verify that grep was called with the correct arguments
    libpng_agent.mock_grep.invoke.assert_called_once()
    call_args = libpng_agent.mock_grep.invoke.call_args[0][0]  # Get the first positional argument
    assert call_args["name"] == "grep"
    assert call_args["args"] == {"pattern": "check", "file_path": "Makefile"}


def test_find_tests_parallel(
    mock_agent: ContextRetrieverAgent,
    mock_agent_llm: MagicMock,
    mock_runnable_config: dict,
    mock_challenge: ChallengeTask,
) -> None:
    """Test that the find tests agent can run multiple test_instructions tool calls in parallel."""
    state = PatcherAgentState(
        context=PatchInput(
            challenge_task_dir=Path("/test/dir"),
            task_id="test-task",
            internal_patch_id="1",
            povs=[
                PatchInputPoV(
                    challenge_task_dir=Path("/test/dir"),
                    sanitizer="address",
                    pov=Path("test.pov"),
                    pov_token="test-token",
                    sanitizer_output="test output",
                    engine="libfuzzer",
                    harness_name="test-harness",
                )
            ],
        ),
        relevant_code_snippets=set(),
        execution_info={},
    )

    # Create a mock for find_tests_agent
    mock_agent_llm.invoke.return_value = AIMessage(
        content="I found test instructions in the README.",
        tool_calls=[
            ToolCall(
                id="test_instructions_call_1",
                name="test_instructions",
                args={
                    "instructions": [
                        "cd /src",
                        "make test",
                    ],
                },
            ),
            ToolCall(
                id="test_instructions_call_2",
                name="test_instructions",
                args={
                    "instructions": [
                        "cd /src2",
                        "make test2",
                    ]
                },
            ),
        ],
    )

    # Mock the docker command execution for test_instructions
    with (
        patch("buttercup.common.challenge_task.ChallengeTask.exec_docker_cmd") as mock_exec,
        patch("buttercup.common.challenge_task.ChallengeTask.get_clean_task") as mock_clean_task,
        patch("buttercup.common.challenge_task.ChallengeTask.apply_patch_diff") as mock_apply_patch_diff,
        patch(
            "buttercup.patcher.agents.context_retriever._are_test_instructions_valid"
        ) as mock_are_test_instructions_valid,
    ):

        @contextmanager
        def yield_challenge(*args, **kwargs):
            yield mock_challenge

        mock_clean_task.return_value = mock_challenge
        mock_apply_patch_diff.return_value = True
        mock_challenge.apply_patch_diff = MagicMock(return_value=True)
        mock_challenge.get_rw_copy = MagicMock(side_effect=yield_challenge)

        def test_instructions_exec(*args, **kwargs):
            if "mount_dirs" in kwargs:
                mount_dirs = kwargs["mount_dirs"]
                mount_dirs_list = list(mount_dirs.items())
                test_file_path = mount_dirs_list[0][0]
                test_file_content = test_file_path.read_text()
                if "cd /src2" in test_file_content:
                    return CommandResult(
                        success=True,
                        returncode=0,
                        output=b"Tests passed",
                        error=b"",
                    )
                else:
                    return CommandResult(
                        success=True,
                        returncode=1,
                        output=b"Tests failed",
                        error=b"",
                    )

            return CommandResult(success=True, returncode=0, output=b"", error=b"")

        mock_exec.side_effect = test_instructions_exec
        mock_are_test_instructions_valid.return_value = True

        result = mock_agent.find_tests_node(state, mock_runnable_config)

        # Verify the agent found and validated test instructions
        assert result is not None
        assert result.update is not None
        assert result.update["tests_instructions"] == "#!/bin/bash\ncd /src2\nmake test2\n"
        assert result.goto == PatcherAgentName.ROOT_CAUSE_ANALYSIS.value


def test_find_tests_redis_save_and_retrieve(
    mock_agent: ContextRetrieverAgent,
    mock_runnable_config: dict,
    mock_challenge: ChallengeTask,
) -> None:
    """Test that find_tests_node correctly saves and retrieves test instructions from Redis."""
    from unittest.mock import MagicMock

    # Create a mock Redis instance
    mock_redis = MagicMock(spec=Redis)
    mock_agent.redis = mock_redis

    # Test data
    task_id = "test-task-id"
    test_instructions = "#!/bin/bash\ncd /src\nmake test\n"

    # Update the challenge task ID to match our test data
    mock_challenge.task_meta.task_id = task_id

    state = PatcherAgentState(
        context=PatchInput(
            challenge_task_dir=Path("/test/dir"),
            task_id=task_id,
            internal_patch_id="1",
            povs=[
                PatchInputPoV(
                    challenge_task_dir=Path("/test/dir"),
                    sanitizer="address",
                    pov=Path("test.pov"),
                    pov_token="test-token",
                    sanitizer_output="test output",
                    engine="libfuzzer",
                    harness_name="test-harness",
                )
            ],
        ),
        relevant_code_snippets=set(),
        execution_info={},
    )

    # Test 1: Verify that instructions are saved to Redis when found
    # Mock the find_tests_agent to return successful test instructions
    mock_find_tests_agent = MagicMock()
    mock_find_tests_agent.invoke.return_value = AIMessage(
        content="I found test instructions in the README.",
        tool_calls=[
            ToolCall(
                id="test_instructions_call_1",
                name="test_instructions",
                args={
                    "instructions": [
                        "cd /src",
                        "make test",
                    ],
                },
            )
        ],
    )
    # Mock the state with all required fields
    mock_find_tests_agent.get_state.return_value.values = {
        "tests_instructions": test_instructions,
        "messages": [],  # Required field
        "challenge_task_dir": Path("/test/dir"),  # Required field
        "work_dir": mock_runnable_config["configurable"]["work_dir"],  # Required field
    }
    mock_agent.find_tests_agent = mock_find_tests_agent

    # Mock the docker command execution for test_instructions
    with (
        patch("buttercup.common.challenge_task.ChallengeTask.exec_docker_cmd") as mock_exec,
        patch("buttercup.common.challenge_task.ChallengeTask.get_clean_task") as mock_clean_task,
        patch("buttercup.common.challenge_task.ChallengeTask.apply_patch_diff") as mock_apply_patch_diff,
        patch("buttercup.common.challenge_task.ChallengeTask.get_oss_fuzz_path") as mock_get_oss_fuzz_path,
        patch(
            "buttercup.patcher.agents.context_retriever._are_test_instructions_valid"
        ) as mock_are_test_instructions_valid,
    ):

        @contextmanager
        def yield_challenge(*args, **kwargs):
            yield mock_challenge

        mock_clean_task.return_value = mock_challenge
        mock_apply_patch_diff.return_value = True
        mock_challenge.apply_patch_diff = MagicMock(return_value=True)
        mock_challenge.get_rw_copy = MagicMock(side_effect=yield_challenge)
        mock_get_oss_fuzz_path.return_value = Path("/test/oss-fuzz")
        mock_exec.return_value = CommandResult(
            success=True,
            returncode=0,
            output=b"Tests passed",
            error=b"",
        )
        mock_are_test_instructions_valid.return_value = True

        # Initially, Redis should not have any instructions for this task
        mock_redis.hget.return_value = None

        result = mock_agent.find_tests_node(state, mock_runnable_config)

        # Verify that the agent found and validated test instructions
        assert result.update["tests_instructions"] == test_instructions
        assert result.goto == PatcherAgentName.ROOT_CAUSE_ANALYSIS.value

        # Verify that the instructions were saved to Redis
        mock_redis.hset.assert_called_once_with(CUSTOM_TEST_MAP_NAME, task_id, test_instructions)

    # Test 2: Verify that instructions are retrieved from Redis when available
    # Reset the mock to clear previous calls
    mock_redis.reset_mock()

    # Mock Redis to return existing instructions
    mock_redis.hget.return_value = test_instructions

    # Mock that test.sh file doesn't exist (so it goes to Redis lookup)
    with (
        patch("pathlib.Path.exists", return_value=False),
        patch("buttercup.common.challenge_task.ChallengeTask.get_oss_fuzz_path") as mock_get_oss_fuzz_path,
    ):
        mock_get_oss_fuzz_path.return_value = Path("/test/oss-fuzz")
        result = mock_agent.find_tests_node(state, mock_runnable_config)

        # Verify that the agent retrieved instructions from Redis
        assert result.update["tests_instructions"] == test_instructions
        assert result.goto == PatcherAgentName.ROOT_CAUSE_ANALYSIS.value

        # Verify that Redis was queried for the instructions
        mock_redis.hget.assert_called_once_with(CUSTOM_TEST_MAP_NAME, task_id)

        # Verify that hset was NOT called (since we retrieved from Redis)
        mock_redis.hset.assert_not_called()

    # Test 3: Verify behavior when Redis is None
    mock_agent.redis = None

    # Mock that test.sh file doesn't exist
    with (
        patch("pathlib.Path.exists", return_value=False),
        patch("buttercup.common.challenge_task.ChallengeTask.get_oss_fuzz_path") as mock_get_oss_fuzz_path,
        patch("buttercup.common.challenge_task.ChallengeTask.get_clean_task") as mock_get_clean_task,
    ):
        mock_get_oss_fuzz_path.return_value = Path("/test/oss-fuzz")
        mock_get_clean_task.return_value = mock_challenge

        # Mock the find_tests_agent to avoid actual execution
        mock_find_tests_agent = MagicMock()
        mock_find_tests_agent.invoke.return_value = AIMessage(content="Test")
        mock_find_tests_agent.get_state.return_value.values = {
            "tests_instructions": None,
            "messages": [],
            "challenge_task_dir": Path("/test/dir"),
            "work_dir": mock_runnable_config["configurable"]["work_dir"],
        }
        mock_agent.find_tests_agent = mock_find_tests_agent

        result = mock_agent.find_tests_node(state, mock_runnable_config)

        # Should proceed to find tests agent since Redis is None
        # The result should be the same as when Redis was available but empty
        assert result.goto == PatcherAgentName.ROOT_CAUSE_ANALYSIS.value

    # Test 4: Verify that _get_custom_test_instructions returns None when Redis is None
    assert mock_agent._get_custom_test_instructions() is None

    # Test 5: Verify that _save_custom_test_instructions does nothing when Redis is None
    # This should not raise any exceptions
    mock_agent._save_custom_test_instructions("some instructions")

    # Test 6: Verify Redis operations with actual Redis instance
    mock_agent.redis = mock_redis

    # Test _get_custom_test_instructions
    mock_redis.hget.return_value = "cached_instructions"
    assert mock_agent._get_custom_test_instructions() == "cached_instructions"
    mock_redis.hget.assert_called_with(CUSTOM_TEST_MAP_NAME, task_id)

    # Test _save_custom_test_instructions
    mock_agent._save_custom_test_instructions("new_instructions")
    mock_redis.hset.assert_called_with(CUSTOM_TEST_MAP_NAME, task_id, "new_instructions")


def test_find_tests_redis_multiple_tasks(
    mock_agent: ContextRetrieverAgent,
    mock_runnable_config: dict,
    mock_challenge: ChallengeTask,
) -> None:
    """Test that Redis correctly handles multiple tasks with different test instructions."""
    from unittest.mock import MagicMock

    # Create a mock Redis instance
    mock_redis = MagicMock(spec=Redis)
    mock_agent.redis = mock_redis

    # Test data for multiple tasks
    task_id_1 = "test-task-1"
    task_id_2 = "test-task-2"
    instructions_1 = "#!/bin/bash\ncd /src\nmake test\n"
    instructions_2 = "#!/bin/bash\ncd /src\n./run_tests.sh\n"

    # Test that different tasks get different instructions
    mock_redis.hget.side_effect = lambda map_name, task_id: {
        task_id_1: instructions_1,
        task_id_2: instructions_2,
    }.get(task_id, None)

    # Test task 1
    mock_challenge.task_meta.task_id = task_id_1
    state_1 = PatcherAgentState(
        context=PatchInput(
            challenge_task_dir=Path("/test/dir"),
            task_id=task_id_1,
            internal_patch_id="1",
            povs=[
                PatchInputPoV(
                    challenge_task_dir=Path("/test/dir"),
                    sanitizer="address",
                    pov=Path("test.pov"),
                    pov_token="test-token",
                    sanitizer_output="test output",
                    engine="libfuzzer",
                    harness_name="test-harness",
                )
            ],
        ),
        relevant_code_snippets=set(),
        execution_info={},
    )

    with (
        patch("pathlib.Path.exists", return_value=False),
        patch("buttercup.common.challenge_task.ChallengeTask.get_oss_fuzz_path") as mock_get_oss_fuzz_path,
    ):
        mock_get_oss_fuzz_path.return_value = Path("/test/oss-fuzz")
        result_1 = mock_agent.find_tests_node(state_1, mock_runnable_config)
        assert result_1.update["tests_instructions"] == instructions_1

    # Test task 2
    mock_challenge.task_meta.task_id = task_id_2
    state_2 = PatcherAgentState(
        context=PatchInput(
            challenge_task_dir=Path("/test/dir"),
            task_id=task_id_2,
            internal_patch_id="1",
            povs=[
                PatchInputPoV(
                    challenge_task_dir=Path("/test/dir"),
                    sanitizer="address",
                    pov=Path("test.pov"),
                    pov_token="test-token",
                    sanitizer_output="test output",
                    engine="libfuzzer",
                    harness_name="test-harness",
                )
            ],
        ),
        relevant_code_snippets=set(),
        execution_info={},
    )

    with (
        patch("pathlib.Path.exists", return_value=False),
        patch("buttercup.common.challenge_task.ChallengeTask.get_oss_fuzz_path") as mock_get_oss_fuzz_path,
    ):
        mock_get_oss_fuzz_path.return_value = Path("/test/oss-fuzz")
        result_2 = mock_agent.find_tests_node(state_2, mock_runnable_config)
        assert result_2.update["tests_instructions"] == instructions_2

    # Verify that Redis was called with the correct task IDs
    assert mock_redis.hget.call_count == 2
    calls = mock_redis.hget.call_args_list
    assert calls[0] == ((CUSTOM_TEST_MAP_NAME, task_id_1),)
    assert calls[1] == ((CUSTOM_TEST_MAP_NAME, task_id_2),)
