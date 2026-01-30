# Precise Coverage Hierarchy for LLM Guidance

This document describes a hierarchical coverage representation designed to guide LLMs in generating inputs that target specific uncovered code paths.

## Scope

This feature applies only to **functions with partial coverage** (0 < covered_lines < total_lines). Functions with 0% or 100% coverage are excluded:
- **0% coverage**: Function never executed - need to find how to call it first
- **100% coverage**: Nothing to improve
- **Partial coverage**: Has uncovered paths we can target with specific inputs

## Problem Statement

The current flat representation of uncovered lines is insufficient for LLM guidance:

```
Uncovered lines: [48-52, 104-106, 965-970]
```

Problems:
1. **No context**: What do these lines do? Why aren't they covered?
2. **Mixed sources**: Lines may come from different files (macros, includes)
3. **No structure**: Can't tell if line 104 is inside a macro called from line 50
4. **No actionability**: How should the LLM trigger these paths?

## Solution: Coverage Hierarchy

Represent coverage as a tree that mirrors the code's macro expansion structure:

```
Function: png_read_end (pngread.c:912-987)
│
├─ CodeBlock [912-915] ✓ covered
│
├─ MacroExpansion: PNG_SETJMP() at line 916
│   ├─ CodeBlock [pngpriv.h:45-47] ✓ covered
│   └─ CodeBlock [pngpriv.h:48-52] ✗ UNCOVERED
│
├─ CodeBlock [917-925] ✓ covered
│
├─ MacroExpansion: png_crc_finish() at line 926
│   ├─ CodeBlock [png.c:230-235] ✓ covered
│   ├─ MacroExpansion: PNG_CRC_CHECK() at png.c:236
│   │   ├─ CodeBlock [pngpriv.h:102-103] ✓ covered
│   │   └─ CodeBlock [pngpriv.h:104-106] ✗ UNCOVERED
│   └─ CodeBlock [png.c:237-240] ✓ covered
│
└─ CodeBlock [927-987] partial
    └─ Lines 965-970 ✗ UNCOVERED
```

## LLVM Coverage Background

### Region Format
```
[lineStart, colStart, lineEnd, colEnd, execCount, fileID, expandedFileID, kind]
```

- **fileID**: Index into the function's `filenames` array (per-function, not global)
- **expandedFileID**: For ExpansionRegions, points to file containing macro body
- **kind**: 0=Code, 1=Expansion, 2=Skipped, 3=Gap, 4+=Branch/MCDC

### Expansion Hierarchy in LLVM

1. Function's `regions` array contains CodeRegions and ExpansionRegions
2. ExpansionRegion marks WHERE a macro is called (call site)
3. `expandedFileID` tells us which file contains the macro body
4. Actual macro body regions are in `files[].expansions[].target_regions`
5. Macro bodies can contain nested ExpansionRegions (recursive)

## Data Model

### Python Classes

```python
@dataclass
class CodeBlock:
    """A contiguous block of non-macro code."""
    file_path: str
    start_line: int
    end_line: int
    covered_lines: set[int]
    total_lines: set[int]

    @property
    def uncovered_lines(self) -> set[int]:
        return self.total_lines - self.covered_lines

    @property
    def is_fully_covered(self) -> bool:
        return len(self.uncovered_lines) == 0

    @property
    def coverage_fraction(self) -> float:
        if not self.total_lines:
            return 1.0
        return len(self.covered_lines) / len(self.total_lines)


@dataclass
class MacroExpansion:
    """A macro call site with its expansion hierarchy."""
    call_file: str
    call_line: int
    call_column: int
    macro_file: str  # From expandedFileID
    children: list["CoverageNode"]

    def total_uncovered_lines(self) -> int:
        """Recursively count uncovered lines in this expansion tree."""
        count = 0
        for child in self.children:
            if isinstance(child, CodeBlock):
                count += len(child.uncovered_lines)
            elif isinstance(child, MacroExpansion):
                count += child.total_uncovered_lines()
        return count

    def has_uncovered_code(self) -> bool:
        return self.total_uncovered_lines() > 0


# Type alias for tree nodes
CoverageNode = CodeBlock | MacroExpansion


@dataclass
class FunctionCoverageHierarchy:
    """Complete coverage hierarchy for a partially-covered function."""
    function_name: str
    primary_file: str
    start_line: int
    end_line: int
    total_lines: int
    covered_lines: int
    children: list[CoverageNode]

    @property
    def coverage_percentage(self) -> float:
        return (self.covered_lines / self.total_lines * 100) if self.total_lines else 0

    def iter_uncovered_paths(self) -> Iterator[tuple[list[str], CodeBlock]]:
        """Yield (path, code_block) for each uncovered code block.

        Path is like ["png_read_end", "PNG_SETJMP() at line 916", "pngpriv.h:48-52"]
        """
        yield from self._iter_uncovered(self.children, [self.function_name])

    def _iter_uncovered(self, nodes, path):
        for node in nodes:
            if isinstance(node, CodeBlock):
                if not node.is_fully_covered:
                    yield (path + [f"{node.file_path}:{node.start_line}-{node.end_line}"], node)
            elif isinstance(node, MacroExpansion):
                if node.has_uncovered_code():
                    macro_path = path + [f"{node.macro_file} at {node.call_file}:{node.call_line}"]
                    yield from self._iter_uncovered(node.children, macro_path)
```

### Protobuf Messages

```protobuf
// Coverage hierarchy for LLM guidance (only for partial coverage functions)

message CodeBlock {
    string file_path = 1;
    uint32 start_line = 2;
    uint32 end_line = 3;
    // Run-length encoded line coverage within block
    repeated uint32 covered_starts = 4 [packed = true];
    repeated uint32 covered_lengths = 5 [packed = true];
    repeated uint32 uncovered_starts = 6 [packed = true];
    repeated uint32 uncovered_lengths = 7 [packed = true];
}

message MacroExpansion {
    string call_file = 1;
    uint32 call_line = 2;
    uint32 call_column = 3;
    string macro_file = 4;
    repeated CoverageNode children = 5;
}

message CoverageNode {
    oneof node {
        CodeBlock code = 1;
        MacroExpansion macro = 2;
    }
}

message FunctionCoverageHierarchy {
    string function_name = 1;
    string primary_file = 2;
    uint32 start_line = 3;
    uint32 end_line = 4;
    uint32 total_lines = 5;
    uint32 covered_lines = 6;
    repeated CoverageNode children = 7;
}
```

## Algorithm

### Building the Hierarchy

```python
def build_coverage_hierarchy(
    function: dict,
    file_expansions: dict[str, list],
) -> FunctionCoverageHierarchy | None:
    """Build hierarchical coverage for a function.

    Args:
        function: Function object from LLVM coverage JSON
        file_expansions: Map of filename -> list of expansion objects

    Returns:
        FunctionCoverageHierarchy for partial coverage, None otherwise
    """
    filenames = function['filenames']
    regions = function['regions']

    # Calculate aggregate coverage
    total_lines, covered_lines = count_all_lines(regions, filenames, file_expansions)

    # Skip if not partial coverage
    if covered_lines == 0 or covered_lines == total_lines:
        return None

    # Find primary file (where function is defined)
    primary_file_id = find_primary_file(regions, filenames)
    primary_file = filenames[primary_file_id]

    # Build the tree starting from primary file regions
    children = build_node_tree(
        regions=[r for r in regions if r[5] == primary_file_id],
        all_regions=regions,
        filenames=filenames,
        file_expansions=file_expansions,
    )

    # Compute function bounds from primary file
    primary_regions = [r for r in regions if r[5] == primary_file_id and r[7] == CODE_REGION]
    start_line = min(r[0] for r in primary_regions) if primary_regions else 0
    end_line = max(r[2] for r in primary_regions) if primary_regions else 0

    return FunctionCoverageHierarchy(
        function_name=function['name'],
        primary_file=primary_file,
        start_line=start_line,
        end_line=end_line,
        total_lines=total_lines,
        covered_lines=covered_lines,
        children=children,
    )


def build_node_tree(
    regions: list,
    all_regions: list,
    filenames: list[str],
    file_expansions: dict[str, list],
) -> list[CoverageNode]:
    """Build tree of CoverageNodes from regions.

    Regions should be pre-filtered to a specific file_id.
    """
    # Sort by start position
    sorted_regions = sorted(regions, key=lambda r: (r[0], r[1]))

    nodes: list[CoverageNode] = []
    pending_code_lines: dict[int, bool] = {}  # line -> is_covered

    for region in sorted_regions:
        kind = region[7] if len(region) > 7 else CODE_REGION

        if kind == CODE_REGION:
            # Accumulate code lines
            exec_count = region[4]
            for line in range(region[0], region[2] + 1):
                if line not in pending_code_lines:
                    pending_code_lines[line] = (exec_count > 0)
                else:
                    # Line is covered if ANY region covering it is executed
                    pending_code_lines[line] |= (exec_count > 0)

        elif kind == EXPANSION_REGION:
            # Flush pending code block before macro
            if pending_code_lines:
                nodes.append(make_code_block(filenames[region[5]], pending_code_lines))
                pending_code_lines = {}

            # Build macro expansion node
            file_id = region[5]
            expanded_file_id = region[6]

            # Look up expansion's target regions
            target_regions = lookup_expansion(
                file_expansions,
                filenames[file_id],
                (region[0], region[1], region[2], region[3])
            )

            # Recursively build children from target regions
            macro_children = build_expansion_tree(
                target_regions,
                filenames,
                file_expansions,
            )

            nodes.append(MacroExpansion(
                call_file=filenames[file_id],
                call_line=region[0],
                call_column=region[1],
                macro_file=filenames[expanded_file_id] if expanded_file_id < len(filenames) else "unknown",
                children=macro_children,
            ))

    # Flush remaining code
    if pending_code_lines:
        file_id = sorted_regions[0][5] if sorted_regions else 0
        nodes.append(make_code_block(filenames[file_id], pending_code_lines))

    return nodes


def build_expansion_tree(
    target_regions: list,
    filenames: list[str],
    file_expansions: dict[str, list],
    visited: set[tuple] | None = None,
) -> list[CoverageNode]:
    """Recursively build tree from expansion target regions."""
    if visited is None:
        visited = set()

    nodes: list[CoverageNode] = []
    pending_code_lines: dict[int, bool] = {}
    current_file_id = None

    for region in target_regions:
        if len(region) < 5:
            continue

        kind = region[7] if len(region) > 7 else CODE_REGION
        file_id = region[5] if len(region) > 5 else 0

        # Track file changes
        if current_file_id is None:
            current_file_id = file_id
        elif file_id != current_file_id:
            # Flush code block when switching files
            if pending_code_lines and current_file_id < len(filenames):
                nodes.append(make_code_block(filenames[current_file_id], pending_code_lines))
                pending_code_lines = {}
            current_file_id = file_id

        if kind == CODE_REGION:
            exec_count = region[4]
            for line in range(region[0], region[2] + 1):
                if line not in pending_code_lines:
                    pending_code_lines[line] = (exec_count > 0)
                else:
                    pending_code_lines[line] |= (exec_count > 0)

        elif kind == EXPANSION_REGION:
            # Prevent infinite recursion
            region_key = (file_id, region[0], region[1], region[2], region[3])
            if region_key in visited:
                continue
            visited.add(region_key)

            # Flush pending code
            if pending_code_lines and current_file_id < len(filenames):
                nodes.append(make_code_block(filenames[current_file_id], pending_code_lines))
                pending_code_lines = {}

            # Get nested expansion
            expanded_file_id = region[6]
            nested_targets = lookup_expansion(
                file_expansions,
                filenames[file_id] if file_id < len(filenames) else "",
                (region[0], region[1], region[2], region[3])
            )

            nested_children = build_expansion_tree(
                nested_targets,
                filenames,
                file_expansions,
                visited,
            )

            if file_id < len(filenames):
                nodes.append(MacroExpansion(
                    call_file=filenames[file_id],
                    call_line=region[0],
                    call_column=region[1],
                    macro_file=filenames[expanded_file_id] if expanded_file_id < len(filenames) else "unknown",
                    children=nested_children,
                ))

    # Flush remaining code
    if pending_code_lines and current_file_id is not None and current_file_id < len(filenames):
        nodes.append(make_code_block(filenames[current_file_id], pending_code_lines))

    return nodes


def make_code_block(file_path: str, lines: dict[int, bool]) -> CodeBlock:
    """Create a CodeBlock from accumulated line coverage data."""
    sorted_lines = sorted(lines.keys())
    return CodeBlock(
        file_path=file_path,
        start_line=min(sorted_lines),
        end_line=max(sorted_lines),
        covered_lines={ln for ln, cov in lines.items() if cov},
        total_lines=set(sorted_lines),
    )
```

## LLM Prompt Generation

### Serialization for LLM

```python
def format_hierarchy_for_llm(hierarchy: FunctionCoverageHierarchy) -> str:
    """Format coverage hierarchy as text for LLM consumption."""
    lines = [
        f"Function: {hierarchy.function_name}",
        f"Location: {hierarchy.primary_file}:{hierarchy.start_line}-{hierarchy.end_line}",
        f"Coverage: {hierarchy.coverage_percentage:.1f}% ({hierarchy.covered_lines}/{hierarchy.total_lines} lines)",
        "",
        "Code structure with uncovered paths:",
        "",
    ]

    lines.extend(format_nodes(hierarchy.children, indent=0))

    # Add summary of uncovered paths
    uncovered_paths = list(hierarchy.iter_uncovered_paths())
    if uncovered_paths:
        lines.append("")
        lines.append("Uncovered code paths to target:")
        for i, (path, block) in enumerate(uncovered_paths, 1):
            lines.append(f"  {i}. {' → '.join(path)}")
            lines.append(f"     {len(block.uncovered_lines)} uncovered lines")

    return "\n".join(lines)


def format_nodes(nodes: list[CoverageNode], indent: int) -> list[str]:
    """Recursively format nodes as indented text."""
    lines = []
    prefix = "  " * indent

    for node in nodes:
        if isinstance(node, CodeBlock):
            status = "✓" if node.is_fully_covered else "✗" if node.coverage_fraction == 0 else "◐"
            uncovered_info = ""
            if not node.is_fully_covered:
                uncovered = sorted(node.uncovered_lines)
                ranges = compress_to_ranges(uncovered)
                uncovered_info = f" [uncovered: {format_ranges(ranges)}]"

            lines.append(f"{prefix}[{node.start_line}-{node.end_line}] {status}{uncovered_info}")

        elif isinstance(node, MacroExpansion):
            status = "✗" if node.has_uncovered_code() else "✓"
            uncovered_info = ""
            if node.has_uncovered_code():
                uncovered_info = f" ({node.total_uncovered_lines()} uncovered)"

            lines.append(f"{prefix}↳ Macro at line {node.call_line} → {node.macro_file}{uncovered_info}")
            lines.extend(format_nodes(node.children, indent + 1))

    return lines
```

### Example Output

```
Function: png_read_end
Location: pngread.c:912-987
Coverage: 85.2% (184/216 lines)

Code structure with uncovered paths:

[912-915] ✓
↳ Macro at line 916 → pngpriv.h (5 uncovered)
  [45-47] ✓
  [48-52] ✗ [uncovered: 48-52]
[917-925] ✓
↳ Macro at line 926 → png.c (3 uncovered)
  [230-235] ✓
  ↳ Macro at line 236 → pngpriv.h (3 uncovered)
    [102-103] ✓
    [104-106] ✗ [uncovered: 104-106]
  [237-240] ✓
[927-964] ✓
[965-987] ◐ [uncovered: 965-970]

Uncovered code paths to target:
  1. png_read_end → pngpriv.h at pngread.c:916 → pngpriv.h:48-52
     5 uncovered lines
  2. png_read_end → png.c at pngread.c:926 → pngpriv.h at png.c:236 → pngpriv.h:104-106
     3 uncovered lines
  3. png_read_end → pngread.c:965-987
     6 uncovered lines
```

## Integration Points

### Coverage Runner
- Build hierarchy during `_process_function_coverage` for partial coverage functions
- Store in new field `coverage_hierarchy` on `CoveredFunction`

### Coverage Bot
- Serialize `FunctionCoverageHierarchy` to protobuf
- Store in Redis via new `CoverageHierarchyMap`

### Seed Generator
- Fetch hierarchy for target function
- Include formatted hierarchy in LLM prompt
- LLM can see exactly which code paths need inputs

## Benefits

1. **Actionable**: LLM sees the structure, not just line numbers
2. **Contextual**: Macro expansions show where uncovered code comes from
3. **Hierarchical**: Nested macros are properly represented
4. **Focused**: Only partial coverage functions are processed
5. **Efficient**: Tree structure avoids redundant information

## Future Enhancements

1. **Source snippets**: Include actual source code for uncovered blocks
2. **Path conditions**: Annotate what conditions lead to uncovered paths
3. **Semantic labels**: Detect common patterns (error handlers, bounds checks, etc.)
4. **Coverage delta**: Track which paths were newly covered by recent inputs
