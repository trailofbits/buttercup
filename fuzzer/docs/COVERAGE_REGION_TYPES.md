# LLVM Coverage Region Types and Coverage Computation

This document describes how the coverage-bot processes LLVM source-based code coverage data, specifically how region types affect the accuracy of coverage metrics.

## Motivation

The original implementation treated all coverage regions identically, which led to inaccurate coverage metrics:

1. **SkippedRegions** (code inside unmet `#ifdef` conditions) were counted as reachable lines, even though they were never compiled into the binary
2. **GapRegions** (whitespace/formatting between code blocks) inflated line counts
3. **BranchRegions** added metadata lines that overlap with actual code lines
4. **Macro expansions** were not properly handled - either ignored entirely or double-counted

The updated implementation filters regions by type to compute accurate coverage: `covered_lines / reachable_lines` where `reachable_lines` only includes code that can actually be executed.

## LLVM Coverage Region Types

LLVM defines 7 region types in `CoverageMapping.h`:

| Kind | Value | Description | Counted as Reachable? |
|------|-------|-------------|----------------------|
| CodeRegion | 0 | Associates code with an execution counter | **YES** - all lines counted |
| ExpansionRegion | 1 | Macro instantiation or #include file | **YES** - as 1 line if has CodeRegions |
| SkippedRegion | 2 | Preprocessor-skipped code (#ifdef) | NO - never compiled |
| GapRegion | 3 | Whitespace/formatting gaps | NO - not real code |
| BranchRegion | 4 | Branch condition tracking (true/false) | NO - overlaps with CodeRegions |
| MCDCDecisionRegion | 5 | MC/DC top-level boolean | NO - metadata only |
| MCDCBranchRegion | 6 | MC/DC branch with control flow IDs | NO - metadata only |

## JSON Export Format

The `llvm-cov export -format=text` command produces JSON with regions in this format:

```
[lineStart, colStart, lineEnd, colEnd, executionCount, fileID, expandedFileID, regionKind]
```

- **Index 7** (`regionKind`) identifies the region type (0-6)
- Older LLVM versions may not include all 8 fields; we default to CodeRegion for backwards compatibility

## How Each Region Type is Handled

### CodeRegion (kind=0)

Standard executable code. All lines in the region are counted as reachable. Lines with `execution_count > 0` are counted as covered.

### ExpansionRegion (kind=1)

Macro call sites. These are pointers to expanded content, not executable code themselves. The expanded content's CodeRegions are stored separately in `files[].expansions[].target_regions`.

**Our approach**: Count the macro call as ONE reachable line (the start line of the macro invocation). If ANY CodeRegion in the expansion's target_regions has `execution_count > 0`, count that line as covered.

**Rationale**: This avoids inflating line counts with macro internals while still tracking whether macro code was exercised.

**Example**:
```c
void foo() {
    int x = 1;        // Line 1: CodeRegion - counted
    MY_MACRO(x);      // Line 2: ExpansionRegion - 1 reachable line
    int y = 2;        // Line 3: CodeRegion - counted
}
```
If `MY_MACRO` expands to 5 lines of code, we count 3 total lines (not 8).

### SkippedRegion (kind=2)

Code that was skipped by the preprocessor (e.g., inside `#ifdef DEBUG` when DEBUG is not defined). These lines were never compiled into the binary and cannot be executed.

**Our approach**: Completely excluded from coverage counts.

### GapRegion (kind=3)

Formatting gaps between code regions. These only affect line execution count when they're the sole region on a line.

**Our approach**: Excluded from coverage counts - they don't represent executable code.

### BranchRegion (kind=4)

Leaf-level boolean expressions with separate true/false counters. These can occupy the same source locations as CodeRegions.

**Our approach**: Excluded - the underlying CodeRegion already covers the line. BranchRegions provide branch coverage metadata, not additional executable lines.

### MCDCDecisionRegion (kind=5) and MCDCBranchRegion (kind=6)

Modified Condition/Decision Coverage metadata for advanced coverage analysis.

**Our approach**: Excluded - these are metadata regions, not executable code.

## Zero Counters and Unreachable Code

LLVM uses a "zero counter" encoding internally to mark statically unreachable code (e.g., code after a `return` statement). However, in the JSON export, both unreachable code and never-executed code appear identically as `execution_count = 0`. The original counter tag information is lost.

**Implication**: We cannot distinguish between "code that was never executed" and "code that cannot be executed" from the JSON export alone. Both are counted as reachable lines with 0 coverage. This is an accepted limitation of the export format.

## Implementation Details

The coverage processing flow:

1. **Build expansion coverage map**: Pre-process `files[].expansions[]` to determine which expansions contain CodeRegions and whether any are covered
2. **Process function regions**: For each region in `function["regions"]`:
   - CodeRegion: Add all lines to totals
   - ExpansionRegion: Look up in map; if has CodeRegions, add 1 line
   - Other kinds: Skip
3. **Compute metrics**: `total_lines` (reachable) and `covered_lines` (executed)

## References

- [LLVM CoverageMapping.h](https://llvm.org/doxygen/structllvm_1_1coverage_1_1CounterMappingRegion.html)
- [LLVM Coverage Mapping Format](https://llvm.org/docs/CoverageMappingFormat.html)
- [Clang Source-Based Code Coverage](https://clang.llvm.org/docs/SourceBasedCodeCoverage.html)
- [llvm-cov Command Guide](https://llvm.org/docs/CommandGuide/llvm-cov.html)
