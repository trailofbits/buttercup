"""Tests for cross-filesystem operations in node_local module.

These tests use real filesystem operations, not mocks, to test the actual
behavior of cross-filesystem file operations.
"""

import errno
import os
import shutil
import tempfile
from pathlib import Path

import pytest

from buttercup.common.node_local import (
    _copy_and_delete,
    rename_atomically,
)


@pytest.fixture
def temp_dirs():
    """Create temporary directories for testing."""
    dir1 = tempfile.mkdtemp(prefix="test_dir1_")
    dir2 = tempfile.mkdtemp(prefix="test_dir2_")
    yield {"dir1": Path(dir1), "dir2": Path(dir2)}
    shutil.rmtree(dir1, ignore_errors=True)
    shutil.rmtree(dir2, ignore_errors=True)


class TestCopyAndDelete:
    """Tests for _copy_and_delete function."""

    def test_file(self, temp_dirs):
        """Test _copy_and_delete for files."""
        src = temp_dirs["dir1"] / "test_file.txt"
        dst = temp_dirs["dir2"] / "copied_file.txt"

        # Create source file
        src.write_bytes(b"file content")

        # Copy and delete
        result = _copy_and_delete(src, dst)

        assert result == dst
        assert dst.exists()
        assert not src.exists()
        assert dst.read_bytes() == b"file content"

    def test_directory(self, temp_dirs):
        """Test _copy_and_delete for directories."""
        src = temp_dirs["dir1"] / "test_dir"
        dst = temp_dirs["dir2"] / "copied_dir"

        # Create source directory with files
        src.mkdir()
        (src / "file1.txt").write_bytes(b"content1")
        (src / "file2.txt").write_bytes(b"content2")

        # Copy and delete
        result = _copy_and_delete(src, dst)

        assert result == dst
        assert dst.exists()
        assert not src.exists()
        assert (dst / "file1.txt").read_bytes() == b"content1"
        assert (dst / "file2.txt").read_bytes() == b"content2"

    def test_file_exists(self, temp_dirs):
        """Test _copy_and_delete when destination already exists."""
        src = temp_dirs["dir1"] / "test_file.txt"
        dst = temp_dirs["dir2"] / "existing_file.txt"

        # Create source and destination files
        src.write_bytes(b"source content")
        dst.write_bytes(b"existing content")

        # Copy and delete should skip and return None
        result = _copy_and_delete(src, dst)

        assert result is None
        # Destination should keep its original content
        assert dst.read_bytes() == b"existing content"
        # Source should be deleted
        assert not src.exists()

    def test_directory_exists(self, temp_dirs):
        """Test _copy_and_delete when destination directory already exists."""
        src = temp_dirs["dir1"] / "test_dir"
        dst = temp_dirs["dir2"] / "existing_dir"

        # Create source and destination directories
        src.mkdir()
        (src / "new_file.txt").write_bytes(b"new content")

        dst.mkdir()
        (dst / "existing_file.txt").write_bytes(b"existing content")

        # Copy and delete should skip and return None
        result = _copy_and_delete(src, dst)

        assert result is None
        # Destination should keep its original content
        assert (dst / "existing_file.txt").read_bytes() == b"existing content"
        # Source should be deleted
        assert not src.exists()


class TestRenameAtomicallyCrossFilesystem:
    """Tests for rename_atomically function with cross-filesystem scenarios."""

    def test_cross_filesystem(self, temp_dirs):
        """Test rename_atomically handles cross-filesystem via copy+delete."""
        src = temp_dirs["dir1"] / "test_file.txt"
        dst = temp_dirs["dir2"] / "renamed_file.txt"

        # Create source file
        src.write_bytes(b"test content")

        # Manually patch os.rename at runtime to simulate EXDEV
        original_rename = os.rename

        def mock_rename(s, d):
            raise OSError(errno.EXDEV, "Invalid cross-device link")

        os.rename = mock_rename
        try:
            # rename_atomically should fall back to copy+delete
            result = rename_atomically(src, dst)

            assert result == dst
            assert dst.exists()
            assert not src.exists()
            assert dst.read_bytes() == b"test content"
        finally:
            os.rename = original_rename

    def test_directory_not_empty(self, temp_dirs):
        """Test rename_atomically when directory exists (errno ENOTEMPTY)."""
        src = temp_dirs["dir1"] / "test_file.txt"
        dst = temp_dirs["dir2"] / "renamed_file.txt"

        # Create source file
        src.write_bytes(b"test content")

        # Manually patch os.rename at runtime to simulate ENOTEMPTY
        original_rename = os.rename

        def mock_rename(s, d):
            raise OSError(errno.ENOTEMPTY, "Directory not empty")

        os.rename = mock_rename
        try:
            # rename_atomically should return None
            result = rename_atomically(src, dst)

            assert result is None
        finally:
            os.rename = original_rename

    def test_cross_filesystem_directory(self, temp_dirs):
        """Test rename_atomically handles cross-filesystem for directories."""
        src = temp_dirs["dir1"] / "test_dir"
        dst = temp_dirs["dir2"] / "renamed_dir"

        # Create source directory with files
        src.mkdir()
        (src / "file1.txt").write_bytes(b"content1")
        (src / "subdir").mkdir()
        (src / "subdir" / "file2.txt").write_bytes(b"content2")

        # Manually patch os.rename at runtime to simulate EXDEV
        original_rename = os.rename

        def mock_rename(s, d):
            raise OSError(errno.EXDEV, "Invalid cross-device link")

        os.rename = mock_rename
        try:
            # rename_atomically should fall back to copy+delete
            result = rename_atomically(src, dst)

            assert result == dst
            assert dst.exists()
            assert not src.exists()
            assert (dst / "file1.txt").read_bytes() == b"content1"
            assert (dst / "subdir" / "file2.txt").read_bytes() == b"content2"
        finally:
            os.rename = original_rename
