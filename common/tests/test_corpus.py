import pytest
import os
import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch
from buttercup.common.corpus import InputDir, Corpus


@pytest.fixture
def temp_dir():
    """Create a temporary directory for testing."""
    tmp_dir = tempfile.mkdtemp()
    yield tmp_dir
    shutil.rmtree(tmp_dir)


@pytest.fixture
def mock_node_local(temp_dir):
    """Mock node_local dependencies."""
    remote_path = os.path.join(temp_dir, "remote")
    with patch("buttercup.common.node_local.node_local_path", "/test/node/data"):
        with patch("buttercup.common.node_local.remote_path", return_value=remote_path):
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


def test_input_dir_copy_corpus_with_size_limit(temp_dir, mock_node_local):
    """Test that InputDir.copy_corpus respects copy_corpus_max_size limit."""
    # Create an InputDir with a size limit of 2KB
    input_dir = InputDir(temp_dir, "test_corpus", copy_corpus_max_size=2048)

    # Create a source directory with files of different sizes
    src_dir = os.path.join(temp_dir, "src_corpus")
    os.makedirs(src_dir, exist_ok=True)

    # Create files: 1KB, 2KB, 3KB, 4KB
    file_sizes = [1024, 2048, 3072, 4096]
    for i, size in enumerate(file_sizes):
        file_path = os.path.join(src_dir, f"file_{i}")
        with open(file_path, "wb") as f:
            f.write(b"x" * size)

    # Copy corpus - should only copy files <= 2KB
    copied_files = input_dir.copy_corpus(src_dir)

    # Should only have copied 2 files (1KB and 2KB)
    assert len(copied_files) == 2
    assert input_dir.local_corpus_count() == 2


def test_input_dir_copy_corpus_no_size_limit(temp_dir, mock_node_local):
    """Test that InputDir.copy_corpus works without size limit."""
    # Create an InputDir without size limit
    input_dir = InputDir(temp_dir, "test_corpus")

    # Create a source directory with files of different sizes
    src_dir = os.path.join(temp_dir, "src_corpus")
    os.makedirs(src_dir, exist_ok=True)

    # Create files: 1KB, 2KB, 3KB, 4KB
    file_sizes = [1024, 2048, 3072, 4096]
    for i, size in enumerate(file_sizes):
        file_path = os.path.join(src_dir, f"file_{i}")
        with open(file_path, "wb") as f:
            f.write(b"x" * size)

    # Copy corpus - should copy all files
    copied_files = input_dir.copy_corpus(src_dir)

    # Should have copied all 4 files
    assert len(copied_files) == 4
    assert input_dir.local_corpus_count() == 4


def test_corpus_class_with_size_limit(temp_dir, mock_node_local):
    """Test that Corpus class properly handles copy_corpus_max_size."""
    # Create a Corpus with size limit of 1KB
    corpus = Corpus(temp_dir, "test_task", "test_harness", copy_corpus_max_size=1024)

    # Create a source directory with files
    src_dir = os.path.join(temp_dir, "src_corpus")
    os.makedirs(src_dir, exist_ok=True)

    # Create files: 512B, 1KB, 2KB
    file_sizes = [512, 1024, 2048]
    for i, size in enumerate(file_sizes):
        file_path = os.path.join(src_dir, f"file_{i}")
        with open(file_path, "wb") as f:
            f.write(b"x" * size)

    # Copy corpus - should only copy files <= 1KB
    copied_files = corpus.copy_corpus(src_dir)

    # Should only have copied 2 files (512B and 1KB)
    assert len(copied_files) == 2
    assert corpus.local_corpus_count() == 2

    # Verify the corpus attributes are set correctly
    assert corpus.task_id == "test_task"
    assert corpus.harness_name == "test_harness"
    assert corpus.copy_corpus_max_size == 1024


def test_corpus_class_no_size_limit(temp_dir, mock_node_local):
    """Test that Corpus class works without size limit."""
    # Create a Corpus without size limit
    corpus = Corpus(temp_dir, "test_task", "test_harness")

    # Create a source directory with files
    src_dir = os.path.join(temp_dir, "src_corpus")
    os.makedirs(src_dir, exist_ok=True)

    # Create files of various sizes
    file_sizes = [512, 1024, 2048, 4096]
    for i, size in enumerate(file_sizes):
        file_path = os.path.join(src_dir, f"file_{i}")
        with open(file_path, "wb") as f:
            f.write(b"x" * size)

    # Copy corpus - should copy all files
    copied_files = corpus.copy_corpus(src_dir)

    # Should have copied all 4 files
    assert len(copied_files) == 4
    assert corpus.local_corpus_count() == 4

    # Verify the corpus attributes are set correctly
    assert corpus.task_id == "test_task"
    assert corpus.harness_name == "test_harness"
    assert corpus.copy_corpus_max_size is None


def test_input_dir_copy_corpus_all_files_too_large(temp_dir, mock_node_local):
    """Test that InputDir.copy_corpus handles case where all files exceed size limit."""
    # Create an InputDir with very small size limit
    input_dir = InputDir(temp_dir, "test_corpus", copy_corpus_max_size=100)

    # Create a source directory with large files
    src_dir = os.path.join(temp_dir, "src_corpus")
    os.makedirs(src_dir, exist_ok=True)

    # Create files larger than 100 bytes
    file_sizes = [200, 500, 1000]
    for i, size in enumerate(file_sizes):
        file_path = os.path.join(src_dir, f"file_{i}")
        with open(file_path, "wb") as f:
            f.write(b"x" * size)

    # Copy corpus - should copy no files
    copied_files = input_dir.copy_corpus(src_dir)

    # Should return empty list
    assert copied_files == []
    assert input_dir.local_corpus_count() == 0
