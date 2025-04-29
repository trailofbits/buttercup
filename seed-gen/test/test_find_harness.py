"""Tests for finding libfuzzer and jazzer harnesses in source code."""

from pathlib import Path

import pytest

from buttercup.common.challenge_task import ChallengeTask
from buttercup.common.task_meta import TaskMeta
from buttercup.seed_gen.find_harness import (
    find_jazzer_harnesses,
    find_libfuzzer_harnesses,
    get_harness_source_candidates,
)

FUZZ_TARGET_CPP = """
#include <stddef.h>
#include <stdint.h>

extern "C" int LLVMFuzzerTestOneInput(const uint8_t* data, size_t size) {
    // Test code here
    return 0;
}
"""

NORMAL_CPP = """
#include <iostream>

int main() {
    std::cout << "Hello World!" << std::endl;
    return 0;
}
"""

FUZZ_TARGET_JAVA = """
import com.code_intelligence.jazzer.api.FuzzedDataProvider;
import com.code_intelligence.jazzer.junit.FuzzTest;

public class FuzzTarget {
    @FuzzTest
    public void fuzzerTestOneInput(FuzzedDataProvider data) {
        // Test code here
    }
}
"""

NORMAL_JAVA = """
public class Normal {
    public static void main(String[] args) {
        System.out.println("Hello World!");
    }
}
"""

NORMAL_CPP_WITH_COMMENT = """
#include <iostream>

// This is a comment containing LLVMFuzzerTestOneInput
int main() {
    std::cout << "Hello World!" << std::endl;
    return 0;
}
"""

NORMAL_JAVA_WITH_COMMENT = """
// This is a comment containing fuzzerTestOneInput
public class Normal {
    public static void main(String[] args) {
        System.out.println("Hello World!");
    }
}
"""

MULTILINE_FUZZER_CPP = """
#include <stddef.h>
#include <stdint.h>

extern "C" int LLVMFuzzerTestOneInput(
    const uint8_t* data,
    size_t size
) {
    // Test code here
    return 0;
}
"""

MULTILINE_FUZZER_JAVA = """
import com.code_intelligence.jazzer.api.FuzzedDataProvider;
import com.code_intelligence.jazzer.junit.FuzzTest;

public class MultilineFuzzer {
    @FuzzTest
    public void fuzzerTestOneInput(
        FuzzedDataProvider data
    ) {
        // Test code here
    }
}
"""


@pytest.fixture
def task_dir(tmp_path: Path) -> Path:
    """Create a mock challenge task directory structure."""
    # Create the main directories
    oss_fuzz = tmp_path / "fuzz-tooling" / "my-oss-fuzz"
    source = tmp_path / "src" / "my-source"
    diffs = tmp_path / "diff" / "my-diff"

    oss_fuzz.mkdir(parents=True, exist_ok=True)
    source.mkdir(parents=True, exist_ok=True)
    diffs.mkdir(parents=True, exist_ok=True)

    # Create a mock helper.py file
    helper_path = oss_fuzz / "infra/helper.py"
    helper_path.parent.mkdir(parents=True, exist_ok=True)
    helper_path.write_text("import sys;\nsys.exit(0)\n")

    project_name = "my-project"
    project_yaml_path = oss_fuzz / "projects" / project_name / "project.yaml"
    project_yaml_path.parent.mkdir(parents=True, exist_ok=True)
    # Create task metadata
    TaskMeta(
        project_name=project_name,
        focus="my-source",
        task_id="task-id-challenge-task",
        metadata={"task_id": "task-id-challenge-task", "round_id": "testing", "team_id": "tob"},
    ).save(tmp_path)

    return tmp_path


@pytest.fixture
def challenge_task(task_dir: Path) -> ChallengeTask:
    """Create a mock challenge task for testing."""
    return ChallengeTask(
        read_only_task_dir=task_dir,
    )


def test_find_libfuzzer_harnesses(challenge_task: ChallengeTask):
    """Test finding libfuzzer harnesses in source code."""
    source_path = challenge_task.get_source_path()
    subdir = source_path / "subdir"
    subdir.mkdir(parents=True, exist_ok=True)

    (source_path / "fuzz_target.cpp").write_text(FUZZ_TARGET_CPP)
    (source_path / "another_fuzzer.c").write_text(FUZZ_TARGET_CPP)
    (source_path / "normal.cpp").write_text(NORMAL_CPP)
    (subdir / "FuzzTarget.java").write_text(FUZZ_TARGET_JAVA)
    (source_path / "multiline_fuzzer.cpp").write_text(MULTILINE_FUZZER_CPP)

    # Find harnesses
    harnesses = find_libfuzzer_harnesses(challenge_task)

    # Verify results
    assert len(harnesses) == 3
    harness_paths = {h.name for h in harnesses}
    assert "fuzz_target.cpp" in harness_paths
    assert "another_fuzzer.c" in harness_paths
    assert "multiline_fuzzer.cpp" in harness_paths


def test_find_jazzer_harnesses(challenge_task: ChallengeTask):
    """Test finding jazzer harnesses in source code."""
    source_path = challenge_task.get_source_path()
    subdir = source_path / "subdir"
    subdir.mkdir(parents=True, exist_ok=True)
    (source_path / "fuzz_target.cpp").write_text(FUZZ_TARGET_CPP)
    (source_path / "normal.java").write_text(NORMAL_JAVA)
    (subdir / "FuzzTarget.java").write_text(FUZZ_TARGET_JAVA)
    (source_path / "MultilineFuzzer.java").write_text(MULTILINE_FUZZER_JAVA)
    # Find harnesses
    harnesses = find_jazzer_harnesses(challenge_task)

    # Verify results
    assert len(harnesses) == 2
    harness_paths = {h.name for h in harnesses}
    assert "FuzzTarget.java" in harness_paths
    assert "MultilineFuzzer.java" in harness_paths


def test_find_harnesses_with_comments(challenge_task: ChallengeTask):
    """Test finding harnesses when the target string appears in comments."""
    source_path = challenge_task.get_source_path()

    # Create files with target strings in comments
    (source_path / "commented.cpp").write_text(NORMAL_CPP_WITH_COMMENT)
    (source_path / "commented.java").write_text(NORMAL_JAVA_WITH_COMMENT)

    # Find harnesses
    libfuzzer_harnesses = find_libfuzzer_harnesses(challenge_task)
    jazzer_harnesses = find_jazzer_harnesses(challenge_task)

    # Verify results - should not match since strings are in comments
    assert len(libfuzzer_harnesses) == 0
    assert len(jazzer_harnesses) == 0


def test_find_harnesses_in_oss_fuzz_project(challenge_task: ChallengeTask):
    """Test finding harnesses when they are in the oss-fuzz project directory."""
    source_path = challenge_task.get_source_path()
    oss_fuzz_path = challenge_task.task_dir / "fuzz-tooling/my-oss-fuzz/projects/my-project"

    # Create files with target strings in comments
    (oss_fuzz_path / "fuzz_target.cpp").write_text(FUZZ_TARGET_CPP)
    (source_path / "fuzz_target1.cpp").write_text(FUZZ_TARGET_CPP)
    (oss_fuzz_path / "FuzzTarget.java").write_text(FUZZ_TARGET_JAVA)

    # Find harnesses
    libfuzzer_harnesses = find_libfuzzer_harnesses(challenge_task)
    jazzer_harnesses = find_jazzer_harnesses(challenge_task)

    assert len(libfuzzer_harnesses) == 2
    assert "fuzz_target.cpp" in {h.name for h in libfuzzer_harnesses}
    assert "fuzz_target1.cpp" in {h.name for h in libfuzzer_harnesses}
    assert len(jazzer_harnesses) == 1
    assert "FuzzTarget.java" in {h.name for h in jazzer_harnesses}


def test_get_harness_source_candidates_cpp(challenge_task: ChallengeTask):
    """Test getting harness source candidates for C++ project."""
    source_path = challenge_task.get_source_path()
    project_yaml_path = (
        challenge_task.task_dir / "fuzz-tooling/my-oss-fuzz/projects/my-project/project.yaml"
    )
    project_yaml_path.write_text("language: cpp\n")

    # Create test files
    (source_path / "fuzz_target.cpp").write_text(FUZZ_TARGET_CPP)
    (source_path / "another_fuzzer.c").write_text(FUZZ_TARGET_CPP)
    (source_path / "normal.cpp").write_text(NORMAL_CPP)
    (source_path / "FuzzTarget.java").write_text(FUZZ_TARGET_JAVA)

    # Test one candidate is similar
    candidates = get_harness_source_candidates(challenge_task, "my-project", "fuzz_target")
    candidate_names = [c.name for c in candidates]
    assert candidate_names == ["fuzz_target.cpp", "another_fuzzer.c"]

    # Test case-insensitive candidate is similar
    candidates = get_harness_source_candidates(challenge_task, "my-project", "AnotherFuzzer")
    candidate_names = [c.name for c in candidates]
    assert candidate_names == ["another_fuzzer.c", "fuzz_target.cpp"]

    # Test no match
    candidates = get_harness_source_candidates(challenge_task, "my-project", "nonexistent")
    assert len(candidates) == 2
    assert "another_fuzzer.c" in candidate_names
    assert "fuzz_target.cpp" in candidate_names


def test_get_harness_source_candidates_java(challenge_task: ChallengeTask):
    """Test getting harness source candidates for Java project."""
    source_path = challenge_task.get_source_path()
    project_yaml_path = (
        challenge_task.task_dir / "fuzz-tooling/my-oss-fuzz/projects/my-project/project.yaml"
    )
    project_yaml_path.write_text("language: jvm\n")

    # Create test files
    (source_path / "fuzztarget.cpp").write_text(FUZZ_TARGET_CPP)
    (source_path / "another_fuzzer.c").write_text(FUZZ_TARGET_CPP)
    (source_path / "FuzzTarget.java").write_text(FUZZ_TARGET_JAVA)
    (source_path / "FuzzTarget1.java").write_text(FUZZ_TARGET_JAVA)

    # Test one candidate is similar
    candidates = get_harness_source_candidates(challenge_task, "my-project", "FuzzTarget")
    candidate_names = [c.name for c in candidates]
    assert candidate_names == ["FuzzTarget.java", "FuzzTarget1.java"]

    # Test case-insensitive candidate is similar
    candidates = get_harness_source_candidates(challenge_task, "my-project", "fuzztarget1")
    candidate_names = [c.name for c in candidates]
    assert candidate_names == ["FuzzTarget1.java", "FuzzTarget.java"]

    # Test no match
    candidates = get_harness_source_candidates(challenge_task, "my-project", "nonexistent")
    assert len(candidates) == 2
    assert "FuzzTarget.java" in candidate_names
    assert "FuzzTarget1.java" in candidate_names


def test_weird_libfuzzer_harnesses(challenge_task: ChallengeTask):
    """Test finding libfuzzer harnesses with unusual but valid signatures."""
    source_path = challenge_task.get_source_path()

    # Test case 1: Function signature split across multiple lines with weird indentation
    weird_signature_cpp = """
#include <stddef.h>
#include <stdint.h>

extern "C" int 
    LLVMFuzzerTestOneInput(
        const uint8_t* 
            data,
        size_t 
            size
    ) {
    // Test code here
    return 0;
}
"""  # noqa: W291
    # Test case 2: Function signature with extra spaces and newlines
    extra_spaces_cpp = """
#include <stddef.h>
#include <stdint.h>

extern "C" int  LLVMFuzzerTestOneInput  (  const uint8_t*  data  ,  size_t  size  ) {
    // Test code here
    return 0;
}
"""
    # Test case 3: Function signature with comments between parameters
    commented_params_cpp = """
#include <stddef.h>
#include <stdint.h>

extern "C" int LLVMFuzzerTestOneInput(
    const uint8_t* data,  /* input data */
    size_t size          /* size of input */
) {
    // Test code here
    return 0;
}
"""
    # Test case 4: Function signature with line continuation
    line_continuation_cpp = """
#include <stddef.h>
#include <stdint.h>

extern "C" int LLVMFuzzerTestOneInput(\
    const uint8_t* data,\
    size_t size\
) {
    // Test code here
    return 0;
}
"""

    # Write test files
    (source_path / "weird_signature.cpp").write_text(weird_signature_cpp)
    (source_path / "extra_spaces.cpp").write_text(extra_spaces_cpp)
    (source_path / "commented_params.cpp").write_text(commented_params_cpp)
    (source_path / "line_continuation.cpp").write_text(line_continuation_cpp)

    # Find harnesses
    harnesses = find_libfuzzer_harnesses(challenge_task)

    # Verify results
    assert len(harnesses) == 4
    harness_paths = {h.name for h in harnesses}
    assert "weird_signature.cpp" in harness_paths
    assert "extra_spaces.cpp" in harness_paths
    assert "commented_params.cpp" in harness_paths
    assert "line_continuation.cpp" in harness_paths


def test_weird_jazzer_harnesses(challenge_task: ChallengeTask):
    """Test finding jazzer harnesses with unusual but valid signatures."""
    source_path = challenge_task.get_source_path()

    # Test case 1: Annotation and method split across multiple lines
    split_annotation_java = """
import com.code_intelligence.jazzer.api.FuzzedDataProvider;
import com.code_intelligence.jazzer.junit.FuzzTest;

public class SplitAnnotationFuzzer {
    @FuzzTest
    public void 
        fuzzerTestOneInput(
            FuzzedDataProvider 
                data
        ) {
        // Test code here
    }
}
"""  # noqa: W291
    # Test case 2: Method with extra spaces and newlines
    extra_spaces_java = """
import com.code_intelligence.jazzer.api.FuzzedDataProvider;
import com.code_intelligence.jazzer.junit.FuzzTest;

public class ExtraSpacesFuzzer {
    @FuzzTest
    public void  fuzzerTestOneInput  (  FuzzedDataProvider  data  ) {
        // Test code here
    }
}
"""
    # Test case 3: Method with inline comments
    inline_comments_java = """
import com.code_intelligence.jazzer.api.FuzzedDataProvider;
import com.code_intelligence.jazzer.junit.FuzzTest;

public class InlineCommentsFuzzer {
    @FuzzTest
    public void fuzzerTestOneInput(/* input data */ FuzzedDataProvider data) {
        // Test code here
    }
}
"""
    # Test case 4: Method with line continuation
    line_continuation_java = """
import com.code_intelligence.jazzer.api.FuzzedDataProvider;
import com.code_intelligence.jazzer.junit.FuzzTest;

public class LineContinuationFuzzer {
    @FuzzTest
    public void fuzzerTestOneInput(\
        FuzzedDataProvider data\
    ) {
        // Test code here
    }
}
"""

    # Write test files
    (source_path / "SplitAnnotationFuzzer.java").write_text(split_annotation_java)
    (source_path / "ExtraSpacesFuzzer.java").write_text(extra_spaces_java)
    (source_path / "InlineCommentsFuzzer.java").write_text(inline_comments_java)
    (source_path / "LineContinuationFuzzer.java").write_text(line_continuation_java)

    # Find harnesses
    harnesses = find_jazzer_harnesses(challenge_task)

    # Verify results
    assert len(harnesses) == 4
    harness_paths = {h.name for h in harnesses}
    assert "SplitAnnotationFuzzer.java" in harness_paths
    assert "ExtraSpacesFuzzer.java" in harness_paths
    assert "InlineCommentsFuzzer.java" in harness_paths
    assert "LineContinuationFuzzer.java" in harness_paths
