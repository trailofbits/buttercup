from pathlib import Path
from buttercup.common.challenge_task import ChallengeTask
from buttercup.common.task_meta import TaskMeta
from buttercup.patcher.utils import find_file_in_source_dir
from buttercup.patcher.agents.config import PatcherConfig
from langchain_core.runnables import RunnableConfig
from unittest.mock import patch
import subprocess
import pytest
import os


@pytest.fixture
def task_dir(tmp_path: Path) -> Path:
    """Create a mock challenge task directory structure."""
    # Create the task directory
    task_dir = tmp_path / "test-task-id-1"
    task_dir.mkdir(parents=True, exist_ok=True)

    # Create the main directories
    oss_fuzz = task_dir / "fuzz-tooling" / "my-oss-fuzz"
    source = task_dir / "src" / "my-source"
    diffs = task_dir / "diff" / "my-diff"

    oss_fuzz.mkdir(parents=True, exist_ok=True)
    source.mkdir(parents=True, exist_ok=True)
    diffs.mkdir(parents=True, exist_ok=True)

    # Create some mock patch files
    (diffs / "patch1.diff").write_text("mock patch 1")
    (diffs / "patch2.diff").write_text("mock patch 2")

    # Create a mock helper.py file
    helper_path = oss_fuzz / "infra/helper.py"
    helper_path.parent.mkdir(parents=True, exist_ok=True)
    helper_path.write_text("import sys;\nsys.exit(0)\n")

    # Create a mock test.txt file
    (source / "test.txt").write_text("mock test content")
    (source / "subdir").mkdir(parents=True, exist_ok=True)
    (source / "subdir2").mkdir(parents=True, exist_ok=True)
    (source / "subdir" / "test2.txt").write_text("mock test content 2")
    (source / "subdir" / "test.txt").write_text("mock test content 3")
    (source / "subdir" / "same_name.txt").write_text("mock test same content 1")
    (source / "subdir2" / "same_name.txt").write_text("mock test same content 2")
    (source / "d1" / "d2" / "d3").mkdir(parents=True, exist_ok=True)
    (source / "d1" / "d2" / "d3" / "test.txt").write_text("mock test content 4")

    # Create task metadata
    TaskMeta(
        project_name="example_project",
        focus="my-source",
        task_id="task-id-challenge-task",
        metadata={"task_id": "task-id-challenge-task", "round_id": "testing", "team_id": "tob"},
    ).save(task_dir)

    yield task_dir


@pytest.fixture
def tika_challenge_task_path(tmp_path: Path) -> Path:
    """Create a challenge task using a real OSS-Fuzz repository."""
    # Clone real oss-fuzz repo into temp dir
    tmp_path = tmp_path / "afc-tika"
    tmp_path.mkdir(parents=True)

    oss_fuzz_dir = tmp_path / "fuzz-tooling"
    oss_fuzz_dir.mkdir(parents=True)
    source_dir = tmp_path / "src"
    source_dir.mkdir(parents=True)

    subprocess.run(
        ["git", "-C", str(oss_fuzz_dir), "clone", "https://github.com/aixcc-finals/oss-fuzz-aixcc.git"], check=True
    )
    subprocess.run(
        [
            "git",
            "-C",
            str(oss_fuzz_dir / "oss-fuzz-aixcc"),
            "checkout",
            "challenge-state/tk-full-01",
        ],
        check=True,
    )

    tika_url = "https://github.com/aixcc-finals/afc-tika"
    subprocess.run(["git", "-C", str(source_dir), "clone", tika_url], check=True)
    subprocess.run(
        ["git", "-C", str(source_dir / "afc-tika"), "checkout", "challenges/tk-full-01"],
        check=True,
    )

    # Create task metadata
    TaskMeta(
        project_name="tika",
        focus="afc-tika",
        task_id="task-id-tika",
        metadata={"task_id": "task-id-tika", "round_id": "testing", "team_id": "tob"},
    ).save(tmp_path)

    yield tmp_path


@pytest.fixture
def tika_challenge_task(tika_challenge_task_path: Path) -> ChallengeTask:
    return ChallengeTask(
        read_only_task_dir=tika_challenge_task_path,
        local_task_dir=tika_challenge_task_path,
    )


@pytest.fixture
def mock_challenge_task(task_dir: Path) -> ChallengeTask:
    """Create a mock challenge task for testing."""
    return ChallengeTask(
        read_only_task_dir=task_dir,
        local_task_dir=task_dir,
    )


def test_find_file_in_source_dir_direct(mock_challenge_task: ChallengeTask):
    res = find_file_in_source_dir(mock_challenge_task, Path("test.txt"))
    assert res == Path("test.txt")


def test_find_file_in_source_dir_absolute(mock_challenge_task: ChallengeTask):
    res = find_file_in_source_dir(mock_challenge_task, Path("/src/example_project/test.txt"))
    assert res == Path("test.txt")


@pytest.mark.integration
def test_tika_find_file_in_source_dir(tika_challenge_task: ChallengeTask):
    res = find_file_in_source_dir(
        tika_challenge_task,
        Path(
            "/src/project-parent/tika/tika-parsers/tika-parsers-standard/tika-parsers-standard-modules/tika-parser-text-module/src/main/java/org/apache/tika/parser/csv/TextAndCSVParser.java"
        ),
    )
    assert res == Path(
        "tika-parsers/tika-parsers-standard/tika-parsers-standard-modules/tika-parser-text-module/src/main/java/org/apache/tika/parser/csv/TextAndCSVParser.java"
    )
    res = find_file_in_source_dir(
        tika_challenge_task,
        Path("/src/project-parent/tika/tika-core/src/main/java/org/apache/tika/fork/ContentHandlerResource.java"),
    )
    assert res == Path("tika-core/src/main/java/org/apache/tika/fork/ContentHandlerResource.java")
    res = find_file_in_source_dir(
        tika_challenge_task,
        Path("/src/project-parent/tika/tika-xmp/src/main/java/org/apache/tika/xmp/convert/GenericConverter.java"),
    )
    assert res == Path("tika-xmp/src/main/java/org/apache/tika/xmp/convert/GenericConverter.java")

    res = find_file_in_source_dir(tika_challenge_task, Path("/src/project-parent/mod/not-found/file.java"))
    assert res is None
    res = find_file_in_source_dir(tika_challenge_task, Path("/src/project-parent/GenericConverter.java"))
    assert res is None
    res = find_file_in_source_dir(
        tika_challenge_task,
        Path(
            "/src/project-parent/tika/tika-xmp/src/main/java/org/apache/tika/xmp/convert/GenericConverterNotFound.java"
        ),
    )
    assert res is None


def test_find_file_in_source_dir_relative(mock_challenge_task: ChallengeTask):
    res = find_file_in_source_dir(mock_challenge_task, Path("src/example_project/test.txt"))
    assert res == Path("test.txt")


def test_find_file_in_source_dir_outside(mock_challenge_task: ChallengeTask):
    res = find_file_in_source_dir(mock_challenge_task, Path("/var/lib/fuzz_vuln.c"))
    assert res is None
    res = find_file_in_source_dir(mock_challenge_task, Path("/src/extra_folder/fuzz_vuln.c"))
    assert res is None
    res = find_file_in_source_dir(mock_challenge_task, Path("/src/fuzz_vuln.c"))
    assert res is None


def test_find_file_in_source_dir_relative_subdir(mock_challenge_task: ChallengeTask):
    res = find_file_in_source_dir(mock_challenge_task, Path("src/example_project/subdir/test.txt"))
    assert res == Path("subdir/test.txt")
    res = find_file_in_source_dir(mock_challenge_task, Path("/src/example_project/subdir/test.txt"))
    assert res == Path("subdir/test.txt")


def test_find_file_fuzzy_search(mock_challenge_task: ChallengeTask):
    res = find_file_in_source_dir(mock_challenge_task, Path("test2.txt"))
    assert res == Path("subdir/test2.txt")

    res = find_file_in_source_dir(mock_challenge_task, Path("d2/d3/test.txt"))
    assert res == Path("d1/d2/d3/test.txt")

    # The path is wrong, we don't want to match this
    res = find_file_in_source_dir(mock_challenge_task, Path("d3/d2/test.txt"))
    assert res is None

    # The path is wrong, we don't want to match this
    res = find_file_in_source_dir(mock_challenge_task, Path("d2/d3/test-nonexistent.txt"))
    assert res is None


def test_config_from_env():
    """Test that PatcherConfig correctly reads from environment variables"""
    runnable_config = RunnableConfig(
        configurable={
            "work_dir": Path("/tmp/work"),
            "tasks_storage": Path("/tmp/tasks"),
        }
    )
    config = PatcherConfig.from_configurable(runnable_config)
    assert config.ctx_retriever_recursion_limit == 80
    assert config.max_patch_retries == 10

    with patch.dict(os.environ, {"TOB_PATCHER_CTX_RETRIEVER_RECURSION_LIMIT": "200"}):
        config = PatcherConfig.from_configurable(runnable_config)
        assert config.ctx_retriever_recursion_limit == 200
        assert config.max_patch_retries == 10

    with patch.dict(os.environ, {"TOB_PATCHER_MAX_PATCH_RETRIES": "1234"}):
        config = PatcherConfig.from_configurable(runnable_config)
        assert config.max_patch_retries == 1234

    with patch.dict(os.environ, {"TOB_PATCHER_MAX_MINUTES_RUN_POVS": "333"}):
        config = PatcherConfig.from_configurable(runnable_config)
        assert config.max_minutes_run_povs == 333
