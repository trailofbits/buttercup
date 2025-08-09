import os
import tempfile
import unittest
from unittest.mock import patch

from buttercup.common.clusterfuzz_utils import get_fuzz_targets, EXTRA_BUILD_DIR


class TestGetFuzzTargets(unittest.TestCase):
    def setUp(self):
        # Create a temporary directory for test files
        self.test_dir = tempfile.mkdtemp()

    def tearDown(self):
        # Clean up the temporary directory after tests
        for root, _, files in os.walk(self.test_dir, topdown=False):
            for name in files:
                os.remove(os.path.join(root, name))
            os.rmdir(root)

    def create_file(self, path, content=b""):
        """Helper method to create a file with optional content"""
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(content)

    def test_find_valid_fuzz_targets(self):
        # Create some valid fuzz target files
        valid_targets = [
            os.path.join(self.test_dir, "test_fuzzer"),
            os.path.join(self.test_dir, "subdir", "another_fuzzer"),
        ]

        for target in valid_targets:
            self.create_file(target, b"LLVMFuzzerTestOneInput")

        # Create some non-fuzz target files
        self.create_file(os.path.join(self.test_dir, "regular_file"), b"normal content")

        # Get fuzz targets
        found_targets = get_fuzz_targets(self.test_dir)

        # Sort both lists for comparison
        self.assertEqual(sorted(found_targets), sorted(valid_targets))

    def test_ignore_extra_build_directory(self):
        # Create a valid fuzz target in main directory
        valid_target = os.path.join(self.test_dir, "test_fuzzer")
        self.create_file(valid_target, b"LLVMFuzzerTestOneInput")

        # Create a fuzz target in __extra_build directory
        extra_build_target = os.path.join(self.test_dir, EXTRA_BUILD_DIR, "extra_fuzzer")
        self.create_file(extra_build_target, b"LLVMFuzzerTestOneInput")

        found_targets = get_fuzz_targets(self.test_dir)

        self.assertEqual(found_targets, [valid_target])
        self.assertNotIn(extra_build_target, found_targets)

    def test_empty_directory(self):
        # Test with an empty directory
        found_targets = get_fuzz_targets(self.test_dir)
        self.assertEqual(found_targets, [])

    @patch("buttercup.common.clusterfuzz_utils.is_fuzz_target_local")
    def test_file_filtering(self, mock_is_fuzz_target):
        # Create some test files
        test_files = [
            os.path.join(self.test_dir, "test1_fuzzer"),
            os.path.join(self.test_dir, "test2_fuzzer"),
            os.path.join(self.test_dir, "not_a_fuzzer"),
        ]

        for file_path in test_files:
            self.create_file(file_path)

        # Configure mock to only identify specific files as fuzz targets
        def is_fuzz_target_side_effect(path):
            return path.endswith("_fuzzer")

        mock_is_fuzz_target.side_effect = is_fuzz_target_side_effect

        found_targets = get_fuzz_targets(self.test_dir)

        # Should only find the files ending with _fuzzer
        expected_targets = [f for f in test_files if f.endswith("_fuzzer")]
        self.assertEqual(sorted(found_targets), sorted(expected_targets))
