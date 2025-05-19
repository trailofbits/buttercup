import pytest
import os
import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch
from buttercup.common.corpus import InputDir


@pytest.fixture
def temp_dir():
    """Create a temporary directory for testing."""
    tmp_dir = tempfile.mkdtemp()
    yield tmp_dir
    shutil.rmtree(tmp_dir)


@pytest.fixture
def mock_node_local():
    """Mock node_local dependencies."""
    with patch("buttercup.common.node_local.node_local_path", "/test/node/data"):
        with patch("buttercup.common.node_local.remote_path", return_value="/remote/path"):
            yield


def test_local_corpus_size_handles_exceptions(temp_dir, mock_node_local):
    """Test that local_corpus_size can handle files that are deleted/renamed while iterating."""
    # Create an InputDir
    input_dir = InputDir(temp_dir, "test_corpus")

    # Create several test files in the corpus
    for i in range(5):
        file_path = os.path.join(input_dir.path, f"test_file_{i}")
        with open(file_path, "wb") as f:
            # Each file is 1KB
            f.write(b"x" * 1024)

    # Set up our mock for Path.lstat
    original_lstat = Path.lstat

    def mock_lstat(self):
        # Raise exception for specific files to simulate deletion/renaming
        if self.name in ["test_file_3", "test_file_4"]:
            raise FileNotFoundError(f"Simulated file deletion for {self.name}")
        return original_lstat(self)

    # Apply the mock to Path.lstat
    with patch.object(Path, "lstat", mock_lstat):
        # Call local_corpus_size which should handle the exceptions gracefully
        total_size = input_dir.local_corpus_size()

    # The size should be equal to the size of the first 3 files (3 * 1024 = 3072)
    assert total_size == 3 * 1024

    # Verify that all 5 files still exist physically
    assert len(os.listdir(input_dir.path)) == 5


def test_local_corpus_size_with_mixed_exceptions(temp_dir, mock_node_local):
    """Test that local_corpus_size can handle various exceptions during iteration."""
    # Create an InputDir
    input_dir = InputDir(temp_dir, "test_corpus")

    # Create several test files in the corpus with different sizes
    for i in range(5):
        file_path = os.path.join(input_dir.path, f"test_file_{i}")
        with open(file_path, "wb") as f:
            # Files of increasing size
            f.write(b"x" * (1024 * (i + 1)))

    # Set up our mock for Path.lstat
    original_lstat = Path.lstat
    call_count = {}

    def mock_lstat(self):
        # Keep track of how many times each file is accessed
        call_count[self.name] = call_count.get(self.name, 0) + 1

        # test_file_2 will fail the first time but succeed on any subsequent attempts
        if self.name == "test_file_2" and call_count[self.name] == 1:
            raise FileNotFoundError(f"Simulated transient error for {self.name}")
        # test_file_4 will always fail
        elif self.name == "test_file_4":
            raise PermissionError(f"Simulated permission error for {self.name}")
        # Other files work normally
        return original_lstat(self)

    # Apply the mock to Path.lstat
    with patch.object(Path, "lstat", mock_lstat):
        # Call local_corpus_size which should handle the exceptions gracefully
        total_size = input_dir.local_corpus_size()

    # Expected size: test_file_0 (1*1024) + test_file_1 (2*1024) + test_file_3 (4*1024) = 7*1024
    # test_file_2 fails first time, test_file_4 always fails
    expected_size = 7 * 1024
    assert total_size == expected_size
