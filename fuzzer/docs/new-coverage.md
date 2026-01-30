# Uncovered Lines Tracking v2

This document describes the changes to coverage tracking introduced in v2, which improves how uncovered lines are tracked for functions that use macros or have code spanning multiple files.

## Problem with Original Implementation

The original implementation mixed line numbers from different files into a single set:

```python
# Old CoveredFunction
CoveredFunction:
    total_line_set: {2, 3, 4, 5, 6, 8, 9, 12, 13}  # Lines from BOTH foo.c AND macros.h
    covered_line_set: {2, 5, 6, 8, 9}
    function_start_line: 2   # Could be from macro file!
    function_end_line: 13
```

**Issues:**
1. Line numbers from different files were mixed together
2. `function_start_line` could come from a macro header, not the actual function
3. When an LLM saw "uncovered lines 3-4", it couldn't know which file those lines were in
4. Container paths from LLVM (e.g., `/src/libpng/png.h`) don't map to task paths

## v2 Solution: Per-File Tracking

### New Data Structures

#### FileLineCoverage
Tracks coverage for a single file:

```python
@dataclass
class FileLineCoverage:
    file_id: int
    file_path: str          # Container path from coverage
    total_lines: set[int]
    covered_lines: set[int]
    is_primary: bool        # True if this is the function definition file
```

#### MacroCallSite
Tracks where macros with uncovered code are called:

```python
@dataclass
class MacroCallSite:
    call_line: int              # Line in primary file where macro is called
    macro_file_path: str        # File where macro is defined
    uncovered_line_count: int   # How many lines inside macro are uncovered
```

#### Updated CoveredFunction
```python
@dataclass
class CoveredFunction:
    names: str
    total_lines: int           # Aggregate count (unchanged)
    covered_lines: int         # Aggregate count (unchanged)
    function_paths: list[str]

    # Existing fields (for backwards compatibility)
    total_line_set: set[int] | None
    covered_line_set: set[int] | None
    function_start_line: int | None
    function_end_line: int | None

    # NEW: Per-file tracking
    file_coverage: list[FileLineCoverage] | None
    primary_file_id: int | None
    macro_call_sites: list[MacroCallSite] | None
```

### Protobuf Changes

New messages in `msg.proto`:

```protobuf
message MacroCallSite {
    uint32 call_line = 1;        // Line in primary file where macro is called
    string macro_file_path = 2;  // File where macro is defined
    uint32 uncovered_count = 3;  // Lines inside macro that are uncovered
}

message UncoveredLines {
    repeated uint32 starts = 1 [packed = true];
    repeated uint32 lengths = 2 [packed = true];
    uint32 function_start_line = 3;
    uint32 function_end_line = 4;
}

message FunctionUncoveredLines {
    string function_name = 1;
    repeated string function_paths = 2;
    string primary_file_path = 3;      // Renamed from file_path
    uint32 total_lines = 4;
    uint32 covered_lines = 5;
    UncoveredLines uncovered = 6;      // Uncovered lines in PRIMARY file only
    repeated MacroCallSite macro_sites = 7;  // Macro call sites with uncovered code
}
```

### Key Changes

#### 1. Primary File Identification

The primary file (where the function is defined) is identified by:
- File with the most `REGION_KIND_CODE` regions
- Preference for `.c/.cpp` files over `.h/.hpp` as tiebreaker

```python
def find_primary_file(regions: list, filenames: list[str]) -> int:
    """Find the file_id of the primary file."""
    code_region_counts: dict[int, int] = {}

    for region in regions:
        if region[7] == REGION_KIND_CODE:
            file_id = region[5]
            code_region_counts[file_id] = code_region_counts.get(file_id, 0) + 1

    def file_sort_key(fid):
        count = code_region_counts[fid]
        is_source = filenames[fid].endswith(('.c', '.cpp', '.cc', '.cxx'))
        return (count, is_source)

    return max(code_region_counts.keys(), key=file_sort_key)
```

#### 2. Per-File Region Processing

CODE regions are now grouped by their `file_id`:

```python
for region in regions:
    if kind == REGION_KIND_CODE:
        file_id = region[5]
        # Track in file-specific sets
        if file_id not in lines_by_file:
            lines_by_file[file_id] = (set(), set())
        file_total, file_covered = lines_by_file[file_id]
        self._add_region_lines(region, file_total, file_covered)
```

#### 3. Macro Call Site Tracking

EXPANSION regions are processed to track call sites with uncovered code:

```python
elif kind == REGION_KIND_EXPANSION:
    # Get expansion lines (still needed for aggregate counts)
    exp_total, exp_covered = self._get_expansion_lines(...)

    # Track as macro call site if has uncovered code
    uncovered_count = len(exp_total - exp_covered)
    if uncovered_count > 0:
        macro_call_sites.append(MacroCallSite(
            call_line=region[0],
            macro_file_path=expansion_file_path,
            uncovered_line_count=uncovered_count,
        ))
```

#### 4. Redis Storage

`FunctionUncoveredLines` now stores:
- `primary_file_path`: The actual function definition file
- `uncovered`: Only lines from the primary file
- `macro_sites`: List of macro call sites with uncovered code

## Example

Consider a function `process_data()` in `foo.c` that calls a macro `CHECK_NULL()` from `macros.h`:

### Old Model
```
uncovered.starts: [3, 4, 12, 13]  <- Lines 3-4 are from macros.h!
```
Problem: LLM looks at foo.c lines 3-4 but they don't match.

### New Model
```
primary_file_path: '/src/foo.c'
uncovered.starts: [12, 13]        <- Only lines from foo.c
macro_sites: [
    MacroCallSite(call_line=6, macro_file_path='/src/macros.h', uncovered_count=2)
]
```
Benefit: LLM knows lines 12-13 are in foo.c, and line 6 has a macro with uncovered code.

## Backwards Compatibility

- Aggregate `total_lines` and `covered_lines` counts still include expansion lines
- `total_line_set` and `covered_line_set` still contain mixed lines (for existing code)
- New fields (`file_coverage`, `primary_file_id`, `macro_call_sites`) are `None` when coverage is 0% or 100%

## New Files

- `common/src/buttercup/common/coverage_utils.py`: `UncoveredRanges` class for line set ↔ protobuf conversion
- `common/src/buttercup/common/maps.py`: Added `UncoveredLinesMap` for Redis storage

## Usage for LLM Guidance

The seed-gen component can now provide the LLM with:
1. Function source from program model (avoids path mapping issues)
2. Which lines in the function body are uncovered (from primary file)
3. Which macro calls have uncovered code (call site + count)

This enables targeted input generation to reach specific uncovered paths.
