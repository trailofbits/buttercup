"""Tests for the ContextRetrieverAgent."""

import pytest
from pathlib import Path
import shutil
import subprocess
from unittest.mock import MagicMock, patch
import os

from buttercup.patcher.agents.context_retriever import ContextRetrieverAgent
from buttercup.patcher.agents.common import ContextRetrieverState, CodeSnippetRequest
from buttercup.patcher.patcher import PatchInput
from langgraph.types import Command
from buttercup.common.challenge_task import ChallengeTask
from buttercup.common.task_meta import TaskMeta
from langchain_core.messages import AIMessage
from langchain_core.messages.tool import ToolCall


@pytest.fixture
def mock_llm():
    return MagicMock()


@pytest.fixture
def mock_chain(mock_llm: MagicMock):
    res = MagicMock()
    res.with_fallbacks.return_value = mock_llm
    res.with_fallbacks.return_value.bind_tools.return_value = mock_llm
    return res


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
    (source / "test.c").write_text("int foo() { return 0; }\nint main() { int a = foo(); return a; }")
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
    TaskMeta(project_name="selinux", focus="selinux", task_id="task-id-selinux").save(tmp_path)

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
        submission_index="1",
        harness_name="secilc-fuzzer",
        # not used by the context retriever
        pov=Path("pov-path-selinux"),
        sanitizer_output="sanitizer-output-selinux",
        engine="libfuzzer",
        sanitizer="address",
    )
    wdir = tmp_path / "work_dir"
    wdir.mkdir(parents=True)
    return ContextRetrieverAgent(
        input=patch_input,
        chain_call=lambda _, runnable, args, config, default: runnable.invoke(args, config=config),
        challenge=selinux_oss_fuzz_task,
        work_dir=wdir,
    )


@pytest.fixture
def mock_agent(mock_challenge: ChallengeTask, tmp_path: Path) -> ContextRetrieverAgent:
    """Create a ContextRetrieverAgent instance."""
    patch_input = PatchInput(
        challenge_task_dir=mock_challenge.task_dir,
        task_id=mock_challenge.task_meta.task_id,
        submission_index="1",
        harness_name="mock-harness",
        # not used by the context retriever
        pov=Path("pov-path-mock"),
        sanitizer_output="sanitizer-output-mock",
        engine="libfuzzer",
        sanitizer="address",
    )
    wdir = tmp_path / "work_dir"
    wdir.mkdir(parents=True)
    with patch("subprocess.run", side_effect=mock_docker_run(mock_challenge)):
        return ContextRetrieverAgent(
            input=patch_input,
            chain_call=lambda _, runnable, args, config, default: runnable.invoke(args, config=config),
            challenge=mock_challenge,
            work_dir=wdir,
        )


@pytest.mark.integration
def test_retrieve_context_basic(selinux_agent: ContextRetrieverAgent, mock_llm: MagicMock) -> None:
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
    mock_llm.invoke.side_effect = [
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
                    id="get_function_definition_call_1",
                    name="get_function_definition",
                    args={"function_name": "ebitmap_match_any", "file_path": "libsepol/src/ebitmap.c"},
                )
            ],
        ),
        AIMessage(
            content="I'm done <END>",
        ),
    ]
    result = selinux_agent.retrieve_context(state)

    # Verify the result
    assert isinstance(result, Command)
    assert result.goto == "test_node"
    assert "relevant_code_snippets" in result.update
    assert len(result.update["relevant_code_snippets"]) == 1

    # Verify the code snippet content
    snippet = next(iter(result.update["relevant_code_snippets"]))
    assert "ebitmap_match_any" in snippet.code
    assert "const ebitmap_t *e1" in snippet.code


def test_missing_arg_tool_call(mock_agent: ContextRetrieverAgent, mock_llm: MagicMock) -> None:
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
    mock_llm.invoke.side_effect = [
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
                    id="get_function_definition_call_1",
                    name="get_function_definition",
                    args={
                        "function_name": "main",
                        "file_path": "test.c",
                    },
                )
            ],
        ),
        AIMessage(
            content="I'm done <END>",
        ),
    ]
    result = mock_agent.retrieve_context(state)

    # Verify the result
    assert isinstance(result, Command)
    assert result.goto == "test_node"
    assert "relevant_code_snippets" in result.update
    assert len(result.update["relevant_code_snippets"]) == 1


def test_recursion_limit(mock_agent: ContextRetrieverAgent, mock_llm: MagicMock) -> None:
    """Test hitting the context request limit."""
    state = ContextRetrieverState(
        code_snippet_requests=[
            CodeSnippetRequest(
                request="Find function main",
            )
        ],
        prev_node="test_node",
    )

    mock_llm.invoke.side_effect = [
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
    result = mock_agent.retrieve_context(state)

    # Verify the result
    assert isinstance(result, Command)
    assert result.goto == "test_node"
    assert "relevant_code_snippets" in result.update
    assert len(result.update["relevant_code_snippets"]) == 0, (
        "Should not have any code snippets, we hit the recursion limit and never called the get_function_definition/get_type_definition tool"
    )


def test_recursion_limit_tmp_code_snippets(mock_agent: ContextRetrieverAgent, mock_llm: MagicMock) -> None:
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
                    id="get_function_definition_call",
                    name="get_function_definition",
                    args={
                        "function_name": "main",
                        "file_path": "test.c",
                    },
                )
            ],
        )
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
    mock_llm.invoke.side_effect = llm_invoke_side_effect
    result = mock_agent.retrieve_context(state)

    assert isinstance(result, Command)
    assert result.goto == "test_node"
    assert "relevant_code_snippets" in result.update
    assert len(result.update["relevant_code_snippets"]) == 1
    code_snippet = next(iter(result.update["relevant_code_snippets"]))
    assert code_snippet.code == "int main() { int a = foo(); return a; }"


def test_dupped_code_snippets(mock_agent: ContextRetrieverAgent, mock_llm: MagicMock) -> None:
    """Test that we don't return duplicate code snippets."""
    state = ContextRetrieverState(
        code_snippet_requests=[
            CodeSnippetRequest(request="Find function main"),
        ],
        prev_node="test_node",
    )
    mock_llm.invoke.side_effect = [
        AIMessage(
            content="I'll get the function definition.",
            tool_calls=[
                ToolCall(
                    id="get_function_definition_call",
                    name="get_function_definition",
                    args={"function_name": "main", "file_path": "test.c"},
                )
            ],
        ),
        AIMessage(
            content="I'm done <END>",
        ),
    ]
    result = mock_agent.retrieve_context(state)
    assert isinstance(result, Command)
    assert result.goto == "test_node"
    assert "relevant_code_snippets" in result.update
    assert len(result.update["relevant_code_snippets"]) == 1
    code_snippet = next(iter(result.update["relevant_code_snippets"]))
    assert code_snippet.code == "int main() { int a = foo(); return a; }"

    mock_llm.invoke.side_effect = [
        AIMessage(
            content="I'll get the function definition.",
            tool_calls=[
                ToolCall(
                    id="get_function_definition_call",
                    name="get_function_definition",
                    args={"function_name": "main", "file_path": "test.c"},
                )
            ],
        ),
        AIMessage(
            content="I'll get the function definition.",
            tool_calls=[
                ToolCall(
                    id="get_function_definition_call",
                    name="get_function_definition",
                    args={"function_name": "main", "file_path": "test.c"},
                )
            ],
        ),
        AIMessage(
            content="I'm done <END>",
        ),
    ]
    result = mock_agent.retrieve_context(state)
    assert isinstance(result, Command)
    assert result.goto == "test_node"
    assert "relevant_code_snippets" in result.update
    assert len(result.update["relevant_code_snippets"]) == 1
    code_snippet = next(iter(result.update["relevant_code_snippets"]))
    assert code_snippet.code == "int main() { int a = foo(); return a; }"


def test_get_type_definition(mock_agent: ContextRetrieverAgent, mock_llm: MagicMock) -> None:
    """Test that we can get the type definition."""
    state = ContextRetrieverState(
        code_snippet_requests=[
            CodeSnippetRequest(request="Find type ebitmap_t"),
        ],
        prev_node="test_node",
    )
    mock_llm.invoke.side_effect = [
        AIMessage(
            content="I'll get the type definition.",
            tool_calls=[
                ToolCall(
                    id="get_type_definition_call",
                    name="get_type_definition",
                    args={"type_name": "ebitmap_t", "file_path": "test.h"},
                )
            ],
        ),
        AIMessage(
            content="I'm done <END>",
        ),
    ]
    result = mock_agent.retrieve_context(state)
    assert isinstance(result, Command)
    assert result.goto == "test_node"
    assert "relevant_code_snippets" in result.update
    assert len(result.update["relevant_code_snippets"]) == 1
    code_snippet = next(iter(result.update["relevant_code_snippets"]))
    assert code_snippet.code == "struct ebitmap_t { int a; }"


def test_get_definitions_no_paths(mock_agent: ContextRetrieverAgent, mock_llm: MagicMock) -> None:
    """Test that we can get the type definition even if the file path is not provided."""
    state = ContextRetrieverState(
        code_snippet_requests=[
            CodeSnippetRequest(request="Find type ebitmap_t"),
        ],
        prev_node="test_node",
    )

    mock_llm.invoke.side_effect = [
        AIMessage(
            content="I'll get the function definition.",
            tool_calls=[
                ToolCall(
                    id="get_function_definition_call",
                    name="get_function_definition",
                    args={"function_name": "main", "file_path": None},
                )
            ],
        ),
        AIMessage(
            content="I'll get the type definition.",
            tool_calls=[
                ToolCall(
                    id="get_type_definition_call",
                    name="get_type_definition",
                    args={"type_name": "ebitmap_t", "file_path": None},
                )
            ],
        ),
        AIMessage(
            content="I'm done <END>",
        ),
    ]
    result = mock_agent.retrieve_context(state)
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


def test_get_callers(mock_agent: ContextRetrieverAgent, mock_llm: MagicMock) -> None:
    """Test that we can get the callers of a function."""
    state = ContextRetrieverState(
        code_snippet_requests=[
            CodeSnippetRequest(request="Find callers of foo"),
        ],
        prev_node="test_node",
    )
    mock_llm.invoke.side_effect = [
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
    result = mock_agent.retrieve_context(state)
    assert isinstance(result, Command)
    assert result.goto == "test_node"
    assert "relevant_code_snippets" in result.update
    assert len(result.update["relevant_code_snippets"]) == 1
    code_snippet = next(iter(result.update["relevant_code_snippets"]))
    assert code_snippet.code == "int main() { int a = foo(); return a; }"


def test_get_callees(mock_agent: ContextRetrieverAgent, mock_llm: MagicMock) -> None:
    """Test that we can get the callees of a function."""
    state = ContextRetrieverState(
        code_snippet_requests=[
            CodeSnippetRequest(request="Find callees of main"),
        ],
        prev_node="test_node",
    )
    mock_llm.invoke.side_effect = [
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
    result = mock_agent.retrieve_context(state)
    assert isinstance(result, Command)
    assert result.goto == "test_node"
    assert "relevant_code_snippets" in result.update
    assert len(result.update["relevant_code_snippets"]) == 1
    code_snippet = next(iter(result.update["relevant_code_snippets"]))
    assert code_snippet.code == "int foo() { return 0; }"
