from pathlib import Path
from buttercup.patcher.patcher import Patcher
from buttercup.common.datastructures.msg_pb2 import ConfirmedVulnerability, Crash, BuildOutput
import pytest


@pytest.fixture
def tasks_dir(tmp_path: Path) -> Path:
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

    yield tmp_path


def test_vuln_to_patch_input(tasks_dir: Path, tmp_path: Path):
    patcher = Patcher(
        task_storage_dir=tasks_dir,
        scratch_dir=tmp_path,
        redis=None,
        mock_mode=True,
    )

    vuln = ConfirmedVulnerability(
        vuln_id="test-vuln-1",
        crash=Crash(
            target=BuildOutput(
                task_id="test-task-id-1",
                package_name="libpng",
                engine="test-engine-1",
                sanitizer="test-sanitizer-1",
                output_ossfuzz_path=str(tasks_dir / "test-task-id-1" / "fuzz-tooling" / "my-oss-fuzz"),
                source_path=str(tasks_dir / "test-task-id-1" / "src" / "my-source"),
            ),
            harness_name="test-harness-name-1",
            crash_input_path="test-crash-input-path-1",
            stacktrace="test-stacktrace-1",
        ),
    )

    # Test patch generation
    patch_input = patcher._create_patch_input(vuln)

    # Verify the patch was generated
    assert patch_input is not None
    assert patch_input.task_id == "test-task-id-1"
    assert patch_input.vulnerability_id == "test-vuln-1"
    assert patch_input.project_name == "libpng"
    assert patch_input.harness_name == "test-harness-name-1"
    assert patch_input.pov == Path("test-crash-input-path-1")
    assert patch_input.sanitizer_output == "test-stacktrace-1"
    assert patch_input.engine == "test-engine-1"
    assert patch_input.sanitizer == "test-sanitizer-1"
