"""Tests for the RootCause agent."""

from typing import Iterator
import pytest
from pathlib import Path
import shutil
import subprocess
from unittest.mock import MagicMock, patch
from langchain_core.messages import AIMessage
import os
from langchain_core.language_models import BaseChatModel
from langchain_core.runnables import Runnable, RunnableSequence

from buttercup.patcher.agents.rootcause import RootCauseAgent, get_modified_line_ranges
from buttercup.patcher.agents.common import (
    PatcherAgentState,
    PatcherAgentName,
    ContextCodeSnippet,
    CodeSnippetKey,
)
from buttercup.patcher.patcher import PatchInput
from buttercup.patcher.utils import PatchInputPoV
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
def mock_agent_llm():
    llm = MagicMock(spec=BaseChatModel)
    llm.__or__.return_value = llm
    return llm


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
def mock_llm_functions(mock_llm: MagicMock, mock_agent_llm: MagicMock):
    """Mock LLM creation functions and environment variables."""
    with (
        patch.dict(os.environ, {"BUTTERCUP_LITELLM_HOSTNAME": "http://test-host", "BUTTERCUP_LITELLM_KEY": "test-key"}),
        patch("buttercup.common.llm.create_default_llm", return_value=mock_llm),
        patch("buttercup.common.llm.create_llm", return_value=mock_llm),
        patch("langgraph.prebuilt.chat_agent_executor._get_prompt_runnable", return_value=mock_agent_llm),
    ):
        import buttercup.patcher.agents.rootcause

        buttercup.patcher.agents.rootcause.ROOT_CAUSE_PROMPT = mock_root_cause_prompt
        yield


DIFF_1 = """diff --git a/file.py b/file.py
index 1234567..abcdefg 100644
--- a/file.py
+++ b/file.py
@@ -10,1 +10,3 @@
     print("Hello")
+    print("World")
+    print("!")
     return True
"""

DIFF_2 = """diff --git a/file.c b/file2.c
index 124467..abcdefg 100644
--- a/file.c
+++ b/file2.c
@@ -10,1 +10,3 @@
     b = a + c;
+    printf("Hello");
+    printf("World");
     return 0;
"""


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

    # Add two simple diff files to the challenge task
    (diffs / "patch1.diff").write_text(DIFF_1)
    (diffs / "patch2.diff").write_text(DIFF_2)

    # Create project.yaml file
    project_yaml_path = oss_fuzz / "projects" / "example_project" / "project.yaml"
    project_yaml_path.parent.mkdir(parents=True, exist_ok=True)
    project_yaml_path.write_text("""name: example_project
language: c
""")

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
    agent = RootCauseAgent(
        challenge=mock_challenge,
        input=patch_input,
        chain_call=lambda _, runnable, args, config, default: runnable.invoke(args, config=config),
    )
    agent.root_cause_chain = MagicMock()
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
    root_cause_agent.root_cause_chain.invoke.return_value = state
    state.messages = []

    with pytest.raises(Exception):
        root_cause_agent.analyze_vulnerability(state)


def test_rootcause_requests(root_cause_agent: RootCauseAgent, mock_llm: MagicMock, mock_runnable_config: dict) -> None:
    """Test vulnerability analysis when snippet requests are found."""
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

    root_cause_agent.root_cause_chain.invoke.return_value = state
    state.messages = [
        AIMessage(
            content="<code_snippet_requests><code_snippet_request>Request 1</code_snippet_request><code_snippet_request>Request 2</code_snippet_request></code_snippet_requests>"
        )
    ]

    root_cause_agent.analyze_vulnerability(state)
    assert state.root_cause is None
    assert state.execution_info.code_snippet_requests is not None
    assert len(state.execution_info.code_snippet_requests) == 2
    assert state.execution_info.code_snippet_requests[0].request == "Request 1"
    assert state.execution_info.code_snippet_requests[1].request == "Request 2"


def test_rootcause_success(root_cause_agent: RootCauseAgent, mock_llm: MagicMock, mock_runnable_config: dict) -> None:
    """Test vulnerability analysis when a root cause is found."""
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

    root_cause_agent.root_cause_chain.invoke.return_value = state
    state.messages = [AIMessage(content="Root cause")]

    command = root_cause_agent.analyze_vulnerability(state)
    assert command.goto == PatcherAgentName.PATCH_STRATEGY.value
    assert "root_cause" in command.update
    assert command.update["root_cause"] == "Root cause"


def test_rootcause_multiple_povs(
    root_cause_agent: RootCauseAgent, mock_llm: MagicMock, mock_runnable_config: dict
) -> None:
    """Test vulnerability analysis with multiple POVs."""
    # Create a state with multiple POVs and their corresponding code snippets
    state = PatcherAgentState(
        context=PatchInput(
            task_id=root_cause_agent.input.task_id,
            internal_patch_id=root_cause_agent.input.internal_patch_id,
            povs=[
                # First POV - heap buffer overflow
                PatchInputPoV(
                    challenge_task_dir=root_cause_agent.input.povs[0].challenge_task_dir,
                    sanitizer="address",
                    pov=Path("test1.pov"),
                    pov_token="test-token-1",
                    sanitizer_output="""==1==ERROR: AddressSanitizer: heap-buffer-overflow
 #0 0x123456 in crash_func /src/test/crash.c:10
 #1 0x234567 in process_data /src/test/process.c:20""",
                    engine="libfuzzer",
                    harness_name="test-harness-1",
                ),
                # Second POV - use after free
                PatchInputPoV(
                    challenge_task_dir=root_cause_agent.input.povs[0].challenge_task_dir,
                    sanitizer="address",
                    pov=Path("test2.pov"),
                    pov_token="test-token-2",
                    sanitizer_output="""==1==ERROR: AddressSanitizer: heap-use-after-free
 #0 0x456789 in crash_func /src/test/crash.c:10
 #1 0x567890 in process_data /src/test/process.c:20""",
                    engine="libfuzzer",
                    harness_name="test-harness-2",
                ),
            ],
        ),
        relevant_code_snippets=[
            # Code snippets from both POVs
            ContextCodeSnippet(
                key=CodeSnippetKey(file_path="/src/test/crash.c", identifier="crash_func"),
                start_line=10,
                end_line=10,
                code="void crash_func() { /* crash */ }",
                code_context="",
            ),
            ContextCodeSnippet(
                key=CodeSnippetKey(file_path="/src/test/process.c", identifier="process_data"),
                start_line=20,
                end_line=20,
                code="void process_data() { /* process */ }",
                code_context="",
            ),
        ],
    )

    # Mock the root cause chain to return a state with a root cause
    root_cause_agent.root_cause_chain.invoke.return_value = state
    state.messages = [
        AIMessage(
            content="""Root cause analysis:
1. Both POVs crash in crash_func() which is called by process_data()
2. The heap buffer overflow and use-after-free suggest memory management issues
3. The common path through process_data() indicates a shared vulnerability"""
        )
    ]

    # Test the analyze_vulnerability method
    command = root_cause_agent.analyze_vulnerability(state)

    # Verify the result
    assert command.goto == PatcherAgentName.PATCH_STRATEGY.value
    assert "root_cause" in command.update
    assert "Both POVs crash" in command.update["root_cause"]
    assert "process_data" in command.update["root_cause"]
    assert "memory management" in command.update["root_cause"]

    # Verify that the root cause chain was called with the correct state
    root_cause_agent.root_cause_chain.invoke.assert_called_once()
    call_args = root_cause_agent.root_cause_chain.invoke.call_args[0][0]
    assert call_args.context == state.context
    assert len(call_args.relevant_code_snippets) == 2
    assert any(
        snippet.key.file_path == "/src/test/crash.c" and snippet.key.identifier == "crash_func"
        for snippet in call_args.relevant_code_snippets
    )
    assert any(
        snippet.key.file_path == "/src/test/process.c" and snippet.key.identifier == "process_data"
        for snippet in call_args.relevant_code_snippets
    )


@pytest.mark.parametrize(
    "patch_string,expected_result,expected_file_count",
    [
        # Test case 1: Single file, single hunk
        (
            """diff --git a/file.py b/file.py
index 1234567..abcdefg 100644
--- a/file.py
+++ b/file.py
@@ -10,1 +10,3 @@ def hello():
     print("Hello")
+    print("World")
+    print("!")
     return True
""",
            [("file.py", [(10, 12)])],
            1,
        ),
        # Test case 2: Single file, multiple hunks
        (
            """diff --git a/path/to/file.c b/path/to/file2.c
index 67da216..1e338c2 100644
--- a/path/to/file.c
+++ b/path/to/file2.c
@@ -7,9 +7,6 @@ int main()
     char filename[100];
     int c;

-    printf("Enter the filename to open for reading: ");
-    scanf("%s", filename);
-
     // Open one file for reading
     fptr1 = fopen(filename, "r");
     if (fptr1 == NULL)
@@ -19,6 +16,7 @@ int main()
     }

     printf("Enter the filename to open for writing: ");
+    printf("Some added content")
     scanf("%s", filename);

     // Open another file for writing
""",
            [("path/to/file2.c", [(7, 12), (16, 22)])],
            1,
        ),
        # Test case 3: Multiple files
        (
            """diff --git a/path/to/file.c b/path/to/file2.c
index 67da216..1e338c2 100644
--- a/path/to/file.c
+++ b/path/to/file2.c
@@ -7,9 +7,6 @@ int main()
     char filename[100];
     int c;

-    printf("Enter the filename to open for reading: ");
-    scanf("%s", filename);
-
     // Open one file for reading
     fptr1 = fopen(filename, "r");
     if (fptr1 == NULL)
@@ -19,6 +16,7 @@ int main()
     }

     printf("Enter the filename to open for writing: ");
+    printf("Some added content")
     scanf("%s", filename);

     // Open another file for writing
 
diff --git a/file2.py b/file2.py
index 9876543..fedcba9 100644
--- a/file2.py
+++ b/file2.py
@@ -5,2 +5,3 @@ def func2():
     x = 1
+    y = 2
     return x
""",
            [
                ("path/to/file2.c", [(7, 12), (16, 22)]),
                ("file2.py", [(5, 7)]),
            ],
            2,
        ),
        # Test case 11: File rename
        (
            """diff --git a/old_name.py b/new_name.py
similarity index 85%
rename from old_name.py
rename to new_name.py
index 1234567..abcdefg 100644
--- a/old_name.py
+++ b/new_name.py
@@ -5,1 +5,2 @@
 def function():
+    print("added line")
     pass
""",
            [("new_name.py", [(5, 6)])],
            1,
        ),
        # Test case 12: Binary file (should still work, though no line content)
        (
            """diff --git a/image.png b/image.png
index 1234567..abcdefg 100644
Binary files a/image.png and b/image.png differ
""",
            [("image.png", [])],  # Binary files have no hunks
            1,
        ),
    ],
)
def test_get_modified_line_ranges(patch_string, expected_result, expected_file_count):
    """Test get_modified_line_ranges with various diff formats and scenarios."""
    result = get_modified_line_ranges(patch_string)

    # Test the line ranges match expected
    assert result == expected_result

    # Test the file count matches expected
    assert len(result) == expected_file_count


# Additional simpler specific test for line range
def test_line_range_calculation():
    """Test specific line range calculations."""
    patch = """diff --git a/test.py b/test.py
--- a/test.py
+++ b/test.py
@@ -5,1 +5,4 @@
     a = 1
+    b = 2
+    c = 3
+    d = 4
     return a
"""
    result = get_modified_line_ranges(patch)
    assert len(result) == 1
    file_path, ranges = result[0]
    assert file_path == "test.py"
    assert len(ranges) == 1
    start, end = ranges[0]
    assert start == 5  # Hunk starts at line 5
    assert end == 8  # Three lines actually modified


def test_root_cause_list_diffs(root_cause_agent: RootCauseAgent) -> None:
    """Test root cause list diffs tool."""
    result = root_cause_agent._list_diffs()
    expected = """<diff_files>
<diff_file>
<DIFF_FILE_PATH_1>
<modified_file>
  <file_path>file.py</file_path>
  <modified_lines_range>
    <start_line>10</start_line><end_line>12</end_line>
  </modified_lines_range>
</modified_file>
</diff_file>

<diff_file>
<DIFF_FILE_PATH_2>
<modified_file>
  <file_path>file2.c</file_path>
  <modified_lines_range>
    <start_line>10</start_line><end_line>12</end_line>
  </modified_lines_range>
</modified_file>
</diff_file>

</diff_files>"""

    # Copy the <diff_file_path> from the result into the expected result.
    # We can't predict these values in advance because they are temporary
    # files and dirs created by the task_dir fixture.
    cnt = 1
    for line in result.split("\n"):
        if line.strip().startswith("<diff_file_path>"):
            assert line.strip().endswith(f"/test-challenge-task/diff/my-diff/patch{cnt}.diff</diff_file_path>")
            expected = expected.replace(f"<DIFF_FILE_PATH_{cnt}>", line)
            cnt += 1

    assert "".join(result.split()) == "".join(expected.split())


def test_root_cause_get_diffs(root_cause_agent: RootCauseAgent) -> None:
    """Test root cause get diffs tool."""
    diffs = root_cause_agent._list_diffs()
    # Manually parse xml result to get the diff file paths
    # Not the cleanest but that will do.
    diff_files = [
        line.split("</diff_file_path>")[0].split("<diff_file_path>")[1]
        for line in diffs.split("\n")
        if line.strip().startswith("<diff_file_path>")
    ]
    assert len(diff_files) == 2
    # Check that we can get each diff individually
    assert root_cause_agent._get_diffs(diff_files[0]).strip() == DIFF_1.strip()
    assert root_cause_agent._get_diffs(diff_files[1]).strip() == DIFF_2.strip()
    # Check that getting multiple diff files at once works
    assert root_cause_agent._get_diffs(diff_files).strip() == f"{DIFF_1}\n{DIFF_2}".strip()
