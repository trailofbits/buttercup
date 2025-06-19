"""Tests for finding libfuzzer and jazzer harnesses in source code."""

import subprocess
import tempfile
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from redis import Redis

import buttercup.seed_gen.find_harness
from buttercup.common.challenge_task import ChallengeTask
from buttercup.common.maps import FunctionCoverage
from buttercup.common.task_meta import TaskMeta
from buttercup.program_model.codequery import CONTAINER_SRC_DIR, CodeQuery
from buttercup.seed_gen.find_harness import (
    find_jazzer_harnesses,
    find_libfuzzer_harnesses,
    get_harness_source,
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

FUZZ_TARGET_CPP_1 = """
#include <stddef.h>
#include <stdint.h>

extern "C" int LLVMFuzzerTestOneInput(const uint8_t* data, size_t size) {
    // Test code here
    return 1;
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
    task_dir = tmp_path / "task-dir"
    oss_fuzz = task_dir / "fuzz-tooling" / "my-oss-fuzz"
    source = task_dir / "src" / "my-source"
    diffs = task_dir / "diff" / "my-diff"

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
    project_yaml_path.write_text("language: c\n")
    # Create task metadata
    TaskMeta(
        project_name=project_name,
        focus="my-source",
        task_id="task-id-challenge-task",
        metadata={"task_id": "task-id-challenge-task", "round_id": "testing", "team_id": "tob"},
    ).save(task_dir)

    return task_dir


@pytest.fixture
def challenge_task(task_dir: Path) -> ChallengeTask:
    """Create a mock challenge task for testing."""
    return ChallengeTask(
        read_only_task_dir=task_dir,
        local_task_dir=task_dir,
    )


@pytest.fixture
def codequery(challenge_task: ChallengeTask) -> CodeQuery:
    """Create a mock codequery for testing."""
    with patch.object(CodeQuery, "_create_codequery_db"):
        return CodeQuery(
            challenge=challenge_task,
        )


def test_find_libfuzzer_harnesses(codequery: CodeQuery):
    """Test finding libfuzzer harnesses in source code."""
    source_path = codequery.challenge.task_dir / CONTAINER_SRC_DIR
    subdir = source_path / "subdir"
    subdir.mkdir(parents=True, exist_ok=True)

    (source_path / "fuzz_target.cpp").write_text(FUZZ_TARGET_CPP)
    (source_path / "another_fuzzer.c").write_text(FUZZ_TARGET_CPP)
    (source_path / "normal.cpp").write_text(NORMAL_CPP)
    (subdir / "FuzzTarget.java").write_text(FUZZ_TARGET_JAVA)
    (source_path / "multiline_fuzzer.cpp").write_text(MULTILINE_FUZZER_CPP)

    # Find harnesses
    harnesses = find_libfuzzer_harnesses(codequery)

    # Verify results
    assert len(harnesses) == 3
    harness_paths = {h.name for h in harnesses}
    assert "fuzz_target.cpp" in harness_paths
    assert "another_fuzzer.c" in harness_paths
    assert "multiline_fuzzer.cpp" in harness_paths


def test_find_jazzer_harnesses(codequery: CodeQuery):
    """Test finding jazzer harnesses in source code."""
    source_path = codequery.challenge.task_dir / CONTAINER_SRC_DIR
    subdir = source_path / "subdir"
    subdir.mkdir(parents=True, exist_ok=True)
    (source_path / "fuzz_target.cpp").write_text(FUZZ_TARGET_CPP)
    (source_path / "normal.java").write_text(NORMAL_JAVA)
    (subdir / "FuzzTarget.java").write_text(FUZZ_TARGET_JAVA)
    (source_path / "MultilineFuzzer.java").write_text(MULTILINE_FUZZER_JAVA)
    # Find harnesses
    harnesses = find_jazzer_harnesses(codequery)

    # Verify results
    assert len(harnesses) == 2
    harness_paths = {h.name for h in harnesses}
    assert "FuzzTarget.java" in harness_paths
    assert "MultilineFuzzer.java" in harness_paths


def test_find_harnesses_with_comments(codequery: CodeQuery):
    """Test finding harnesses when the target string appears in comments."""
    source_path = codequery.challenge.task_dir / CONTAINER_SRC_DIR
    source_path.mkdir(parents=True, exist_ok=True)

    # Create files with target strings in comments
    (source_path / "commented.cpp").write_text(NORMAL_CPP_WITH_COMMENT)
    (source_path / "commented.java").write_text(NORMAL_JAVA_WITH_COMMENT)

    # Find harnesses
    libfuzzer_harnesses = find_libfuzzer_harnesses(codequery)
    jazzer_harnesses = find_jazzer_harnesses(codequery)

    # Verify results - should not match since strings are in comments
    assert len(libfuzzer_harnesses) == 0
    assert len(jazzer_harnesses) == 0


def test_find_harnesses_in_oss_fuzz_project(codequery: CodeQuery):
    """Test finding harnesses when they are in the oss-fuzz project directory."""
    source_path = codequery.challenge.task_dir / CONTAINER_SRC_DIR
    oss_fuzz_path = codequery.challenge.task_dir / "fuzz-tooling/my-oss-fuzz/projects/my-project"

    source_path.mkdir(parents=True, exist_ok=True)
    oss_fuzz_path.mkdir(parents=True, exist_ok=True)

    # Create files with target strings in comments
    (oss_fuzz_path / "fuzz_target.cpp").write_text(FUZZ_TARGET_CPP)
    (source_path / "fuzz_target1.cpp").write_text(FUZZ_TARGET_CPP)
    (oss_fuzz_path / "FuzzTarget.java").write_text(FUZZ_TARGET_JAVA)

    # Find harnesses
    libfuzzer_harnesses = find_libfuzzer_harnesses(codequery)
    jazzer_harnesses = find_jazzer_harnesses(codequery)

    # Only expect harnesses from container_src_dir
    assert len(libfuzzer_harnesses) == 1
    assert "fuzz_target1.cpp" in {h.name for h in libfuzzer_harnesses}
    assert len(jazzer_harnesses) == 0  # No Java harnesses in container_src_dir


def test_get_harness_source_candidates_cpp(codequery: CodeQuery):
    """Test getting harness source candidates for C++ project."""
    source_path = codequery.challenge.task_dir / CONTAINER_SRC_DIR
    project_yaml_path = (
        codequery.challenge.task_dir / "fuzz-tooling/my-oss-fuzz/projects/my-project/project.yaml"
    )

    source_path.mkdir(parents=True, exist_ok=True)
    project_yaml_path.parent.mkdir(parents=True, exist_ok=True)
    project_yaml_path.write_text("language: cpp\n")

    # Create test files
    (source_path / "fuzz_target.cpp").write_text(FUZZ_TARGET_CPP)
    (source_path / "another_fuzzer.c").write_text(FUZZ_TARGET_CPP)
    (source_path / "normal.cpp").write_text(NORMAL_CPP)
    (source_path / "FuzzTarget.java").write_text(FUZZ_TARGET_JAVA)

    # Test one candidate is similar
    candidates = get_harness_source_candidates(codequery, "fuzz_target")
    candidate_names = [c.name for c in candidates]
    assert candidate_names == ["fuzz_target.cpp", "another_fuzzer.c"]

    # Test case-insensitive candidate is similar
    candidates = get_harness_source_candidates(codequery, "AnotherFuzzer")
    candidate_names = [c.name for c in candidates]
    assert candidate_names == ["another_fuzzer.c", "fuzz_target.cpp"]

    # Test no match
    candidates = get_harness_source_candidates(codequery, "nonexistent")
    assert len(candidates) == 2
    assert "another_fuzzer.c" in candidate_names
    assert "fuzz_target.cpp" in candidate_names


def test_get_harness_source_cpp(codequery: CodeQuery):
    source_path = codequery.challenge.task_dir / CONTAINER_SRC_DIR
    source_path.joinpath("src").mkdir(parents=True, exist_ok=True)
    project_yaml_path = (
        codequery.challenge.task_dir / "fuzz-tooling/my-oss-fuzz/projects/my-project/project.yaml"
    )

    source_path.mkdir(parents=True, exist_ok=True)
    project_yaml_path.parent.mkdir(parents=True, exist_ok=True)
    project_yaml_path.write_text("language: cpp\n")

    # Create test files
    (source_path / "src/fuzz_target.cpp").write_text(FUZZ_TARGET_CPP)
    (source_path / "src/normal.cpp").write_text(NORMAL_CPP)
    (source_path / "src/FuzzTarget.java").write_text(FUZZ_TARGET_JAVA)

    redis = MagicMock(spec=Redis)
    with patch("buttercup.seed_gen.find_harness.CoverageMap") as coverage_map:
        harness_name = "fuzz_target"
        harness_info = get_harness_source(redis, codequery, harness_name)
        assert harness_info.code == FUZZ_TARGET_CPP
        assert harness_info.file_path == Path("/src/fuzz_target.cpp")
        assert harness_info.harness_name == harness_name

        coverage_map.assert_not_called()

        another_harness_name = "AnotherFuzzer"
        (source_path / "src/another_fuzzer.c").write_text(FUZZ_TARGET_CPP)
        harness_info = get_harness_source(redis, codequery, another_harness_name)
        assert harness_info.code == FUZZ_TARGET_CPP
        assert harness_info.file_path == Path("/src/another_fuzzer.c")
        assert harness_info.harness_name == another_harness_name

        coverage_map.assert_called_once()


def test_get_harness_source_cpp_with_coverage_map(codequery: CodeQuery):
    source_path = codequery.challenge.task_dir / CONTAINER_SRC_DIR
    source_path.joinpath("src").mkdir(parents=True, exist_ok=True)

    # Create test files
    (source_path / "src/curl_common_fuzz.cpp").write_text(FUZZ_TARGET_CPP)
    (source_path / "src/bufq.c").write_text(FUZZ_TARGET_CPP_1)

    redis = MagicMock(spec=Redis)
    with patch("buttercup.seed_gen.find_harness.CoverageMap") as coverage_map:

        def side_effect(*args, **kwargs):
            mock = MagicMock()
            if args[1] == "curl_common_fuzz_https":
                mock.list_function_coverage.return_value = [
                    FunctionCoverage(
                        function_name="curl_common_fuzz_https",
                        function_paths=["/src/curl_common_fuzz.cpp"],
                    ),
                    FunctionCoverage(
                        function_name="strlen",
                        function_paths=["/src/glib/gstrfuncs.c"],
                    ),
                ]
            else:
                mock.list_function_coverage.return_value = [
                    FunctionCoverage(
                        function_name="curl_common_bufq",
                        function_paths=["/src/bufq.c"],
                    ),
                    FunctionCoverage(
                        function_name="myfunc",
                        function_paths=["/src/curl/something.c"],
                    ),
                ]
            return mock

        coverage_map.side_effect = side_effect

        harness_info = get_harness_source(redis, codequery, "curl_common_fuzz_https")
        assert harness_info.code == FUZZ_TARGET_CPP
        assert harness_info.file_path == Path("/src/curl_common_fuzz.cpp")
        assert harness_info.harness_name == "curl_common_fuzz_https"

        harness_info = get_harness_source(redis, codequery, "curl_common_bufq")
        assert harness_info.code == FUZZ_TARGET_CPP_1
        assert harness_info.file_path == Path("/src/bufq.c")
        assert harness_info.harness_name == "curl_common_bufq"


def test_get_harness_source_candidates_java(codequery: CodeQuery):
    """Test getting harness source candidates for Java project."""
    source_path = codequery.challenge.task_dir / CONTAINER_SRC_DIR
    project_yaml_path = (
        codequery.challenge.task_dir / "fuzz-tooling/my-oss-fuzz/projects/my-project/project.yaml"
    )

    source_path.mkdir(parents=True, exist_ok=True)
    project_yaml_path.parent.mkdir(parents=True, exist_ok=True)
    project_yaml_path.write_text("language: jvm\n")

    # Create test files
    (source_path / "fuzztarget.cpp").write_text(FUZZ_TARGET_CPP)
    (source_path / "another_fuzzer.c").write_text(FUZZ_TARGET_CPP)
    (source_path / "FuzzTarget.java").write_text(FUZZ_TARGET_JAVA)
    (source_path / "FuzzTarget1.java").write_text(FUZZ_TARGET_JAVA)

    # Test one candidate is similar
    candidates = get_harness_source_candidates(codequery, "FuzzTarget")
    candidate_names = [c.name for c in candidates]
    assert candidate_names == ["FuzzTarget.java", "FuzzTarget1.java"]

    # Test case-insensitive candidate is similar
    candidates = get_harness_source_candidates(codequery, "fuzztarget1")
    candidate_names = [c.name for c in candidates]
    assert candidate_names == ["FuzzTarget1.java", "FuzzTarget.java"]

    # Test no match
    candidates = get_harness_source_candidates(codequery, "nonexistent")
    assert len(candidates) == 2
    assert "FuzzTarget.java" in candidate_names
    assert "FuzzTarget1.java" in candidate_names


def test_weird_libfuzzer_harnesses(codequery: CodeQuery):
    """Test finding libfuzzer harnesses with unusual but valid signatures."""
    source_path = codequery.challenge.task_dir / CONTAINER_SRC_DIR
    source_path.mkdir(parents=True, exist_ok=True)

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
    harnesses = find_libfuzzer_harnesses(codequery)

    # Verify results
    assert len(harnesses) == 4
    harness_paths = {h.name for h in harnesses}
    assert "weird_signature.cpp" in harness_paths
    assert "extra_spaces.cpp" in harness_paths
    assert "commented_params.cpp" in harness_paths
    assert "line_continuation.cpp" in harness_paths


def test_weird_jazzer_harnesses(codequery: CodeQuery):
    """Test finding jazzer harnesses with unusual but valid signatures."""
    source_path = codequery.challenge.task_dir / CONTAINER_SRC_DIR
    source_path.mkdir(parents=True, exist_ok=True)

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
    harnesses = find_jazzer_harnesses(codequery)

    # Verify results
    assert len(harnesses) == 4
    harness_paths = {h.name for h in harnesses}
    assert "SplitAnnotationFuzzer.java" in harness_paths
    assert "ExtraSpacesFuzzer.java" in harness_paths
    assert "InlineCommentsFuzzer.java" in harness_paths
    assert "LineContinuationFuzzer.java" in harness_paths


@pytest.fixture(scope="module")
def curl_oss_fuzz_ct() -> Iterator[ChallengeTask]:
    # Clone real oss-fuzz repo into temp dir
    with tempfile.TemporaryDirectory() as td:
        tmp_path = Path(td)
        tmp_path = tmp_path / "curl-oss-fuzz"
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
        # Restore curl project directory to specific commit
        cmd = [
            "git",
            "-C",
            str(oss_fuzz_dir / "oss-fuzz-aixcc"),
            "checkout",
            "challenge-state/cu-full-01",
        ]
        subprocess.run(cmd, check=True)

        # Download curl source code
        curl_url = "git@github.com:aixcc-finals/afc-curl.git"
        focus = "afc-curl"
        # Checkout specific curl commit for reproducibility
        subprocess.run(["git", "-C", str(source_dir), "clone", curl_url], check=True)
        subprocess.run(
            ["git", "-C", str(source_dir / focus), "checkout", "challenges/cu-full-01"],
            check=True,
        )

        # Create task metadata
        TaskMeta(
            project_name="curl",
            focus=focus,
            task_id="task-id-curl",
            metadata={"task_id": "task-id-curl", "round_id": "testing", "team_id": "tob"},
        ).save(tmp_path)

        yield ChallengeTask(
            read_only_task_dir=tmp_path,
            local_task_dir=tmp_path,
        )


@pytest.fixture(scope="module")
def curl_oss_fuzz_cq(curl_oss_fuzz_ct: ChallengeTask) -> Iterator[CodeQuery]:
    yield CodeQuery(challenge=curl_oss_fuzz_ct)


@pytest.mark.integration
def test_find_harness_in_curl(curl_oss_fuzz_cq: CodeQuery):
    harnesses = find_libfuzzer_harnesses(curl_oss_fuzz_cq)
    assert len(harnesses) == 8
    assert "curl_fuzzer.cc" in {h.name for h in harnesses}
    assert "fuzz_url.cc" in {h.name for h in harnesses}
    assert "fuzz_bufq.cc" in {h.name for h in harnesses}
    assert "fuzz_fnmatch.cc" in {h.name for h in harnesses}
    # nghttp2 harnesses
    assert "fuzz_target_fdp.cc" in {h.name for h in harnesses}
    assert "fuzz_frames.cc" in {h.name for h in harnesses}
    assert "fuzz_target.cc" in {h.name for h in harnesses}
    # openssl harnesses
    assert "driver.c" in {h.name for h in harnesses}


@pytest.mark.integration
@pytest.mark.parametrize(
    "harness_name,expected_first_match",
    [
        ("curl_fuzzer_https", "curl_fuzzer.cc"),
        ("curl_fuzzer_ftp", "curl_fuzzer.cc"),
        ("curl_fuzzer_tftp", "curl_fuzzer.cc"),
        ("curl_fuzzer_rtsp", "curl_fuzzer.cc"),
        ("curl_fuzzer", "curl_fuzzer.cc"),
        ("curl_fuzzer_pop3", "curl_fuzzer.cc"),
        ("curl_fuzzer_ws", "curl_fuzzer.cc"),
        ("curl_fuzzer_gopher", "curl_fuzzer.cc"),
        ("curl_fuzzer_dict", "curl_fuzzer.cc"),
        ("curl_fuzzer_smb", "curl_fuzzer.cc"),
        ("curl_fuzzer_mqtt", "curl_fuzzer.cc"),
        ("curl_fuzzer_smtp", "curl_fuzzer.cc"),
        ("curl_fuzzer_file", "curl_fuzzer.cc"),
        ("curl_fuzzer_imap", "curl_fuzzer.cc"),
        ("curl_fuzzer_http", "curl_fuzzer.cc"),
        ("fuzz_url", "fuzz_url.cc"),
        # These are not the actual harness source code, but they are the best matches
        ("curl_fuzzer_fnmatch", "curl_fuzzer.cc"),
        ("curl_fuzzer_bufq", "curl_fuzzer.cc"),
    ],
)
def test_get_harness_source_candidates_curl(
    curl_oss_fuzz_cq: CodeQuery, harness_name: str, expected_first_match: str
):
    harnesses = get_harness_source_candidates(curl_oss_fuzz_cq, harness_name)
    assert expected_first_match == harnesses[0].name


@pytest.mark.integration
@pytest.mark.parametrize(
    "harness_name,expected_harness_source_path,coverage_map_function_paths",
    [
        (
            "curl_fuzzer_https",
            "/src/curl_fuzzer/curl_fuzzer.cc",
            ["/src/curl_fuzzer/curl_fuzzer.cc"],
        ),
        ("curl_fuzzer_ftp", "/src/curl_fuzzer/curl_fuzzer.cc", ["/src/curl_fuzzer/curl_fuzzer.cc"]),
        (
            "curl_fuzzer_tftp",
            "/src/curl_fuzzer/curl_fuzzer.cc",
            ["/src/curl_fuzzer/curl_fuzzer.cc"],
        ),
        (
            "curl_fuzzer_rtsp",
            "/src/curl_fuzzer/curl_fuzzer.cc",
            ["/src/curl_fuzzer/curl_fuzzer.cc"],
        ),
        ("curl_fuzzer", "/src/curl_fuzzer/curl_fuzzer.cc", ["/src/curl_fuzzer/curl_fuzzer.cc"]),
        (
            "curl_fuzzer_pop3",
            "/src/curl_fuzzer/curl_fuzzer.cc",
            ["/src/curl_fuzzer/curl_fuzzer.cc"],
        ),
        ("curl_fuzzer_ws", "/src/curl_fuzzer/curl_fuzzer.cc", ["/src/curl_fuzzer/curl_fuzzer.cc"]),
        (
            "curl_fuzzer_gopher",
            "/src/curl_fuzzer/curl_fuzzer.cc",
            ["/src/curl_fuzzer/curl_fuzzer.cc"],
        ),
        (
            "curl_fuzzer_dict",
            "/src/curl_fuzzer/curl_fuzzer.cc",
            ["/src/curl_fuzzer/curl_fuzzer.cc"],
        ),
        ("curl_fuzzer_smb", "/src/curl_fuzzer/curl_fuzzer.cc", ["/src/curl_fuzzer/curl_fuzzer.cc"]),
        (
            "curl_fuzzer_mqtt",
            "/src/curl_fuzzer/curl_fuzzer.cc",
            ["/src/curl_fuzzer/curl_fuzzer.cc"],
        ),
        (
            "curl_fuzzer_smtp",
            "/src/curl_fuzzer/curl_fuzzer.cc",
            ["/src/curl_fuzzer/curl_fuzzer.cc"],
        ),
        (
            "curl_fuzzer_file",
            "/src/curl_fuzzer/curl_fuzzer.cc",
            ["/src/curl_fuzzer/curl_fuzzer.cc"],
        ),
        (
            "curl_fuzzer_imap",
            "/src/curl_fuzzer/curl_fuzzer.cc",
            ["/src/curl_fuzzer/curl_fuzzer.cc"],
        ),
        (
            "curl_fuzzer_http",
            "/src/curl_fuzzer/curl_fuzzer.cc",
            ["/src/curl_fuzzer/curl_fuzzer.cc"],
        ),
        ("fuzz_url", "/src/curl_fuzzer/fuzz_url.cc", ["/src/curl_fuzzer/fuzz_url.cc"]),
        (
            "curl_fuzzer_fnmatch",
            "/src/curl_fuzzer/fuzz_fnmatch.cc",
            ["/src/curl_fuzzer/fuzz_fnmatch.cc"],
        ),
        ("curl_fuzzer_bufq", "/src/curl_fuzzer/fuzz_bufq.cc", ["/src/curl_fuzzer/fuzz_bufq.cc"]),
        # For these we don't have coverage map, so we should return the first candidate
        ("curl_fuzzer_https", "/src/curl_fuzzer/curl_fuzzer.cc", []),
        ("curl_fuzzer_ftp", "/src/curl_fuzzer/curl_fuzzer.cc", []),
        ("curl_fuzzer_tftp", "/src/curl_fuzzer/curl_fuzzer.cc", []),
        ("curl_fuzzer_rtsp", "/src/curl_fuzzer/curl_fuzzer.cc", []),
        ("fuzz_url", "/src/curl_fuzzer/fuzz_url.cc", []),
        ("curl_fuzzer_fnmatch", "/src/curl_fuzzer/curl_fuzzer.cc", []),
        ("curl_fuzzer_bufq", "/src/curl_fuzzer/curl_fuzzer.cc", []),
        # For these we have partial coverage map, but it does not cover the harness
        ("curl_fuzzer_https", "/src/curl_fuzzer/curl_fuzzer.cc", ["/src/curl/terminal.c"]),
        ("curl_fuzzer_ftp", "/src/curl_fuzzer/curl_fuzzer.cc", ["/src/curl/terminal.c"]),
        ("curl_fuzzer_tftp", "/src/curl_fuzzer/curl_fuzzer.cc", ["/src/curl/terminal.c"]),
        ("curl_fuzzer_rtsp", "/src/curl_fuzzer/curl_fuzzer.cc", ["/src/curl/terminal.c"]),
        ("fuzz_url", "/src/curl_fuzzer/fuzz_url.cc", ["/src/curl/terminal.c"]),
        ("curl_fuzzer_fnmatch", "/src/curl_fuzzer/curl_fuzzer.cc", ["/src/curl/terminal.c"]),
        ("curl_fuzzer_bufq", "/src/curl_fuzzer/curl_fuzzer.cc", ["/src/curl/terminal.c"]),
    ],
)
def test_get_harness_source(
    curl_oss_fuzz_cq: CodeQuery,
    harness_name: str,
    expected_harness_source_path: str,
    coverage_map_function_paths: list[str],
):
    redis = MagicMock(spec=Redis)
    with patch("buttercup.seed_gen.find_harness.CoverageMap") as coverage_map:
        coverage_map_mock = MagicMock()
        coverage_map_mock.list_function_coverage.return_value = [
            FunctionCoverage(
                function_name="random_name",
                function_paths=coverage_map_function_paths,
            )
        ]
        coverage_map.return_value = coverage_map_mock

        buttercup.seed_gen.find_harness._harness_source_cache = {}

        harness_info = get_harness_source(redis, curl_oss_fuzz_cq, harness_name)
        relative_source_path = expected_harness_source_path.lstrip("/")
        actual_file = curl_oss_fuzz_cq.challenge.task_dir / CONTAINER_SRC_DIR / relative_source_path
        assert harness_info.code == actual_file.read_text()
        assert harness_info.file_path == Path("/") / relative_source_path
        assert harness_info.harness_name == harness_name
