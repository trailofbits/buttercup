"""Unit tests for CoverageRunner coverage processing logic.

Tests the LLVM coverage region filtering and expansion handling introduced
in commit 37d38b40 to improve coverage tracking precision.
"""

from unittest.mock import MagicMock, patch

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from buttercup.fuzzing_infra.coverage_runner import (
    REGION_KIND_BRANCH,
    REGION_KIND_CODE,
    REGION_KIND_EXPANSION,
    REGION_KIND_GAP,
    REGION_KIND_MCDC_BRANCH,
    REGION_KIND_MCDC_DECISION,
    REGION_KIND_SKIPPED,
    CoverageRunner,
)


def create_mock_coverage_runner():
    """Create a CoverageRunner with mocked dependencies."""
    mock_tool = MagicMock()
    mock_tool.project_name = "test_project"

    with patch("buttercup.fuzzing_infra.coverage_runner.ProjectYaml") as mock_yaml:
        from buttercup.common.project_yaml import Language

        mock_yaml.return_value.unified_language = Language.C
        runner = CoverageRunner(mock_tool, "llvm-cov")

    return runner


@pytest.fixture
def mock_coverage_runner():
    """Create a CoverageRunner with mocked dependencies (pytest fixture version)."""
    return create_mock_coverage_runner()


class TestProcessFunctionCoverage:
    """Tests for _process_function_coverage method."""

    def test_empty_data(self, mock_coverage_runner):
        """Returns empty list when data field is missing."""
        result = mock_coverage_runner._process_function_coverage({})
        assert result == []

    def test_no_functions(self, mock_coverage_runner):
        """Returns empty list when no functions in export object."""
        coverage_data = {"data": [{"files": []}]}
        result = mock_coverage_runner._process_function_coverage(coverage_data)
        assert result == []

    def test_function_missing_name(self, mock_coverage_runner):
        """Skips functions without name field."""
        coverage_data = {
            "data": [
                {
                    "functions": [{"regions": [[1, 1, 5, 1, 10, 0, 0, REGION_KIND_CODE]]}],
                    "files": [],
                }
            ]
        }
        result = mock_coverage_runner._process_function_coverage(coverage_data)
        assert result == []

    def test_function_missing_regions(self, mock_coverage_runner):
        """Skips functions without regions field."""
        coverage_data = {"data": [{"functions": [{"name": "test_func"}], "files": []}]}
        result = mock_coverage_runner._process_function_coverage(coverage_data)
        assert result == []

    def test_basic_code_region(self, mock_coverage_runner):
        """Processes basic CodeRegion correctly."""
        coverage_data = {
            "data": [
                {
                    "functions": [
                        {
                            "name": "test_func",
                            "regions": [
                                # [lineStart, colStart, lineEnd, colEnd, execCount, fileID, expandedFileID, kind]
                                [1, 1, 5, 1, 10, 0, 0, REGION_KIND_CODE],
                            ],
                            "filenames": ["test.c"],
                        }
                    ],
                    "files": [],
                }
            ]
        }
        result = mock_coverage_runner._process_function_coverage(coverage_data)
        assert len(result) == 1
        assert result[0].names == "test_func"
        assert result[0].total_lines == 5  # lines 1-5
        assert result[0].covered_lines == 5  # all covered (exec count > 0)
        assert result[0].function_paths == ["test.c"]

    def test_uncovered_code_region(self, mock_coverage_runner):
        """CodeRegion with zero execution count is counted but not covered."""
        coverage_data = {
            "data": [
                {
                    "functions": [
                        {
                            "name": "test_func",
                            "regions": [
                                [1, 1, 3, 1, 5, 0, 0, REGION_KIND_CODE],  # covered
                                [4, 1, 6, 1, 0, 0, 0, REGION_KIND_CODE],  # not covered
                            ],
                            "filenames": ["test.c"],
                        }
                    ],
                    "files": [],
                }
            ]
        }
        result = mock_coverage_runner._process_function_coverage(coverage_data)
        assert len(result) == 1
        assert result[0].total_lines == 6  # lines 1-6
        assert result[0].covered_lines == 3  # lines 1-3

    def test_skipped_region_excluded(self, mock_coverage_runner):
        """SkippedRegion (preprocessor-skipped code) is not counted."""
        coverage_data = {
            "data": [
                {
                    "functions": [
                        {
                            "name": "test_func",
                            "regions": [
                                [1, 1, 3, 1, 10, 0, 0, REGION_KIND_CODE],
                                [4, 1, 10, 1, 0, 0, 0, REGION_KIND_SKIPPED],  # #ifdef'd out
                            ],
                            "filenames": ["test.c"],
                        }
                    ],
                    "files": [],
                }
            ]
        }
        result = mock_coverage_runner._process_function_coverage(coverage_data)
        assert len(result) == 1
        assert result[0].total_lines == 3  # only lines 1-3, skipped region excluded
        assert result[0].covered_lines == 3

    def test_gap_region_excluded(self, mock_coverage_runner):
        """GapRegion (whitespace/formatting) is not counted."""
        coverage_data = {
            "data": [
                {
                    "functions": [
                        {
                            "name": "test_func",
                            "regions": [
                                [1, 1, 3, 1, 10, 0, 0, REGION_KIND_CODE],
                                [4, 1, 5, 1, 0, 0, 0, REGION_KIND_GAP],
                            ],
                            "filenames": ["test.c"],
                        }
                    ],
                    "files": [],
                }
            ]
        }
        result = mock_coverage_runner._process_function_coverage(coverage_data)
        assert len(result) == 1
        assert result[0].total_lines == 3  # gap region excluded
        assert result[0].covered_lines == 3

    def test_branch_region_excluded(self, mock_coverage_runner):
        """BranchRegion (branch metadata) is not counted - overlaps with CodeRegion."""
        coverage_data = {
            "data": [
                {
                    "functions": [
                        {
                            "name": "test_func",
                            "regions": [
                                [1, 1, 5, 1, 10, 0, 0, REGION_KIND_CODE],
                                [2, 5, 2, 15, 5, 0, 0, REGION_KIND_BRANCH],  # same line as code
                            ],
                            "filenames": ["test.c"],
                        }
                    ],
                    "files": [],
                }
            ]
        }
        result = mock_coverage_runner._process_function_coverage(coverage_data)
        assert len(result) == 1
        assert result[0].total_lines == 5  # branch not double-counted
        assert result[0].covered_lines == 5

    def test_mcdc_regions_excluded(self, mock_coverage_runner):
        """MCDC regions (metadata) are not counted."""
        coverage_data = {
            "data": [
                {
                    "functions": [
                        {
                            "name": "test_func",
                            "regions": [
                                [1, 1, 5, 1, 10, 0, 0, REGION_KIND_CODE],
                                [2, 1, 2, 20, 0, 0, 0, REGION_KIND_MCDC_DECISION],
                                [2, 5, 2, 10, 0, 0, 0, REGION_KIND_MCDC_BRANCH],
                            ],
                            "filenames": ["test.c"],
                        }
                    ],
                    "files": [],
                }
            ]
        }
        result = mock_coverage_runner._process_function_coverage(coverage_data)
        assert len(result) == 1
        assert result[0].total_lines == 5
        assert result[0].covered_lines == 5

    def test_backwards_compatibility_no_kind_field(self, mock_coverage_runner):
        """Regions without kind field (old LLVM format) default to CodeRegion."""
        coverage_data = {
            "data": [
                {
                    "functions": [
                        {
                            "name": "test_func",
                            "regions": [
                                [1, 1, 5, 1, 10],  # only 5 fields, no kind
                            ],
                            "filenames": ["test.c"],
                        }
                    ],
                    "files": [],
                }
            ]
        }
        result = mock_coverage_runner._process_function_coverage(coverage_data)
        assert len(result) == 1
        assert result[0].total_lines == 5
        assert result[0].covered_lines == 5

    def test_function_with_zero_covered_lines_excluded(self, mock_coverage_runner):
        """Functions with zero covered lines are not included in results."""
        coverage_data = {
            "data": [
                {
                    "functions": [
                        {
                            "name": "uncovered_func",
                            "regions": [
                                [1, 1, 10, 1, 0, 0, 0, REGION_KIND_CODE],  # zero exec count
                            ],
                            "filenames": ["test.c"],
                        }
                    ],
                    "files": [],
                }
            ]
        }
        result = mock_coverage_runner._process_function_coverage(coverage_data)
        assert result == []

    def test_overlapping_code_regions_deduplicated(self, mock_coverage_runner):
        """Overlapping CodeRegions don't double-count lines."""
        coverage_data = {
            "data": [
                {
                    "functions": [
                        {
                            "name": "test_func",
                            "regions": [
                                [1, 1, 10, 1, 5, 0, 0, REGION_KIND_CODE],
                                [5, 1, 15, 1, 3, 0, 0, REGION_KIND_CODE],  # overlaps 5-10
                            ],
                            "filenames": ["test.c"],
                        }
                    ],
                    "files": [],
                }
            ]
        }
        result = mock_coverage_runner._process_function_coverage(coverage_data)
        assert len(result) == 1
        assert result[0].total_lines == 15  # lines 1-15, not 25
        assert result[0].covered_lines == 15


class TestBuildExpansionCoverageMap:
    """Tests for _build_expansion_coverage_map method."""

    def test_empty_files(self, mock_coverage_runner):
        """Returns empty maps when no files."""
        export_obj = {"files": []}
        expansion_map, coord_to_filenames = mock_coverage_runner._build_expansion_coverage_map(export_obj)
        assert expansion_map == {}
        assert coord_to_filenames == {}

    def test_no_expansions(self, mock_coverage_runner):
        """Returns empty maps when files have no expansions."""
        export_obj = {"files": [{"filename": "test.c"}]}
        expansion_map, coord_to_filenames = mock_coverage_runner._build_expansion_coverage_map(export_obj)
        assert expansion_map == {}
        assert coord_to_filenames == {}

    def test_expansion_with_code_regions_covered(self, mock_coverage_runner):
        """Expansion returns target_regions list directly."""
        target_regions = [[1, 1, 3, 1, 5, 0, 0, REGION_KIND_CODE]]  # covered
        export_obj = {
            "files": [
                {
                    "filename": "test.c",
                    "expansions": [
                        {
                            "source_region": [10, 5, 10, 20],  # macro call location
                            "target_regions": target_regions,
                        }
                    ],
                }
            ]
        }
        expansion_map, coord_to_filenames = mock_coverage_runner._build_expansion_coverage_map(export_obj)
        key = ("test.c", 10, 5, 10, 20)  # key now includes filename
        assert key in expansion_map
        assert expansion_map[key] == target_regions
        assert coord_to_filenames[(10, 5, 10, 20)] == ["test.c"]

    def test_expansion_with_code_regions_uncovered(self, mock_coverage_runner):
        """Expansion returns target_regions list directly (uncovered case)."""
        target_regions = [[1, 1, 3, 1, 0, 0, 0, REGION_KIND_CODE]]  # uncovered
        export_obj = {
            "files": [
                {
                    "filename": "test.c",
                    "expansions": [
                        {
                            "source_region": [10, 5, 10, 20],
                            "target_regions": target_regions,
                        }
                    ],
                }
            ]
        }
        expansion_map, coord_to_filenames = mock_coverage_runner._build_expansion_coverage_map(export_obj)
        key = ("test.c", 10, 5, 10, 20)  # key now includes filename
        assert key in expansion_map
        assert expansion_map[key] == target_regions
        assert coord_to_filenames[(10, 5, 10, 20)] == ["test.c"]

    def test_expansion_with_only_non_code_regions(self, mock_coverage_runner):
        """Expansion returns target_regions even with non-CodeRegions."""
        target_regions = [
            [1, 1, 3, 1, 5, 0, 0, REGION_KIND_GAP],
            [1, 1, 3, 1, 5, 0, 0, REGION_KIND_BRANCH],
        ]
        export_obj = {
            "files": [
                {
                    "filename": "test.c",
                    "expansions": [
                        {
                            "source_region": [10, 5, 10, 20],
                            "target_regions": target_regions,
                        }
                    ],
                }
            ]
        }
        expansion_map, coord_to_filenames = mock_coverage_runner._build_expansion_coverage_map(export_obj)
        key = ("test.c", 10, 5, 10, 20)  # key now includes filename
        assert key in expansion_map
        assert expansion_map[key] == target_regions

    def test_expansion_empty_target_regions(self, mock_coverage_runner):
        """Expansion with empty target_regions returns empty list."""
        export_obj = {
            "files": [
                {
                    "filename": "test.c",
                    "expansions": [
                        {
                            "source_region": [10, 5, 10, 20],
                            "target_regions": [],
                        }
                    ],
                }
            ]
        }
        expansion_map, coord_to_filenames = mock_coverage_runner._build_expansion_coverage_map(export_obj)
        key = ("test.c", 10, 5, 10, 20)  # key now includes filename
        assert key in expansion_map
        assert expansion_map[key] == []

    def test_malformed_source_region_skipped(self, mock_coverage_runner):
        """Expansions with malformed source_region are skipped."""
        export_obj = {
            "files": [
                {
                    "filename": "test.c",
                    "expansions": [
                        {
                            "source_region": [10, 5],  # too short
                            "target_regions": [[1, 1, 3, 1, 5, 0, 0, REGION_KIND_CODE]],
                        }
                    ],
                }
            ]
        }
        expansion_map, coord_to_filenames = mock_coverage_runner._build_expansion_coverage_map(export_obj)
        assert expansion_map == {}
        assert coord_to_filenames == {}

    def test_malformed_target_region_preserved(self, mock_coverage_runner):
        """Target regions are stored as-is, including malformed ones."""
        target_regions = [
            [1, 1, 3],  # too short, but still stored
            [1, 1, 3, 1, 5, 0, 0, REGION_KIND_CODE],  # valid
        ]
        export_obj = {
            "files": [
                {
                    "filename": "test.c",
                    "expansions": [
                        {
                            "source_region": [10, 5, 10, 20],
                            "target_regions": target_regions,
                        }
                    ],
                }
            ]
        }
        expansion_map, coord_to_filenames = mock_coverage_runner._build_expansion_coverage_map(export_obj)
        key = ("test.c", 10, 5, 10, 20)  # key now includes filename
        assert key in expansion_map
        # Target regions are stored as-is; filtering happens during processing
        assert expansion_map[key] == target_regions


class TestProcessRegions:
    """Tests for _process_regions method."""

    def test_empty_regions(self, mock_coverage_runner):
        """Empty regions list produces empty sets."""
        total_lines: set[int] = set()
        covered_lines: set[int] = set()
        mock_coverage_runner._process_regions([], total_lines, covered_lines, {}, {}, ["test.c"], {})
        assert total_lines == set()
        assert covered_lines == set()

    def test_code_region_processing(self, mock_coverage_runner):
        """CodeRegion adds all lines to totals, covered lines if exec > 0."""
        total_lines: set[int] = set()
        covered_lines: set[int] = set()
        regions = [
            [1, 1, 5, 1, 10, 0, 0, REGION_KIND_CODE],  # covered
            [6, 1, 8, 1, 0, 0, 0, REGION_KIND_CODE],  # not covered
        ]
        mock_coverage_runner._process_regions(regions, total_lines, covered_lines, {}, {}, ["test.c"], {})
        assert total_lines == {1, 2, 3, 4, 5, 6, 7, 8}
        assert covered_lines == {1, 2, 3, 4, 5}

    def test_expansion_region_with_code(self, mock_coverage_runner):
        """ExpansionRegion recursively adds lines from expanded macro body."""
        total_lines: set[int] = set()
        covered_lines: set[int] = set()
        regions = [
            [10, 5, 10, 20, 0, 0, 0, REGION_KIND_EXPANSION],
        ]
        # Macro expands to lines 100-103 (covered)
        target_regions = [[100, 1, 103, 1, 5, 0, 0, REGION_KIND_CODE]]
        expansion_map = {("test.c", 10, 5, 10, 20): target_regions}
        coord_to_filenames = {(10, 5, 10, 20): ["test.c"]}
        mock_coverage_runner._process_regions(
            regions, total_lines, covered_lines, expansion_map, coord_to_filenames, ["test.c"], {}
        )
        # Should include macro body lines, not call site
        assert total_lines == {100, 101, 102, 103}
        assert covered_lines == {100, 101, 102, 103}

    def test_expansion_region_uncovered(self, mock_coverage_runner):
        """ExpansionRegion with uncovered CodeRegions adds to total but not covered."""
        total_lines: set[int] = set()
        covered_lines: set[int] = set()
        regions = [
            [10, 5, 10, 20, 0, 0, 0, REGION_KIND_EXPANSION],
        ]
        # Macro expands to lines 100-102 (not covered)
        target_regions = [[100, 1, 102, 1, 0, 0, 0, REGION_KIND_CODE]]
        expansion_map = {("test.c", 10, 5, 10, 20): target_regions}
        coord_to_filenames = {(10, 5, 10, 20): ["test.c"]}
        mock_coverage_runner._process_regions(
            regions, total_lines, covered_lines, expansion_map, coord_to_filenames, ["test.c"], {}
        )
        assert total_lines == {100, 101, 102}
        assert covered_lines == set()

    def test_expansion_region_no_code(self, mock_coverage_runner):
        """ExpansionRegion with only non-CodeRegions adds nothing."""
        total_lines: set[int] = set()
        covered_lines: set[int] = set()
        regions = [
            [10, 5, 10, 20, 0, 0, 0, REGION_KIND_EXPANSION],
        ]
        # Macro has only GAP and BRANCH regions (no code)
        target_regions = [
            [100, 1, 102, 1, 5, 0, 0, REGION_KIND_GAP],
            [100, 1, 102, 1, 5, 0, 0, REGION_KIND_BRANCH],
        ]
        expansion_map = {("test.c", 10, 5, 10, 20): target_regions}
        coord_to_filenames = {(10, 5, 10, 20): ["test.c"]}
        mock_coverage_runner._process_regions(
            regions, total_lines, covered_lines, expansion_map, coord_to_filenames, ["test.c"], {}
        )
        assert total_lines == set()
        assert covered_lines == set()

    def test_expansion_region_not_in_map(self, mock_coverage_runner):
        """ExpansionRegion not in map is treated as no code."""
        total_lines: set[int] = set()
        covered_lines: set[int] = set()
        regions = [
            [10, 5, 10, 20, 0, 0, 0, REGION_KIND_EXPANSION],
        ]
        mock_coverage_runner._process_regions(regions, total_lines, covered_lines, {}, {}, ["test.c"], {})
        assert total_lines == set()
        assert covered_lines == set()

    def test_skipped_regions_ignored(self, mock_coverage_runner):
        """SkippedRegion adds nothing."""
        total_lines: set[int] = set()
        covered_lines: set[int] = set()
        regions = [
            [1, 1, 100, 1, 0, 0, 0, REGION_KIND_SKIPPED],
        ]
        mock_coverage_runner._process_regions(regions, total_lines, covered_lines, {}, {}, ["test.c"], {})
        assert total_lines == set()
        assert covered_lines == set()

    def test_gap_regions_ignored(self, mock_coverage_runner):
        """GapRegion adds nothing."""
        total_lines: set[int] = set()
        covered_lines: set[int] = set()
        regions = [
            [1, 1, 100, 1, 0, 0, 0, REGION_KIND_GAP],
        ]
        mock_coverage_runner._process_regions(regions, total_lines, covered_lines, {}, {}, ["test.c"], {})
        assert total_lines == set()
        assert covered_lines == set()

    def test_branch_regions_ignored(self, mock_coverage_runner):
        """BranchRegion adds nothing."""
        total_lines: set[int] = set()
        covered_lines: set[int] = set()
        regions = [
            [1, 1, 100, 1, 50, 0, 0, REGION_KIND_BRANCH],
        ]
        mock_coverage_runner._process_regions(regions, total_lines, covered_lines, {}, {}, ["test.c"], {})
        assert total_lines == set()
        assert covered_lines == set()

    def test_mcdc_decision_regions_ignored(self, mock_coverage_runner):
        """MCDCDecisionRegion adds nothing."""
        total_lines: set[int] = set()
        covered_lines: set[int] = set()
        regions = [
            [1, 1, 100, 1, 0, 0, 0, REGION_KIND_MCDC_DECISION],
        ]
        mock_coverage_runner._process_regions(regions, total_lines, covered_lines, {}, {}, ["test.c"], {})
        assert total_lines == set()
        assert covered_lines == set()

    def test_mcdc_branch_regions_ignored(self, mock_coverage_runner):
        """MCDCBranchRegion adds nothing."""
        total_lines: set[int] = set()
        covered_lines: set[int] = set()
        regions = [
            [1, 1, 100, 1, 0, 0, 0, REGION_KIND_MCDC_BRANCH],
        ]
        mock_coverage_runner._process_regions(regions, total_lines, covered_lines, {}, {}, ["test.c"], {})
        assert total_lines == set()
        assert covered_lines == set()

    def test_malformed_region_skipped(self, mock_coverage_runner):
        """Regions with too few fields are skipped."""
        total_lines: set[int] = set()
        covered_lines: set[int] = set()
        regions = [
            [1, 1, 5],  # too short
            [1, 1, 5, 1, 10, 0, 0, REGION_KIND_CODE],  # valid
        ]
        mock_coverage_runner._process_regions(regions, total_lines, covered_lines, {}, {}, ["test.c"], {})
        assert total_lines == {1, 2, 3, 4, 5}
        assert covered_lines == {1, 2, 3, 4, 5}


class TestAddRegionLines:
    """Tests for _add_region_lines helper method."""

    def test_single_line_region(self, mock_coverage_runner):
        """Single line region adds one line."""
        total_lines: set[int] = set()
        covered_lines: set[int] = set()
        region = [5, 1, 5, 10, 1]  # single line, covered
        mock_coverage_runner._add_region_lines(region, total_lines, covered_lines)
        assert total_lines == {5}
        assert covered_lines == {5}

    def test_multi_line_region_covered(self, mock_coverage_runner):
        """Multi-line region with coverage adds all lines to both sets."""
        total_lines: set[int] = set()
        covered_lines: set[int] = set()
        region = [10, 1, 15, 1, 100]
        mock_coverage_runner._add_region_lines(region, total_lines, covered_lines)
        assert total_lines == {10, 11, 12, 13, 14, 15}
        assert covered_lines == {10, 11, 12, 13, 14, 15}

    def test_multi_line_region_uncovered(self, mock_coverage_runner):
        """Multi-line region without coverage adds lines only to totals."""
        total_lines: set[int] = set()
        covered_lines: set[int] = set()
        region = [10, 1, 15, 1, 0]  # exec count = 0
        mock_coverage_runner._add_region_lines(region, total_lines, covered_lines)
        assert total_lines == {10, 11, 12, 13, 14, 15}
        assert covered_lines == set()

    def test_accumulates_to_existing_sets(self, mock_coverage_runner):
        """Lines are added to existing sets, not replacing them."""
        total_lines: set[int] = {1, 2, 3}
        covered_lines: set[int] = {1}
        region = [5, 1, 7, 1, 10]
        mock_coverage_runner._add_region_lines(region, total_lines, covered_lines)
        assert total_lines == {1, 2, 3, 5, 6, 7}
        assert covered_lines == {1, 5, 6, 7}


class TestCoverageInvariants:
    """Property-based tests for coverage invariants."""

    @given(
        line_start=st.integers(min_value=1, max_value=1000),
        line_span=st.integers(min_value=0, max_value=100),
        exec_count=st.integers(min_value=0, max_value=10000),
    )
    @settings(max_examples=100)
    def test_covered_lines_subset_of_total(self, line_start, line_span, exec_count):
        """Covered lines must always be a subset of total lines."""
        runner = create_mock_coverage_runner()
        line_end = line_start + line_span
        total_lines: set[int] = set()
        covered_lines: set[int] = set()
        region = [line_start, 1, line_end, 1, exec_count, 0, 0, REGION_KIND_CODE]
        runner._process_regions([region], total_lines, covered_lines, {}, {}, ["test.c"], {})
        assert covered_lines.issubset(total_lines)

    @given(
        regions_data=st.lists(
            st.tuples(
                st.integers(min_value=1, max_value=100),  # line_start
                st.integers(min_value=0, max_value=20),  # line_span
                st.integers(min_value=0, max_value=100),  # exec_count
                st.sampled_from(
                    [
                        REGION_KIND_CODE,
                        REGION_KIND_EXPANSION,
                        REGION_KIND_SKIPPED,
                        REGION_KIND_GAP,
                        REGION_KIND_BRANCH,
                        REGION_KIND_MCDC_DECISION,
                        REGION_KIND_MCDC_BRANCH,
                    ]
                ),
            ),
            min_size=0,
            max_size=20,
        )
    )
    @settings(max_examples=100)
    def test_covered_never_exceeds_total(self, regions_data):
        """Number of covered lines can never exceed total lines."""
        runner = create_mock_coverage_runner()
        regions = []
        for line_start, line_span, exec_count, kind in regions_data:
            line_end = line_start + line_span
            regions.append([line_start, 1, line_end, 1, exec_count, 0, 0, kind])

        total_lines: set[int] = set()
        covered_lines: set[int] = set()
        runner._process_regions(regions, total_lines, covered_lines, {}, {}, ["test.c"], {})

        assert len(covered_lines) <= len(total_lines)

    @given(
        regions_data=st.lists(
            st.tuples(
                st.integers(min_value=1, max_value=100),
                st.integers(min_value=0, max_value=20),
                st.integers(min_value=0, max_value=100),
            ),
            min_size=1,
            max_size=10,
        )
    )
    @settings(max_examples=50)
    def test_non_code_regions_add_zero_lines(self, regions_data):
        """SkippedRegion, GapRegion, BranchRegion, and MCDC regions add no lines."""
        runner = create_mock_coverage_runner()
        non_code_kinds = [
            REGION_KIND_SKIPPED,
            REGION_KIND_GAP,
            REGION_KIND_BRANCH,
            REGION_KIND_MCDC_DECISION,
            REGION_KIND_MCDC_BRANCH,
        ]

        for kind in non_code_kinds:
            regions = []
            for line_start, line_span, exec_count in regions_data:
                line_end = line_start + line_span
                regions.append([line_start, 1, line_end, 1, exec_count, 0, 0, kind])

            total_lines: set[int] = set()
            covered_lines: set[int] = set()
            runner._process_regions(regions, total_lines, covered_lines, {}, {}, ["test.c"], {})

            assert total_lines == set(), f"Kind {kind} should add no lines"
            assert covered_lines == set(), f"Kind {kind} should add no covered lines"

    @given(
        line_start=st.integers(min_value=1, max_value=100),
        exec_count=st.integers(min_value=1, max_value=100),
    )
    @settings(max_examples=50)
    def test_positive_exec_count_means_covered(self, line_start, exec_count):
        """CodeRegion with positive exec_count must have covered lines."""
        runner = create_mock_coverage_runner()
        total_lines: set[int] = set()
        covered_lines: set[int] = set()
        region = [line_start, 1, line_start, 1, exec_count, 0, 0, REGION_KIND_CODE]
        runner._process_regions([region], total_lines, covered_lines, {}, {}, ["test.c"], {})
        assert len(covered_lines) > 0

    @given(
        line_start=st.integers(min_value=1, max_value=100),
        line_span=st.integers(min_value=0, max_value=50),
    )
    @settings(max_examples=50)
    def test_zero_exec_count_means_no_coverage(self, line_start, line_span):
        """CodeRegion with zero exec_count must have no covered lines."""
        runner = create_mock_coverage_runner()
        line_end = line_start + line_span
        total_lines: set[int] = set()
        covered_lines: set[int] = set()
        region = [line_start, 1, line_end, 1, 0, 0, 0, REGION_KIND_CODE]
        runner._process_regions([region], total_lines, covered_lines, {}, {}, ["test.c"], {})
        assert len(covered_lines) == 0
        assert len(total_lines) == line_span + 1

    @given(
        line=st.integers(min_value=1, max_value=100),
        macro_start=st.integers(min_value=200, max_value=300),
        macro_lines=st.integers(min_value=1, max_value=10),
        exec_count=st.integers(min_value=0, max_value=100),
    )
    @settings(max_examples=50)
    def test_expansion_coverage_consistency(self, line, macro_start, macro_lines, exec_count):
        """ExpansionRegion coverage adds lines from macro body, not call site."""
        runner = create_mock_coverage_runner()

        total_lines: set[int] = set()
        covered_lines: set[int] = set()
        # key now includes filename
        key = ("test.c", line, 1, line, 10)
        coords = (line, 1, line, 10)
        macro_end = macro_start + macro_lines - 1
        target_regions = [[macro_start, 1, macro_end, 1, exec_count, 0, 0, REGION_KIND_CODE]]
        expansion_map = {key: target_regions}
        coord_to_filenames = {coords: ["test.c"]}
        regions = [[line, 1, line, 10, 0, 0, 0, REGION_KIND_EXPANSION]]

        runner._process_regions(regions, total_lines, covered_lines, expansion_map, coord_to_filenames, ["test.c"], {})

        # Should have macro body lines, not call site line
        expected_total = set(range(macro_start, macro_end + 1))
        assert total_lines == expected_total
        assert line not in total_lines  # Call site should NOT be in total

        if exec_count > 0:
            assert covered_lines == expected_total
        else:
            assert covered_lines == set()


class TestIntegrationScenarios:
    """Integration tests with realistic LLVM coverage data patterns."""

    def test_function_with_ifdef_block(self, mock_coverage_runner):
        """Function containing #ifdef block should exclude skipped lines."""
        coverage_data = {
            "data": [
                {
                    "functions": [
                        {
                            "name": "process_data",
                            "regions": [
                                [1, 1, 5, 1, 10, 0, 0, REGION_KIND_CODE],  # before ifdef
                                [6, 1, 15, 1, 0, 0, 0, REGION_KIND_SKIPPED],  # #ifdef DEBUG ... #endif
                                [16, 1, 20, 1, 10, 0, 0, REGION_KIND_CODE],  # after ifdef
                            ],
                            "filenames": ["process.c"],
                        }
                    ],
                    "files": [],
                }
            ]
        }
        result = mock_coverage_runner._process_function_coverage(coverage_data)
        assert len(result) == 1
        assert result[0].total_lines == 10  # 5 + 5, skipped excluded
        assert result[0].covered_lines == 10

    def test_function_with_macro_calls(self, mock_coverage_runner):
        """Function with macro calls should count expanded macro body lines."""
        coverage_data = {
            "data": [
                {
                    "functions": [
                        {
                            "name": "use_macros",
                            "regions": [
                                [1, 1, 3, 1, 10, 0, 0, REGION_KIND_CODE],
                                [4, 5, 4, 20, 0, 0, 0, REGION_KIND_EXPANSION],  # MY_MACRO call
                                [5, 1, 7, 1, 10, 0, 0, REGION_KIND_CODE],
                            ],
                            "filenames": ["macros.c"],
                        }
                    ],
                    "files": [
                        {
                            "filename": "macros.c",
                            "expansions": [
                                {
                                    "source_region": [4, 5, 4, 20],
                                    "target_regions": [
                                        [100, 1, 105, 1, 10, 0, 0, REGION_KIND_CODE],  # macro body
                                    ],
                                }
                            ],
                        }
                    ],
                }
            ]
        }
        result = mock_coverage_runner._process_function_coverage(coverage_data)
        assert len(result) == 1
        # Lines 1-3 (3) + lines 100-105 from macro (6) + lines 5-7 (3) = 12
        assert result[0].total_lines == 12
        assert result[0].covered_lines == 12

    def test_function_with_branch_coverage(self, mock_coverage_runner):
        """Function with branch regions should not double-count lines."""
        coverage_data = {
            "data": [
                {
                    "functions": [
                        {
                            "name": "branching_func",
                            "regions": [
                                [1, 1, 10, 1, 10, 0, 0, REGION_KIND_CODE],
                                # Branch regions on same lines
                                [3, 5, 3, 15, 5, 0, 0, REGION_KIND_BRANCH],  # if condition
                                [3, 5, 3, 15, 5, 0, 0, REGION_KIND_BRANCH],  # true branch
                                [5, 5, 5, 15, 3, 0, 0, REGION_KIND_BRANCH],  # else
                            ],
                            "filenames": ["branch.c"],
                        }
                    ],
                    "files": [],
                }
            ]
        }
        result = mock_coverage_runner._process_function_coverage(coverage_data)
        assert len(result) == 1
        assert result[0].total_lines == 10  # no double counting
        assert result[0].covered_lines == 10

    def test_multiple_functions_in_file(self, mock_coverage_runner):
        """Multiple functions should be processed independently."""
        coverage_data = {
            "data": [
                {
                    "functions": [
                        {
                            "name": "func_a",
                            "regions": [[1, 1, 10, 1, 5, 0, 0, REGION_KIND_CODE]],
                            "filenames": ["multi.c"],
                        },
                        {
                            "name": "func_b",
                            "regions": [[20, 1, 25, 1, 10, 0, 0, REGION_KIND_CODE]],
                            "filenames": ["multi.c"],
                        },
                        {
                            "name": "func_c_uncovered",
                            "regions": [[30, 1, 40, 1, 0, 0, 0, REGION_KIND_CODE]],
                            "filenames": ["multi.c"],
                        },
                    ],
                    "files": [],
                }
            ]
        }
        result = mock_coverage_runner._process_function_coverage(coverage_data)
        assert len(result) == 2  # func_c excluded (zero coverage)
        names = {r.names for r in result}
        assert names == {"func_a", "func_b"}

    def test_cpp_name_demangling(self):
        """C++ mangled names should be demangled."""
        mock_tool = MagicMock()
        mock_tool.project_name = "test_project"

        with patch("buttercup.fuzzing_infra.coverage_runner.ProjectYaml") as mock_yaml:
            from buttercup.common.project_yaml import Language

            mock_yaml.return_value.unified_language = Language.CPP
            runner = CoverageRunner(mock_tool, "llvm-cov")

        coverage_data = {
            "data": [
                {
                    "functions": [
                        {
                            "name": "_Z3fooi",  # mangled name for foo(int)
                            "regions": [[1, 1, 5, 1, 10, 0, 0, REGION_KIND_CODE]],
                            "filenames": ["test.cpp"],
                        }
                    ],
                    "files": [],
                }
            ]
        }
        result = runner._process_function_coverage(coverage_data)
        assert len(result) == 1
        assert result[0].names == "foo(int)"  # demangled

    def test_cross_file_macro_collision_prevented(self, mock_coverage_runner):
        """Macros at same line/col in different files should not cause coverage leakage.

        This tests the fix for a bug where functions in different files could
        incorrectly inherit coverage from each other when they had macros at
        the same line/column coordinates.

        Scenario:
        - file_a.c:func_a has macro PNG_UNUSED at line 10, col 4 - COVERED (executed)
        - file_b.c:func_b has macro PNG_UNUSED at line 10, col 4 - NOT COVERED (never executed)

        Before the fix: func_b would incorrectly show coverage because the
        expansion_coverage map used only (line, col) as key, causing collisions.

        After the fix: filename is included in the key, preventing collisions.
        """
        coverage_data = {
            "data": [
                {
                    "functions": [
                        {
                            "name": "func_a",
                            "regions": [
                                [10, 4, 10, 20, 0, 0, 0, REGION_KIND_EXPANSION],  # macro call
                                [11, 1, 15, 1, 5, 0, 0, REGION_KIND_CODE],  # covered code
                            ],
                            "filenames": ["file_a.c"],
                        },
                        {
                            "name": "func_b",
                            "regions": [
                                # Same line/col as func_a's macro - but different file!
                                [10, 4, 10, 20, 0, 0, 0, REGION_KIND_EXPANSION],  # macro call
                                [11, 1, 15, 1, 0, 0, 0, REGION_KIND_CODE],  # uncovered code
                            ],
                            "filenames": ["file_b.c"],
                        },
                    ],
                    "files": [
                        {
                            "filename": "file_a.c",
                            "expansions": [
                                {
                                    "source_region": [10, 4, 10, 20],
                                    "target_regions": [
                                        [100, 1, 100, 10, 5, 0, 0, REGION_KIND_CODE],  # covered
                                    ],
                                }
                            ],
                        },
                        {
                            "filename": "file_b.c",
                            "expansions": [
                                {
                                    "source_region": [10, 4, 10, 20],  # Same coordinates!
                                    "target_regions": [
                                        [100, 1, 100, 10, 0, 0, 0, REGION_KIND_CODE],  # NOT covered
                                    ],
                                }
                            ],
                        },
                    ],
                }
            ]
        }
        result = mock_coverage_runner._process_function_coverage(coverage_data)

        # func_a should be covered (has covered code and covered macro expansion)
        func_a_results = [r for r in result if r.names == "func_a"]
        assert len(func_a_results) == 1
        assert func_a_results[0].covered_lines > 0  # Should have coverage

        # func_b should NOT appear in results because it has zero covered lines
        # The macro at same coordinates should NOT inherit coverage from file_a.c
        func_b_results = [r for r in result if r.names == "func_b"]
        assert len(func_b_results) == 0  # Should be excluded (zero coverage)

    def test_partial_coverage_computes_correct_totals(self, mock_coverage_runner):
        """Verify total_lines and covered_lines are correctly computed with partial coverage."""
        coverage_data = {
            "data": [
                {
                    "functions": [
                        {
                            "name": "test_func",
                            "regions": [
                                [1, 1, 5, 1, 10, 0, 0, REGION_KIND_CODE],  # covered
                                [6, 1, 10, 1, 0, 0, 0, REGION_KIND_CODE],  # not covered
                            ],
                            "filenames": ["test.c"],
                        }
                    ],
                    "files": [],
                }
            ]
        }
        result = mock_coverage_runner._process_function_coverage(coverage_data)
        assert len(result) == 1
        assert result[0].total_lines == 10
        assert result[0].covered_lines == 5


class TestNestedMacroExpansion:
    """Tests for recursive/nested macro expansion handling."""

    @pytest.fixture
    def mock_coverage_runner(self):
        mock_tool = MagicMock()
        mock_tool.project_name = "test_project"
        with patch("buttercup.fuzzing_infra.coverage_runner.ProjectYaml") as mock_yaml:
            from buttercup.common.project_yaml import Language

            mock_yaml.return_value.unified_language = Language.C
            runner = CoverageRunner(mock_tool, "llvm-cov")
        return runner

    def test_nested_macro_expansion(self, mock_coverage_runner):
        """Nested macros (A -> B -> code) should recursively include all lines."""
        # OUTER_MACRO at line 10 expands to INNER_MACRO at line 100
        # INNER_MACRO at line 100 expands to code at lines 200-205
        coverage_data = {
            "data": [
                {
                    "functions": [
                        {
                            "name": "nested_func",
                            "regions": [
                                [1, 1, 5, 1, 10, 0, 0, REGION_KIND_CODE],  # regular code
                                [10, 1, 10, 20, 0, 0, 0, REGION_KIND_EXPANSION],  # OUTER_MACRO
                            ],
                            "filenames": ["test.c"],
                        }
                    ],
                    "files": [
                        {
                            "filename": "test.c",
                            "expansions": [
                                {
                                    "source_region": [10, 1, 10, 20],  # OUTER_MACRO call
                                    "target_regions": [
                                        # OUTER_MACRO expands to INNER_MACRO call
                                        [100, 1, 100, 15, 5, 0, 0, REGION_KIND_EXPANSION],
                                    ],
                                },
                                {
                                    "source_region": [100, 1, 100, 15],  # INNER_MACRO call
                                    "target_regions": [
                                        # INNER_MACRO expands to actual code
                                        [200, 1, 205, 1, 10, 0, 0, REGION_KIND_CODE],
                                    ],
                                },
                            ],
                        }
                    ],
                }
            ]
        }
        result = mock_coverage_runner._process_function_coverage(coverage_data)
        assert len(result) == 1
        func = result[0]
        # Lines 1-5 (5) + lines 200-205 from nested macro (6) = 11
        assert func.total_lines == 11
        assert func.covered_lines == 11

    def test_circular_macro_reference_prevented(self, mock_coverage_runner):
        """Circular macro references should not cause infinite recursion."""
        # MACRO_A at line 10 -> MACRO_B at line 100 -> MACRO_A at line 10 (circular!)
        total_lines: set[int] = set()
        covered_lines: set[int] = set()

        expansion_map = {
            ("test.c", 10, 1, 10, 20): [
                [100, 1, 100, 15, 5, 0, 0, REGION_KIND_EXPANSION],  # -> MACRO_B
            ],
            ("test.c", 100, 1, 100, 15): [
                [50, 1, 52, 1, 10, 0, 0, REGION_KIND_CODE],  # some code
                [10, 1, 10, 20, 5, 0, 0, REGION_KIND_EXPANSION],  # -> MACRO_A (circular)
            ],
        }
        coord_to_filenames = {
            (10, 1, 10, 20): ["test.c"],
            (100, 1, 100, 15): ["test.c"],
        }

        # Process MACRO_A - should not infinite loop
        mock_coverage_runner._process_expansion_lines(
            expansion_map[("test.c", 10, 1, 10, 20)],
            total_lines,
            covered_lines,
            expansion_map,
            coord_to_filenames,
            {"test.c"},
            {},
        )

        # Should have processed lines 50-52 from MACRO_B, but not loop back
        assert total_lines == {50, 51, 52}
        assert covered_lines == {50, 51, 52}

    def test_mixed_regions_in_expansion(self, mock_coverage_runner):
        """Expansion with both CodeRegions and nested ExpansionRegions."""
        total_lines: set[int] = set()
        covered_lines: set[int] = set()

        expansion_map = {
            ("test.c", 10, 1, 10, 20): [
                [100, 1, 102, 1, 5, 0, 0, REGION_KIND_CODE],  # direct code
                [110, 1, 110, 10, 0, 0, 0, REGION_KIND_EXPANSION],  # nested macro
                [120, 1, 122, 1, 5, 0, 0, REGION_KIND_CODE],  # more direct code
            ],
            ("test.c", 110, 1, 110, 10): [
                [200, 1, 203, 1, 10, 0, 0, REGION_KIND_CODE],  # nested macro body
            ],
        }
        coord_to_filenames = {
            (10, 1, 10, 20): ["test.c"],
            (110, 1, 110, 10): ["test.c"],
        }

        mock_coverage_runner._process_expansion_lines(
            expansion_map[("test.c", 10, 1, 10, 20)],
            total_lines,
            covered_lines,
            expansion_map,
            coord_to_filenames,
            {"test.c"},
            {},
        )

        # Lines 100-102 (3) + lines 200-203 from nested (4) + lines 120-122 (3) = 10
        assert total_lines == {100, 101, 102, 120, 121, 122, 200, 201, 202, 203}
        assert covered_lines == {100, 101, 102, 120, 121, 122, 200, 201, 202, 203}

    def test_deeply_nested_macros(self, mock_coverage_runner):
        """Three levels of macro nesting: A -> B -> C -> code."""
        total_lines: set[int] = set()
        covered_lines: set[int] = set()

        expansion_map = {
            ("test.c", 10, 1, 10, 10): [
                [100, 1, 100, 10, 0, 0, 0, REGION_KIND_EXPANSION],  # -> B
            ],
            ("test.c", 100, 1, 100, 10): [
                [200, 1, 200, 10, 0, 0, 0, REGION_KIND_EXPANSION],  # -> C
            ],
            ("test.c", 200, 1, 200, 10): [
                [300, 1, 305, 1, 5, 0, 0, REGION_KIND_CODE],  # final code
            ],
        }
        coord_to_filenames = {
            (10, 1, 10, 10): ["test.c"],
            (100, 1, 100, 10): ["test.c"],
            (200, 1, 200, 10): ["test.c"],
        }

        mock_coverage_runner._process_expansion_lines(
            expansion_map[("test.c", 10, 1, 10, 10)],
            total_lines,
            covered_lines,
            expansion_map,
            coord_to_filenames,
            {"test.c"},
            {},
        )

        # Only lines 300-305 from the innermost macro
        assert total_lines == {300, 301, 302, 303, 304, 305}
        assert covered_lines == {300, 301, 302, 303, 304, 305}

    def test_empty_nested_expansion(self, mock_coverage_runner):
        """Nested expansion that expands to nothing."""
        total_lines: set[int] = set()
        covered_lines: set[int] = set()

        expansion_map = {
            ("test.c", 10, 1, 10, 10): [
                [100, 1, 100, 10, 0, 0, 0, REGION_KIND_EXPANSION],  # -> empty macro
            ],
            ("test.c", 100, 1, 100, 10): [],  # empty expansion
        }
        coord_to_filenames = {
            (10, 1, 10, 10): ["test.c"],
            (100, 1, 100, 10): ["test.c"],
        }

        mock_coverage_runner._process_expansion_lines(
            expansion_map[("test.c", 10, 1, 10, 10)],
            total_lines,
            covered_lines,
            expansion_map,
            coord_to_filenames,
            {"test.c"},
            {},
        )

        # Should add nothing
        assert total_lines == set()
        assert covered_lines == set()
