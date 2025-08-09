#!/usr/bin/env python3

import os
import unittest
import copy
from pathlib import Path

from buttercup.common.sarif_store import SARIFBroadcastDetail
from buttercup.common.datastructures.msg_pb2 import TracedCrash
from buttercup.orchestrator.scheduler.sarif_matcher import match


class TestSarifMatcher(unittest.TestCase):
    """Test suite for the SARIF matcher functionality."""

    def setUp(self):
        """Set up test fixtures."""
        test_dir = Path(os.path.dirname(os.path.abspath(__file__)))
        self.data_dir = test_dir / "data"
        self.sarif_broadcast_path = self.data_dir / "sarif_broadcast.json"
        self.sarif_matching_vuln_path = self.data_dir / "traced_crash.proto"

    def load_sarif_broadcast(self) -> SARIFBroadcastDetail:
        """Test that we can load a SARIF broadcast from the file."""
        with open(self.sarif_broadcast_path, "r") as f:
            sarif_json = f.read()
            sarif_broadcast = SARIFBroadcastDetail.model_validate_json(sarif_json)

        self.assertIsInstance(sarif_broadcast, SARIFBroadcastDetail)
        self.assertEqual(sarif_broadcast.sarif_id, "9be47143-9126-43ec-aa86-5eee3935e79c")
        self.assertEqual(sarif_broadcast.task_id, "d769fce7-59f0-4399-8a63-9569bfcd67a4")
        return sarif_broadcast

    def load_traced_crash(self) -> TracedCrash:
        """Test that we can load a traced crash from the file."""
        with open(self.sarif_matching_vuln_path, "rb") as f:
            # Parse the protobuf message
            traced_crash_data = f.read()
            traced_crash = TracedCrash()
            traced_crash.ParseFromString(traced_crash_data)

        self.assertIsInstance(traced_crash, TracedCrash)
        self.assertTrue(hasattr(traced_crash, "crash"))
        self.assertTrue(hasattr(traced_crash, "tracer_stacktrace"))
        return traced_crash

    def test_match(self):
        """Test that we can match a SARIF broadcast with a traced crash."""
        sarif_broadcast = self.load_sarif_broadcast()
        traced_crash = self.load_traced_crash()
        result = match(sarif_broadcast, traced_crash)
        self.assertIsNotNone(result)
        self.assertEqual(result.sarif_info.file, Path("pngrutil.c"))
        self.assertEqual(result.frame.file, Path("/src/libpng/pngrutil.c"))
        self.assertEqual(result.frame.line, 1447)
        self.assertEqual(result.frame.function, "OSS_FUZZ_png_handle_iCCP")
        self.assertTrue(result.matches_filename)
        self.assertTrue(result.matches_lines)
        self.assertFalse(result.matches_function)
        self.assertFalse(result.matches_stripped_function)
        self.assertFalse(result.matches_full_path)

    def test_match_different_line_number(self):
        """Test matching with a different line number outside the SARIF range."""
        sarif_broadcast = self.load_sarif_broadcast()
        traced_crash = self.load_traced_crash()

        # Modify the stacktrace to point to a different line number
        modified_stacktrace = traced_crash.tracer_stacktrace
        modified_stacktrace = modified_stacktrace.replace("/src/libpng/pngrutil.c:1447", "/src/libpng/pngrutil.c:1500")
        traced_crash.tracer_stacktrace = modified_stacktrace

        result = match(sarif_broadcast, traced_crash)
        self.assertIsNone(result, "Should not match when line is outside SARIF range")

    def test_match_different_function_name(self):
        """Test matching when the function name is different but file and line match."""
        sarif_broadcast = self.load_sarif_broadcast()
        traced_crash = self.load_traced_crash()

        # Modify the stacktrace to change the function name
        modified_stacktrace = traced_crash.tracer_stacktrace
        modified_stacktrace = modified_stacktrace.replace("OSS_FUZZ_png_handle_iCCP", "different_function_name")
        traced_crash.tracer_stacktrace = modified_stacktrace

        result = match(sarif_broadcast, traced_crash)
        self.assertIsNotNone(result, "Should still match based on file and line")
        self.assertEqual(result.frame.function, "different_function_name")
        self.assertTrue(result.matches_filename)
        self.assertTrue(result.matches_lines)
        self.assertFalse(result.matches_function)
        self.assertFalse(result.matches_stripped_function)

    def test_match_stripped_function_name(self):
        """Test matching with a function that matches after stripping OSS_FUZZ_ prefix."""
        sarif_broadcast = self.load_sarif_broadcast()
        traced_crash = self.load_traced_crash()

        # Modify the SARIF broadcast to include a function name without OSS_FUZZ_ prefix
        modified_sarif = copy.deepcopy(sarif_broadcast.sarif)

        # Add a logical location with the function name without prefix
        modified_sarif["runs"][0]["results"][0]["locations"][0]["logicalLocations"] = [{"name": "png_handle_iCCP"}]
        sarif_broadcast.sarif = modified_sarif

        result = match(sarif_broadcast, traced_crash)
        self.assertIsNotNone(result)
        self.assertEqual(result.frame.function, "OSS_FUZZ_png_handle_iCCP")
        self.assertTrue(result.matches_stripped_function)

    def test_match_different_file(self):
        """Test matching with a different file name."""
        sarif_broadcast = self.load_sarif_broadcast()
        traced_crash = self.load_traced_crash()

        # Modify the stacktrace to change the file name
        modified_stacktrace = traced_crash.tracer_stacktrace
        modified_stacktrace = modified_stacktrace.replace("/src/libpng/pngrutil.c", "/src/libpng/different_file.c")
        traced_crash.tracer_stacktrace = modified_stacktrace

        result = match(sarif_broadcast, traced_crash)
        self.assertIsNone(result, "Should not match with different filename")

    def test_match_same_function_name(self):
        """Test matching when the function name matches exactly."""
        sarif_broadcast = self.load_sarif_broadcast()
        traced_crash = self.load_traced_crash()

        # Modify the SARIF broadcast to include a function name that exactly matches
        modified_sarif = copy.deepcopy(sarif_broadcast.sarif)

        # Add a logical location with the exact function name
        modified_sarif["runs"][0]["results"][0]["locations"][0]["logicalLocations"] = [
            {"name": "OSS_FUZZ_png_handle_iCCP"}
        ]
        sarif_broadcast.sarif = modified_sarif

        result = match(sarif_broadcast, traced_crash)
        self.assertIsNotNone(result)
        self.assertTrue(result.matches_function)
        self.assertTrue(result.matches_filename)
        self.assertTrue(result.matches_lines)

    def test_match_empty_sarif(self):
        """Test matching with an empty SARIF broadcast."""
        sarif_broadcast = self.load_sarif_broadcast()
        traced_crash = self.load_traced_crash()

        # Create an empty SARIF
        sarif_broadcast.sarif = {"runs": []}

        result = match(sarif_broadcast, traced_crash)
        self.assertIsNone(result, "Should not match with empty SARIF")

    def test_match_empty_stacktrace(self):
        """Test matching with an empty stacktrace."""
        sarif_broadcast = self.load_sarif_broadcast()
        traced_crash = self.load_traced_crash()

        # Empty the stacktrace
        traced_crash.tracer_stacktrace = ""

        result = match(sarif_broadcast, traced_crash)
        self.assertIsNone(result, "Should not match with empty stacktrace")

    def test_match_multiple_locations(self):
        """Test matching with multiple locations in the SARIF, one of which matches."""
        sarif_broadcast = self.load_sarif_broadcast()
        traced_crash = self.load_traced_crash()

        # Modify the SARIF broadcast to include multiple locations
        modified_sarif = copy.deepcopy(sarif_broadcast.sarif)

        # Add a second location that doesn't match
        first_location = modified_sarif["runs"][0]["results"][0]["locations"][0]
        second_location = copy.deepcopy(first_location)
        second_location["physicalLocation"]["artifactLocation"]["uri"] = "different_file.c"
        second_location["physicalLocation"]["region"]["startLine"] = 100
        second_location["physicalLocation"]["region"]["endLine"] = 120

        # Add to the locations array
        modified_sarif["runs"][0]["results"][0]["locations"].append(second_location)
        sarif_broadcast.sarif = modified_sarif

        result = match(sarif_broadcast, traced_crash)
        self.assertIsNotNone(result, "Should match with one of the locations")
        self.assertEqual(result.sarif_info.file, Path("pngrutil.c"))
        self.assertEqual(result.frame.line, 1447)

    def test_match_multiple_sarif_results(self):
        """Test matching with multiple SARIF results, one of which matches."""
        sarif_broadcast = self.load_sarif_broadcast()
        traced_crash = self.load_traced_crash()

        # Modify the SARIF broadcast to include multiple results
        modified_sarif = copy.deepcopy(sarif_broadcast.sarif)

        # Add a second result that doesn't match
        first_result = modified_sarif["runs"][0]["results"][0]
        second_result = copy.deepcopy(first_result)
        second_result["locations"][0]["physicalLocation"]["artifactLocation"]["uri"] = "different_file.c"
        second_result["locations"][0]["physicalLocation"]["region"]["startLine"] = 100
        second_result["locations"][0]["physicalLocation"]["region"]["endLine"] = 120

        # Add to the results array
        modified_sarif["runs"][0]["results"].append(second_result)
        sarif_broadcast.sarif = modified_sarif

        result = match(sarif_broadcast, traced_crash)
        self.assertIsNotNone(result, "Should match with one of the results")
        self.assertEqual(result.sarif_info.file, Path("pngrutil.c"))
        self.assertEqual(result.frame.line, 1447)

    def test_match_full_path(self):
        """Test matching when the full file path matches."""
        sarif_broadcast = self.load_sarif_broadcast()
        traced_crash = self.load_traced_crash()

        # Modify the SARIF broadcast to include the full path that matches the stacktrace
        modified_sarif = copy.deepcopy(sarif_broadcast.sarif)

        # Set the full path
        modified_sarif["runs"][0]["results"][0]["locations"][0]["physicalLocation"]["artifactLocation"]["uri"] = (
            "/src/libpng/pngrutil.c"
        )
        sarif_broadcast.sarif = modified_sarif

        result = match(sarif_broadcast, traced_crash)
        self.assertIsNotNone(result)
        self.assertEqual(result.sarif_info.file, Path("/src/libpng/pngrutil.c"))
        self.assertEqual(result.frame.file, Path("/src/libpng/pngrutil.c"))
        self.assertTrue(result.matches_filename)
        self.assertTrue(result.matches_full_path)
        self.assertTrue(result.matches_lines)


if __name__ == "__main__":
    unittest.main()
