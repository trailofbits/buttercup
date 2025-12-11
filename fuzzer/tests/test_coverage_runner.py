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
        """Returns empty map when no files."""
        export_obj = {"files": []}
        result = mock_coverage_runner._build_expansion_coverage_map(export_obj)
        assert result == {}

    def test_no_expansions(self, mock_coverage_runner):
        """Returns empty map when files have no expansions."""
        export_obj = {"files": [{"filename": "test.c"}]}
        result = mock_coverage_runner._build_expansion_coverage_map(export_obj)
        assert result == {}

    def test_expansion_with_code_regions_covered(self, mock_coverage_runner):
        """Expansion with covered CodeRegions returns (True, True)."""
        export_obj = {
            "files": [
                {
                    "filename": "test.c",
                    "expansions": [
                        {
                            "source_region": [10, 5, 10, 20],  # macro call location
                            "target_regions": [
                                [1, 1, 3, 1, 5, 0, 0, REGION_KIND_CODE],  # covered
                            ],
                        }
                    ],
                }
            ]
        }
        result = mock_coverage_runner._build_expansion_coverage_map(export_obj)
        key = (10, 5, 10, 20)
        assert key in result
        assert result[key] == (True, True)

    def test_expansion_with_code_regions_uncovered(self, mock_coverage_runner):
        """Expansion with uncovered CodeRegions returns (True, False)."""
        export_obj = {
            "files": [
                {
                    "filename": "test.c",
                    "expansions": [
                        {
                            "source_region": [10, 5, 10, 20],
                            "target_regions": [
                                [1, 1, 3, 1, 0, 0, 0, REGION_KIND_CODE],  # uncovered
                            ],
                        }
                    ],
                }
            ]
        }
        result = mock_coverage_runner._build_expansion_coverage_map(export_obj)
        key = (10, 5, 10, 20)
        assert key in result
        assert result[key] == (True, False)

    def test_expansion_with_only_non_code_regions(self, mock_coverage_runner):
        """Expansion with only non-CodeRegions returns (False, False)."""
        export_obj = {
            "files": [
                {
                    "filename": "test.c",
                    "expansions": [
                        {
                            "source_region": [10, 5, 10, 20],
                            "target_regions": [
                                [1, 1, 3, 1, 5, 0, 0, REGION_KIND_GAP],
                                [1, 1, 3, 1, 5, 0, 0, REGION_KIND_BRANCH],
                            ],
                        }
                    ],
                }
            ]
        }
        result = mock_coverage_runner._build_expansion_coverage_map(export_obj)
        key = (10, 5, 10, 20)
        assert key in result
        assert result[key] == (False, False)

    def test_expansion_empty_target_regions(self, mock_coverage_runner):
        """Expansion with empty target_regions returns (False, False)."""
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
        result = mock_coverage_runner._build_expansion_coverage_map(export_obj)
        key = (10, 5, 10, 20)
        assert key in result
        assert result[key] == (False, False)

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
        result = mock_coverage_runner._build_expansion_coverage_map(export_obj)
        assert result == {}

    def test_malformed_target_region_skipped(self, mock_coverage_runner):
        """Target regions with too few fields are skipped."""
        export_obj = {
            "files": [
                {
                    "filename": "test.c",
                    "expansions": [
                        {
                            "source_region": [10, 5, 10, 20],
                            "target_regions": [
                                [1, 1, 3],  # too short, skipped
                                [1, 1, 3, 1, 5, 0, 0, REGION_KIND_CODE],  # valid
                            ],
                        }
                    ],
                }
            ]
        }
        result = mock_coverage_runner._build_expansion_coverage_map(export_obj)
        key = (10, 5, 10, 20)
        assert key in result
        assert result[key] == (True, True)


class TestProcessRegions:
    """Tests for _process_regions method."""

    def test_empty_regions(self, mock_coverage_runner):
        """Empty regions list produces empty sets."""
        total_lines: set[int] = set()
        covered_lines: set[int] = set()
        mock_coverage_runner._process_regions([], total_lines, covered_lines, {})
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
        mock_coverage_runner._process_regions(regions, total_lines, covered_lines, {})
        assert total_lines == {1, 2, 3, 4, 5, 6, 7, 8}
        assert covered_lines == {1, 2, 3, 4, 5}

    def test_expansion_region_with_code(self, mock_coverage_runner):
        """ExpansionRegion with CodeRegions adds 1 line."""
        total_lines: set[int] = set()
        covered_lines: set[int] = set()
        regions = [
            [10, 5, 10, 20, 0, 0, 0, REGION_KIND_EXPANSION],
        ]
        expansion_coverage = {(10, 5, 10, 20): (True, True)}  # has code, is covered
        mock_coverage_runner._process_regions(regions, total_lines, covered_lines, expansion_coverage)
        assert total_lines == {10}
        assert covered_lines == {10}

    def test_expansion_region_uncovered(self, mock_coverage_runner):
        """ExpansionRegion with uncovered CodeRegions adds to total but not covered."""
        total_lines: set[int] = set()
        covered_lines: set[int] = set()
        regions = [
            [10, 5, 10, 20, 0, 0, 0, REGION_KIND_EXPANSION],
        ]
        expansion_coverage = {(10, 5, 10, 20): (True, False)}  # has code, not covered
        mock_coverage_runner._process_regions(regions, total_lines, covered_lines, expansion_coverage)
        assert total_lines == {10}
        assert covered_lines == set()

    def test_expansion_region_no_code(self, mock_coverage_runner):
        """ExpansionRegion without CodeRegions adds nothing."""
        total_lines: set[int] = set()
        covered_lines: set[int] = set()
        regions = [
            [10, 5, 10, 20, 0, 0, 0, REGION_KIND_EXPANSION],
        ]
        expansion_coverage = {(10, 5, 10, 20): (False, False)}  # no code
        mock_coverage_runner._process_regions(regions, total_lines, covered_lines, expansion_coverage)
        assert total_lines == set()
        assert covered_lines == set()

    def test_expansion_region_not_in_map(self, mock_coverage_runner):
        """ExpansionRegion not in map is treated as no code."""
        total_lines: set[int] = set()
        covered_lines: set[int] = set()
        regions = [
            [10, 5, 10, 20, 0, 0, 0, REGION_KIND_EXPANSION],
        ]
        mock_coverage_runner._process_regions(regions, total_lines, covered_lines, {})
        assert total_lines == set()
        assert covered_lines == set()

    def test_skipped_regions_ignored(self, mock_coverage_runner):
        """SkippedRegion adds nothing."""
        total_lines: set[int] = set()
        covered_lines: set[int] = set()
        regions = [
            [1, 1, 100, 1, 0, 0, 0, REGION_KIND_SKIPPED],
        ]
        mock_coverage_runner._process_regions(regions, total_lines, covered_lines, {})
        assert total_lines == set()
        assert covered_lines == set()

    def test_gap_regions_ignored(self, mock_coverage_runner):
        """GapRegion adds nothing."""
        total_lines: set[int] = set()
        covered_lines: set[int] = set()
        regions = [
            [1, 1, 100, 1, 0, 0, 0, REGION_KIND_GAP],
        ]
        mock_coverage_runner._process_regions(regions, total_lines, covered_lines, {})
        assert total_lines == set()
        assert covered_lines == set()

    def test_branch_regions_ignored(self, mock_coverage_runner):
        """BranchRegion adds nothing."""
        total_lines: set[int] = set()
        covered_lines: set[int] = set()
        regions = [
            [1, 1, 100, 1, 50, 0, 0, REGION_KIND_BRANCH],
        ]
        mock_coverage_runner._process_regions(regions, total_lines, covered_lines, {})
        assert total_lines == set()
        assert covered_lines == set()

    def test_mcdc_decision_regions_ignored(self, mock_coverage_runner):
        """MCDCDecisionRegion adds nothing."""
        total_lines: set[int] = set()
        covered_lines: set[int] = set()
        regions = [
            [1, 1, 100, 1, 0, 0, 0, REGION_KIND_MCDC_DECISION],
        ]
        mock_coverage_runner._process_regions(regions, total_lines, covered_lines, {})
        assert total_lines == set()
        assert covered_lines == set()

    def test_mcdc_branch_regions_ignored(self, mock_coverage_runner):
        """MCDCBranchRegion adds nothing."""
        total_lines: set[int] = set()
        covered_lines: set[int] = set()
        regions = [
            [1, 1, 100, 1, 0, 0, 0, REGION_KIND_MCDC_BRANCH],
        ]
        mock_coverage_runner._process_regions(regions, total_lines, covered_lines, {})
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
        mock_coverage_runner._process_regions(regions, total_lines, covered_lines, {})
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
        runner._process_regions([region], total_lines, covered_lines, {})
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
        runner._process_regions(regions, total_lines, covered_lines, {})

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
            runner._process_regions(regions, total_lines, covered_lines, {})

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
        runner._process_regions([region], total_lines, covered_lines, {})
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
        runner._process_regions([region], total_lines, covered_lines, {})
        assert len(covered_lines) == 0
        assert len(total_lines) == line_span + 1

    @given(
        has_code=st.booleans(),
        is_covered=st.booleans(),
        line=st.integers(min_value=1, max_value=1000),
    )
    @settings(max_examples=50)
    def test_expansion_coverage_consistency(self, has_code, is_covered, line):
        """ExpansionRegion coverage follows expansion_coverage map logic."""
        runner = create_mock_coverage_runner()
        # If is_covered is True but has_code is False, that's an invalid state
        # the implementation handles this by only checking is_covered when has_code is True
        if is_covered and not has_code:
            is_covered = False

        total_lines: set[int] = set()
        covered_lines: set[int] = set()
        key = (line, 1, line, 10)
        expansion_coverage = {key: (has_code, is_covered)}
        regions = [[line, 1, line, 10, 0, 0, 0, REGION_KIND_EXPANSION]]

        runner._process_regions(regions, total_lines, covered_lines, expansion_coverage)

        if has_code:
            assert line in total_lines
            if is_covered:
                assert line in covered_lines
            else:
                assert line not in covered_lines
        else:
            assert line not in total_lines
            assert line not in covered_lines


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
        """Function with macro calls should count macro call sites correctly."""
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
        # Lines 1-3 (3) + line 4 (macro, 1) + lines 5-7 (3) = 7
        assert result[0].total_lines == 7
        assert result[0].covered_lines == 7

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
