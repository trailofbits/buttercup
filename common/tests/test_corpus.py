import os
import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from buttercup.common import node_local
from buttercup.common.corpus import Corpus, InputDir, _get_corpus_storage_path


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
        if self.name == "test_file_4":
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


def test_copy_corpus_only_local(temp_dir):
    """Test that copy_corpus copies only to node-local (not remote)."""
    remote_path = os.path.join(temp_dir, "remote")
    with patch("buttercup.common.node_local.remote_path", return_value=remote_path):
        input_dir = InputDir(temp_dir, "test_corpus")

        src_dir = os.path.join(temp_dir, "src_corpus")
        os.makedirs(src_dir, exist_ok=True)

        # Create a test file
        file_path = os.path.join(src_dir, "test_file")
        with open(file_path, "wb") as f:
            f.write(b"test content")

        copied_files = input_dir.copy_corpus(src_dir)

        # File should exist locally
        assert len(copied_files) == 1
        assert os.path.exists(copied_files[0])

        # Remote file should not exist
        remote_file = os.path.join(remote_path, os.path.basename(copied_files[0]))
        assert not os.path.exists(remote_file)


def test_copy_file_only_local(temp_dir):
    """Test that copy_file with only_local=True skips remote copy."""
    remote_path = os.path.join(temp_dir, "remote")
    with patch("buttercup.common.node_local.remote_path", return_value=remote_path):
        input_dir = InputDir(temp_dir, "test_corpus")

        src_dir = os.path.join(temp_dir, "src_corpus")
        os.makedirs(src_dir, exist_ok=True)

        # Create a test file
        file_path = os.path.join(src_dir, "test_file")
        with open(file_path, "wb") as f:
            f.write(b"test content")

        # Copy file with only_local=True
        dst = input_dir.copy_file(file_path, only_local=True)

        # File should exist locally
        assert os.path.exists(dst)

        # Remote file should not exist
        remote_file = os.path.join(remote_path, os.path.basename(dst))
        assert not os.path.exists(remote_file)


def test_copy_file_with_remote(temp_dir):
    """Test that copy_file with only_local=False copies to both local and remote."""
    remote_path = os.path.join(temp_dir, "remote")
    with patch("buttercup.common.node_local.remote_path", return_value=remote_path):
        input_dir = InputDir(temp_dir, "test_corpus")

        src_dir = os.path.join(temp_dir, "src_corpus")
        os.makedirs(src_dir, exist_ok=True)

        # Create a test file
        file_path = os.path.join(src_dir, "test_file")
        with open(file_path, "wb") as f:
            f.write(b"test content")

        # Copy file with only_local=False (explicit)
        dst = input_dir.copy_file(file_path, only_local=False)

        # File should exist locally
        assert os.path.exists(dst)

        # Same file should exist in remote
        remote_file = os.path.join(remote_path, os.path.basename(dst))
        assert os.path.exists(remote_file)


# ============================================================================
# Tests for tmpfs corpus functionality
# ============================================================================


@pytest.fixture
def tmpfs_temp_dirs():
    """Create separate temp directories for node_data, tmpfs, and remote storage."""
    node_data_dir = tempfile.mkdtemp(prefix="node_data_")
    tmpfs_dir = tempfile.mkdtemp(prefix="tmpfs_")
    yield {"node_data": node_data_dir, "tmpfs": tmpfs_dir}
    shutil.rmtree(node_data_dir, ignore_errors=True)
    shutil.rmtree(tmpfs_dir, ignore_errors=True)


class TestTmpfsCorpusConfiguration:
    """Tests for tmpfs corpus configuration functions."""

    def test_is_corpus_tmpfs_enabled_when_not_set(self):
        """Test that tmpfs is disabled when env var is not set."""
        with patch.object(node_local, "corpus_tmpfs_path", None):
            assert node_local.is_corpus_tmpfs_enabled() is False

    def test_is_corpus_tmpfs_enabled_when_set(self):
        """Test that tmpfs is enabled when env var is set."""
        with patch.object(node_local, "corpus_tmpfs_path", "/tmp/corpus"):
            assert node_local.is_corpus_tmpfs_enabled() is True

    def test_get_corpus_tmpfs_path_when_not_set(self):
        """Test that get_corpus_tmpfs_path returns None when not configured."""
        with patch.object(node_local, "corpus_tmpfs_path", None):
            assert node_local.get_corpus_tmpfs_path() is None

    def test_get_corpus_tmpfs_path_when_set(self):
        """Test that get_corpus_tmpfs_path returns the configured path."""
        with patch.object(node_local, "corpus_tmpfs_path", "/tmp/corpus"):
            assert node_local.get_corpus_tmpfs_path() == Path("/tmp/corpus")


class TestCorpusTmpfsStorage:
    """Tests for corpus storage using tmpfs."""

    def test_corpus_uses_standard_path_when_tmpfs_disabled(self, tmpfs_temp_dirs):
        """Test that Corpus uses standard node-local path when tmpfs is disabled."""
        node_data = tmpfs_temp_dirs["node_data"]
        remote_path = Path(tmpfs_temp_dirs["node_data"]) / "remote"

        with patch.object(node_local, "corpus_tmpfs_path", None):
            with patch.object(node_local, "node_local_path", node_data):
                with patch("buttercup.common.node_local.remote_path", return_value=remote_path):
                    corpus = Corpus(node_data, "test_task", "test_harness")

                    # Corpus should be stored under node_data
                    assert corpus.path.startswith(node_data)
                    assert "test_task" in corpus.path
                    assert "buttercup_corpus_test_harness" in corpus.path

    def test_corpus_uses_tmpfs_path_when_enabled(self, tmpfs_temp_dirs):
        """Test that Corpus uses tmpfs path when tmpfs is enabled."""
        node_data = tmpfs_temp_dirs["node_data"]
        tmpfs = tmpfs_temp_dirs["tmpfs"]
        remote_path = Path("/") / "test_task" / "buttercup_corpus_test_harness"

        with patch.object(node_local, "corpus_tmpfs_path", tmpfs):
            with patch.object(node_local, "node_local_path", node_data):
                with patch("buttercup.common.node_local.remote_path", return_value=remote_path):
                    corpus = Corpus(node_data, "test_task", "test_harness")

                    # Corpus should be stored under tmpfs
                    assert corpus.path.startswith(tmpfs)
                    assert "test_task" in corpus.path
                    assert "buttercup_corpus_test_harness" in corpus.path

    def test_corpus_remote_path_unchanged_with_tmpfs(self, tmpfs_temp_dirs):
        """Test that remote path is calculated correctly regardless of tmpfs setting."""
        node_data = tmpfs_temp_dirs["node_data"]
        tmpfs = tmpfs_temp_dirs["tmpfs"]

        # The remote path should be calculated based on node_data structure, not tmpfs
        expected_remote = Path("/") / "test_task" / "buttercup_corpus_test_harness"

        with patch.object(node_local, "corpus_tmpfs_path", tmpfs):
            with patch.object(node_local, "node_local_path", node_data):
                local_path, remote_path = _get_corpus_storage_path(node_data, "test_task/buttercup_corpus_test_harness")

                # Local should use tmpfs
                assert tmpfs in local_path

                # Remote should be calculated from node_data structure
                assert remote_path == expected_remote

    def test_corpus_file_operations_with_tmpfs(self, tmpfs_temp_dirs):
        """Test that corpus file operations work correctly with tmpfs."""
        node_data = tmpfs_temp_dirs["node_data"]
        tmpfs = tmpfs_temp_dirs["tmpfs"]
        remote_path = Path(node_data) / "remote" / "test_task" / "buttercup_corpus_test_harness"

        with patch.object(node_local, "corpus_tmpfs_path", tmpfs):
            with patch.object(node_local, "node_local_path", node_data):
                with patch("buttercup.common.node_local.remote_path", return_value=remote_path):
                    corpus = Corpus(node_data, "test_task", "test_harness")

                    # Create a source directory with test files
                    src_dir = os.path.join(tmpfs_temp_dirs["node_data"], "src")
                    os.makedirs(src_dir, exist_ok=True)

                    # Create test files
                    for i in range(3):
                        file_path = os.path.join(src_dir, f"file_{i}")
                        with open(file_path, "wb") as f:
                            f.write(f"content_{i}".encode())

                    # Copy files to corpus (should be on tmpfs)
                    copied = corpus.copy_corpus(src_dir)

                    assert len(copied) == 3
                    assert corpus.local_corpus_count() == 3

                    # Verify files are on tmpfs
                    for copied_file in copied:
                        assert tmpfs in copied_file
                        assert os.path.exists(copied_file)


class TestGetCorpusStoragePath:
    """Tests for the _get_corpus_storage_path function."""

    def test_standard_path_when_tmpfs_disabled(self, tmpfs_temp_dirs):
        """Test standard path calculation when tmpfs is disabled."""
        node_data = tmpfs_temp_dirs["node_data"]

        with patch.object(node_local, "corpus_tmpfs_path", None):
            with patch.object(node_local, "node_local_path", node_data):
                local_path, remote_path = _get_corpus_storage_path(node_data, "task/corpus")

                assert local_path == os.path.join(node_data, "task/corpus")
                assert remote_path == Path("/task/corpus")

    def test_tmpfs_path_when_enabled(self, tmpfs_temp_dirs):
        """Test tmpfs path calculation when enabled."""
        node_data = tmpfs_temp_dirs["node_data"]
        tmpfs = tmpfs_temp_dirs["tmpfs"]

        with patch.object(node_local, "corpus_tmpfs_path", tmpfs):
            with patch.object(node_local, "node_local_path", node_data):
                local_path, remote_path = _get_corpus_storage_path(node_data, "task/corpus")

                # Local path should use tmpfs
                assert local_path == os.path.join(tmpfs, "task/corpus")
                # Remote path should still be calculated from node_data structure
                assert remote_path == Path("/task/corpus")


class TestCrossFilesystemOperations:
    """Tests for cross-filesystem file operations."""

    def test_hash_corpus_with_shutil_move(self, temp_dir, mock_node_local):
        """Test that hash_corpus works correctly (uses shutil.move internally)."""
        input_dir = InputDir(temp_dir, "test_corpus")

        # Create files with non-hash names
        test_files = ["file_a.txt", "file_b.txt", "file_c.txt"]
        for name in test_files:
            file_path = os.path.join(input_dir.path, name)
            with open(file_path, "wb") as f:
                f.write(f"content of {name}".encode())

        # Hash the corpus
        hashed = InputDir.hash_corpus(input_dir.path)

        # Should have hashed all 3 files
        assert len(hashed) == 3

        # All files should now have hash names (64 hex chars)
        for file in os.listdir(input_dir.path):
            assert InputDir.has_hashed_name(file)

    def test_hash_corpus_skips_already_hashed(self, temp_dir, mock_node_local):
        """Test that hash_corpus skips files that are already hashed."""
        input_dir = InputDir(temp_dir, "test_corpus")

        # Create a file with a hash name (64 hex chars)
        hash_name = "a" * 64
        hash_file_path = os.path.join(input_dir.path, hash_name)
        with open(hash_file_path, "wb") as f:
            f.write(b"already hashed content")

        # Create a non-hashed file
        non_hash_path = os.path.join(input_dir.path, "not_hashed.txt")
        with open(non_hash_path, "wb") as f:
            f.write(b"not hashed content")

        # Hash the corpus
        hashed = InputDir.hash_corpus(input_dir.path)

        # Should only hash the non-hashed file
        assert len(hashed) == 1
        assert hash_name not in hashed

        # The pre-existing hash file should still exist with same name
        assert os.path.exists(hash_file_path)


class TestInputDirOverrides:
    """Tests for InputDir with override parameters."""

    def test_input_dir_with_override_local_path(self, temp_dir):
        """Test InputDir with override_local_path parameter."""
        custom_local = os.path.join(temp_dir, "custom_local")
        remote_path = Path(temp_dir) / "remote"

        with patch("buttercup.common.node_local.remote_path", return_value=remote_path):
            input_dir = InputDir(
                temp_dir,
                "test_corpus",
                override_local_path=custom_local,
            )

            assert input_dir.path == custom_local
            assert os.path.exists(custom_local)

    def test_input_dir_with_override_remote_path(self, temp_dir):
        """Test InputDir with override_remote_path parameter."""
        custom_remote = Path("/custom/remote/path")

        # Need to still patch the default remote_path call
        with patch("buttercup.common.node_local.remote_path", return_value=Path("/default")):
            input_dir = InputDir(
                temp_dir,
                "test_corpus",
                override_remote_path=custom_remote,
            )

            assert input_dir.remote_path == custom_remote

    def test_input_dir_with_both_overrides(self, temp_dir):
        """Test InputDir with both override parameters."""
        custom_local = os.path.join(temp_dir, "custom_local")
        custom_remote = Path("/custom/remote")

        with patch("buttercup.common.node_local.remote_path", return_value=Path("/default")):
            input_dir = InputDir(
                temp_dir,
                "test_corpus",
                override_local_path=custom_local,
                override_remote_path=custom_remote,
            )

            assert input_dir.path == custom_local
            assert input_dir.remote_path == custom_remote
