#!/bin/bash
# Lint changed files, automatically detecting which components they belong to
# This script is optimized for AI coding assistants (Claude Code, Cursor, etc.)
#
# Features:
# - Deterministic output for reliable parsing
# - Automatic fixing without prompts
# - JSON output format for structured data
# - Clear error messages
# - Dynamic component discovery

set -e
set -o pipefail

# Parse flags
PLAIN_OUTPUT=false
OUTPUT_FORMAT="text"  # text or json

while [[ $# -gt 0 ]] && [[ "$1" == --* ]]; do
    case "$1" in
        --plain)
            PLAIN_OUTPUT=true
            shift
            ;;
        --format=json)
            OUTPUT_FORMAT="json"
            PLAIN_OUTPUT=true  # JSON implies plain
            shift
            ;;
        --format=text)
            OUTPUT_FORMAT="text"
            shift
            ;;
        *)
            echo "Unknown flag: $1" >&2
            exit 1
            ;;
    esac
done

# Parse arguments
MODE="${1:-check}"  # "check" or "fix"
shift || true

# Validate mode
if [[ "$MODE" != "check" && "$MODE" != "fix" ]]; then
    echo "Error: Invalid mode '$MODE'. Must be 'check' or 'fix'" >&2
    exit 1
fi

# Color codes for better output (disabled for plain output or non-terminal)
if [ "$PLAIN_OUTPUT" = true ] || [ ! -t 1 ]; then
    RED=''
    GREEN=''
    YELLOW=''
    BLUE=''
    NC=''
else
    RED='\033[0;31m'
    GREEN='\033[0;32m'
    YELLOW='\033[1;33m'
    BLUE='\033[0;34m'
    NC='\033[0m' # No Color
fi

# JSON output helper
json_output() {
    if [ "$OUTPUT_FORMAT" = "json" ]; then
        echo "$1"
    fi
}

# Text output helper
text_output() {
    if [ "$OUTPUT_FORMAT" = "text" ]; then
        echo -e "$1"
    fi
}

# If no files provided, exit successfully
if [ $# -eq 0 ]; then
    if [ "$OUTPUT_FORMAT" = "json" ]; then
        echo '{"status":"success","message":"No files to lint","files_processed":0}'
    else
        text_output "${YELLOW}→${NC} No files to lint"
    fi
    exit 0
fi

# Detect project root (where this script lives in ./scripts/)
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT" || {
    echo "Error: Failed to change to project root" >&2
    exit 1
}

# Dynamically discover components (any directory with pyproject.toml)
text_output "${BLUE}→${NC} Discovering components..."
COMPONENTS=""
for dir in */; do
    if [ -f "${dir}pyproject.toml" ]; then
        component="${dir%/}"
        COMPONENTS="$COMPONENTS $component"
    fi
done

if [ -z "$COMPONENTS" ]; then
    echo "Error: No components found (no directories with pyproject.toml)" >&2
    exit 1
fi

text_output "   Found components:$COMPONENTS"

# Process files and group by component
temp_dir=$(mktemp -d)
trap "rm -rf $temp_dir" EXIT

# Track statistics
total_files=$#
files_processed=0
files_skipped=0
components_checked=""

# Convert all file arguments to absolute paths and group by component
for file in "$@"; do
    # Convert to absolute path
    if [[ "$file" = /* ]]; then
        abs_file="$file"
    else
        abs_file="$(cd "$(dirname "$file")" 2>/dev/null && pwd)/$(basename "$file")" || {
            text_output "${YELLOW}⚠${NC}  Skipping non-existent file: $file"
            ((files_skipped++))
            continue
        }
    fi
    
    # Check if file exists
    if [ ! -f "$abs_file" ]; then
        text_output "${YELLOW}⚠${NC}  Skipping non-existent file: $file"
        ((files_skipped++))
        continue
    fi
    
    # Check if it's a Python file
    if [[ "$abs_file" != *.py ]] && [[ "$abs_file" != *.pyi ]]; then
        text_output "${YELLOW}⚠${NC}  Skipping non-Python file: $file"
        ((files_skipped++))
        continue
    fi
    
    # Find which component this file belongs to
    found_component=false
    for component in $COMPONENTS; do
        component_dir="$PROJECT_ROOT/$component"
        if [[ "$abs_file" == "$component_dir"/* ]]; then
            echo "$abs_file" >> "$temp_dir/$component.files"
            found_component=true
            if [[ ! " $components_checked " =~ " $component " ]]; then
                components_checked="$components_checked $component"
            fi
            break
        fi
    done
    
    if [ "$found_component" = false ]; then
        text_output "${YELLOW}⚠${NC}  Skipping file not in any component: $file"
        ((files_skipped++))
    fi
done

# Exit if no components need linting
if [ -z "$(ls -A $temp_dir 2>/dev/null)" ]; then
    if [ "$OUTPUT_FORMAT" = "json" ]; then
        echo "{\"status\":\"success\",\"message\":\"No Python files in recognized components\",\"total_files\":$total_files,\"files_skipped\":$files_skipped}"
    else
        text_output "${YELLOW}→${NC} No Python files in recognized components"
    fi
    exit 0
fi

# Function to run linting for a component
lint_component() {
    local component=$1
    local mode=$2
    local files_list="$temp_dir/$component.files"
    
    # Count files for this component
    local file_count=$(wc -l < "$files_list")
    
    text_output "${BLUE}→${NC} Linting $component ($file_count file$([ "$file_count" -eq 1 ] || echo 's'))..."
    cd "$PROJECT_ROOT/$component" || return 1
    
    # Ensure dependencies are available (check if pyproject.toml is newer than .venv)
    if [ ! -d ".venv" ] || [ "pyproject.toml" -nt ".venv" ]; then
        text_output "   ${YELLOW}↻${NC} Syncing dependencies..."
        if ! uv sync -q --all-extras 2>&1; then
            text_output "   ${RED}✗${NC} Failed to sync dependencies"
            return 1
        fi
    fi
    
    # Read files into array (portable way for macOS compatibility)
    files=()
    while IFS= read -r file; do
        files+=("$file")
    done < "$files_list"
    
    # Prepare ruff arguments based on mode
    local format_args=""
    local check_args=""
    
    if [ "$mode" = "fix" ]; then
        format_args=""
        check_args="--fix"
    else
        format_args="--check"
        check_args=""
    fi
    
    # Suppress ruff output in JSON mode
    local output_redirect=""
    if [ "$OUTPUT_FORMAT" = "json" ]; then
        output_redirect=">/dev/null 2>&1"
    fi
    
    # Run ruff format
    text_output "   ${BLUE}▸${NC} Running formatter..."
    if [ "$OUTPUT_FORMAT" = "json" ]; then
        if ! uv run ruff format $format_args "${files[@]}" >/dev/null 2>&1; then
            return 1
        fi
    else
        if ! uv run ruff format $format_args "${files[@]}"; then
            text_output "   ${RED}✗${NC} Format check failed"
            return 1
        fi
    fi
    
    if [ "$mode" = "fix" ]; then
        text_output "   ${GREEN}✓${NC} Formatted"
    else
        text_output "   ${GREEN}✓${NC} Format check passed"
    fi
    
    # Run ruff check
    text_output "   ${BLUE}▸${NC} Running linter..."
    if [ "$OUTPUT_FORMAT" = "json" ]; then
        if ! uv run ruff check $check_args "${files[@]}" >/dev/null 2>&1; then
            return 1
        fi
    else
        if ! uv run ruff check $check_args "${files[@]}"; then
            text_output "   ${RED}✗${NC} Lint check failed"
            return 1
        fi
    fi
    
    if [ "$mode" = "fix" ]; then
        text_output "   ${GREEN}✓${NC} Fixed linting issues"
    else
        text_output "   ${GREEN}✓${NC} Lint check passed"
    fi
    
    return 0
}

# Process each component that has changed files
exit_code=0
errors=()
num_components=0

for component in $COMPONENTS; do
    if [ -f "$temp_dir/$component.files" ]; then
        ((num_components++))
        file_count=$(wc -l < "$temp_dir/$component.files")
        ((files_processed += file_count))
        
        if ! lint_component "$component" "$MODE"; then
            exit_code=1
            errors+=("$component")
        fi
    fi
done

# Output final status
if [ "$OUTPUT_FORMAT" = "json" ]; then
    error_list=""
    if [ ${#errors[@]} -gt 0 ]; then
        error_list=$(printf ',"%s"' "${errors[@]}")
        error_list="[${error_list:1}]"
    else
        error_list="[]"
    fi
    
    status="success"
    if [ $exit_code -ne 0 ]; then
        status="error"
    fi
    
    echo "{\"status\":\"$status\",\"mode\":\"$MODE\",\"total_files\":$total_files,\"files_processed\":$files_processed,\"files_skipped\":$files_skipped,\"components_checked\":$num_components,\"errors\":$error_list}"
else
    echo ""
    if [ $exit_code -eq 0 ]; then
        text_output "${GREEN}✓${NC} All checks passed!"
    else
        text_output "${RED}✗${NC} Some checks failed"
        if [ ${#errors[@]} -gt 0 ]; then
            text_output "   Failed components: ${errors[*]}"
        fi
    fi
    
    text_output ""
    text_output "Summary:"
    text_output "  Files provided: $total_files"
    text_output "  Files processed: $files_processed"
    text_output "  Files skipped: $files_skipped"
    text_output "  Components checked: $num_components"
fi

exit $exit_code