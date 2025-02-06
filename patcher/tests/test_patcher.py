from pathlib import Path
from buttercup.patcher.patcher import Patcher
from buttercup.common.datastructures.msg_pb2 import ConfirmedVulnerability, Crash, BuildOutput


def test_patcher_mock_mode_libpng():
    # Initialize patcher in mock mode
    patcher = Patcher(task_storage_dir=Path("/tmp"), redis=None, mock_mode=True)

    # Create a test vulnerability for libpng
    vuln = ConfirmedVulnerability(
        vuln_id="test-vuln-1",
        crash=Crash(
            target=BuildOutput(
                task_id="test-task-id-1",
                package_name="libpng",
                engine="test-engine-1",
                sanitizer="test-sanitizer-1",
                output_ossfuzz_path="test-output-ossfuzz-path-1",
                source_path="test-source-path-1",
            ),
            harness_name="test-harness-name-1",
            crash_input_path="test-crash-input-path-1",
        ),
    )

    # Test patch generation
    patch_input = patcher._create_patch_input(vuln)
    patch = patcher.process_vulnerability(patch_input)

    # Verify the patch was generated
    assert patch is not None
    assert patch.task_id == "test-task-id-1"
    assert patch.vulnerability_id == "test-vuln-1"
    assert "diff --git" in patch.patch  # Verify it contains the mock patch content
