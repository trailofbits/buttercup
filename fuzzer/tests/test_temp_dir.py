import os
import tempfile
import threading
import time
import unittest
from unittest.mock import patch, MagicMock

from buttercup.fuzzing_infra.temp_dir import get_temp_dir, patched_temp_dir, _scratch_path_var


class TestGetTempDir(unittest.TestCase):
    """Test cases for the get_temp_dir function."""

    def setUp(self):
        """Set up test fixtures."""
        # Clear any existing context variable value
        _scratch_path_var.set(None)

    def test_get_temp_dir_with_scratch_path(self):
        """Test get_temp_dir uses scratch path when available."""
        test_scratch_path = "/test/scratch/path"

        with patch("buttercup.fuzzing_infra.temp_dir.shell.create_directory") as mock_create_dir:
            # Set the context variable
            token = _scratch_path_var.set(test_scratch_path)

            try:
                result = get_temp_dir()

                # Should use scratch path as prefix
                expected_path = os.path.join(test_scratch_path, f"temp-{os.getpid()}")
                self.assertEqual(result, expected_path)
                mock_create_dir.assert_called_once_with(expected_path)
            finally:
                _scratch_path_var.reset(token)

    def test_get_temp_dir_fallback_with_fuzz_inputs_disk(self):
        """Test get_temp_dir falls back to FUZZ_INPUTS_DISK when no scratch path."""
        test_fuzz_inputs_path = "/test/fuzz/inputs"

        with (
            patch("buttercup.fuzzing_infra.temp_dir.environment.get_value") as mock_get_value,
            patch("buttercup.fuzzing_infra.temp_dir.shell.create_directory") as mock_create_dir,
        ):
            mock_get_value.return_value = test_fuzz_inputs_path

            result = get_temp_dir(use_fuzz_inputs_disk=True)

            expected_path = os.path.join(test_fuzz_inputs_path, f"temp-{os.getpid()}")
            self.assertEqual(result, expected_path)
            mock_get_value.assert_called_once_with("FUZZ_INPUTS_DISK", tempfile.gettempdir())
            mock_create_dir.assert_called_once_with(expected_path)

    def test_get_temp_dir_fallback_without_fuzz_inputs_disk(self):
        """Test get_temp_dir falls back to system temp when use_fuzz_inputs_disk=False."""
        with patch("buttercup.fuzzing_infra.temp_dir.shell.create_directory") as mock_create_dir:
            result = get_temp_dir(use_fuzz_inputs_disk=False)

            expected_path = os.path.join(tempfile.gettempdir(), f"temp-{os.getpid()}")
            self.assertEqual(result, expected_path)
            mock_create_dir.assert_called_once_with(expected_path)

    def test_get_temp_dir_fallback_to_system_temp(self):
        """Test get_temp_dir falls back to system temp when FUZZ_INPUTS_DISK not set."""
        with (
            patch("buttercup.fuzzing_infra.temp_dir.environment.get_value") as mock_get_value,
            patch("buttercup.fuzzing_infra.temp_dir.shell.create_directory") as mock_create_dir,
        ):
            # Return system temp dir when FUZZ_INPUTS_DISK is not set
            mock_get_value.return_value = tempfile.gettempdir()

            result = get_temp_dir(use_fuzz_inputs_disk=True)

            expected_path = os.path.join(tempfile.gettempdir(), f"temp-{os.getpid()}")
            self.assertEqual(result, expected_path)
            mock_create_dir.assert_called_once_with(expected_path)


class TestPatchedTempDir(unittest.TestCase):
    """Test cases for the patched_temp_dir context manager."""

    def test_patched_temp_dir_basic_functionality(self):
        """Test basic functionality of patched_temp_dir context manager."""
        with patch("buttercup.fuzzing_infra.temp_dir.scratch_dir") as mock_scratch_dir:
            # Mock scratch_dir context manager
            mock_scratch = MagicMock()
            mock_scratch.path = "/mock/scratch/path"
            mock_scratch_dir.return_value.__enter__.return_value = mock_scratch
            mock_scratch_dir.return_value.__exit__.return_value = None

            with patched_temp_dir() as scratch:
                # Verify we get the scratch directory
                self.assertEqual(scratch, mock_scratch)

                # Verify the context variable is set correctly
                self.assertEqual(_scratch_path_var.get(), "/mock/scratch/path")

    def test_patched_temp_dir_patches_clusterfuzz_function(self):
        """Test that patched_temp_dir properly patches the clusterfuzz function."""
        with patch("buttercup.fuzzing_infra.temp_dir.scratch_dir") as mock_scratch_dir:
            # Mock scratch_dir context manager
            mock_scratch = MagicMock()
            mock_scratch.path = "/mock/scratch/path"
            mock_scratch_dir.return_value.__enter__.return_value = mock_scratch
            mock_scratch_dir.return_value.__exit__.return_value = None

            # Test that the patching works by calling the function directly
            with patched_temp_dir():
                with patch("buttercup.fuzzing_infra.temp_dir.shell.create_directory") as mock_create_dir:
                    # Import and call the clusterfuzz function - it should be patched to use our implementation
                    import clusterfuzz._internal.bot.fuzzers.utils as utils

                    result = utils.get_temp_dir()

                    # Should return path using our scratch directory
                    expected_path = os.path.join("/mock/scratch/path", f"temp-{os.getpid()}")
                    self.assertEqual(result, expected_path)
                    mock_create_dir.assert_called_once_with(expected_path)

    def test_patched_temp_dir_context_variable_cleanup(self):
        """Test that context variable is properly cleaned up after context exit."""
        with patch("buttercup.fuzzing_infra.temp_dir.scratch_dir") as mock_scratch_dir:
            # Mock scratch_dir context manager
            mock_scratch = MagicMock()
            mock_scratch.path = "/mock/scratch/path"
            mock_scratch_dir.return_value.__enter__.return_value = mock_scratch
            mock_scratch_dir.return_value.__exit__.return_value = None

            # Verify context variable is None before
            self.assertIsNone(_scratch_path_var.get())

            with patched_temp_dir():
                # Verify context variable is set inside context
                self.assertEqual(_scratch_path_var.get(), "/mock/scratch/path")

            # Verify context variable is cleaned up after
            self.assertIsNone(_scratch_path_var.get())

    def test_patched_temp_dir_nested_contexts(self):
        """Test that nested patched_temp_dir contexts work correctly."""
        with patch("buttercup.fuzzing_infra.temp_dir.scratch_dir") as mock_scratch_dir:
            # Mock different scratch directories for nested contexts
            mock_scratch1 = MagicMock()
            mock_scratch1.path = "/mock/scratch/path1"
            mock_scratch2 = MagicMock()
            mock_scratch2.path = "/mock/scratch/path2"

            mock_scratch_dir.return_value.__enter__.side_effect = [mock_scratch1, mock_scratch2]
            mock_scratch_dir.return_value.__exit__.return_value = None

            with patched_temp_dir():
                self.assertEqual(_scratch_path_var.get(), "/mock/scratch/path1")

                with patched_temp_dir():
                    self.assertEqual(_scratch_path_var.get(), "/mock/scratch/path2")

                # Should restore to outer context
                self.assertEqual(_scratch_path_var.get(), "/mock/scratch/path1")

            # Should be cleaned up completely
            self.assertIsNone(_scratch_path_var.get())

    def test_patched_temp_dir_exception_handling(self):
        """Test that context variable is cleaned up even when exceptions occur."""
        with patch("buttercup.fuzzing_infra.temp_dir.scratch_dir") as mock_scratch_dir:
            mock_scratch = MagicMock()
            mock_scratch.path = "/mock/scratch/path"
            mock_scratch_dir.return_value.__enter__.return_value = mock_scratch
            mock_scratch_dir.return_value.__exit__.return_value = None

            try:
                with patched_temp_dir():
                    self.assertEqual(_scratch_path_var.get(), "/mock/scratch/path")
                    raise ValueError("Test exception")
            except ValueError:
                pass

            # Should still be cleaned up after exception
            self.assertIsNone(_scratch_path_var.get())


class TestThreadSafety(unittest.TestCase):
    """Test cases for thread safety of the temp_dir module."""

    def test_thread_safety_multiple_contexts(self):
        """Test that multiple threads can use patched_temp_dir simultaneously."""
        results = {}
        errors = []

        def thread_worker(thread_id: int):
            try:
                with patch("buttercup.fuzzing_infra.temp_dir.scratch_dir") as mock_scratch_dir:
                    mock_scratch = MagicMock()
                    mock_scratch.path = f"/mock/scratch/thread{thread_id}"
                    mock_scratch_dir.return_value.__enter__.return_value = mock_scratch
                    mock_scratch_dir.return_value.__exit__.return_value = None

                    with patched_temp_dir():
                        # Store the context variable value for this thread
                        results[thread_id] = _scratch_path_var.get()

                        # Sleep to allow other threads to run
                        time.sleep(0.1)

                        # Verify the value hasn't changed
                        if _scratch_path_var.get() != f"/mock/scratch/thread{thread_id}":
                            errors.append(f"Thread {thread_id} context variable changed!")

            except Exception as e:
                errors.append(f"Thread {thread_id} error: {e}")

        # Start multiple threads
        threads = []
        for i in range(5):
            thread = threading.Thread(target=thread_worker, args=(i,))
            threads.append(thread)
            thread.start()

        # Wait for all threads to complete
        for thread in threads:
            thread.join()

        # Verify no errors occurred
        self.assertEqual(errors, [], f"Thread safety errors: {errors}")

        # Verify each thread had its own context value
        for i in range(5):
            self.assertEqual(results[i], f"/mock/scratch/thread{i}")

        # Verify context is clean after all threads
        self.assertIsNone(_scratch_path_var.get())


if __name__ == "__main__":
    unittest.main()
