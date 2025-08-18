#!/bin/bash
# Lint changed files, automatically detecting which components they belong to
# This script is used by both pre-commit hooks and can be run manually
#
# Optimized for AI coding assistants (Claude Code, Cursor, etc.)
# Requirements:
# - Deterministic output
# - Automatic fixing
# - Clear error messages  
# - No interactive prompts
# - Structured output options for parsing

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
    if [ -f "${dir}pyproject.toml" ] && [ "$dir" != "external/" ] && [ "$dir" != "deployment/" ]; then
        component="${dir%/}"  # Remove trailing slash
        COMPONENTS="$COMPONENTS $component"
    fi
done

if [ -z "$COMPONENTS" ]; then
    if [ "$OUTPUT_FORMAT" = "json" ]; then
        echo '{"status":"error","message":"No components found with pyproject.toml"}'
    else
        text_output "${RED}✗${NC} No components found with pyproject.toml"
    fi
    exit 1
fi

text_output "${GREEN}✓${NC} Found components:${COMPONENTS}"

# Process files and group by component
temp_dir=$(mktemp -d) || {
    echo "Error: Failed to create temporary directory" >&2
    exit 1
}
trap "rm -rf $temp_dir" EXIT

# Track statistics
total_files=0
skipped_files=0
components_data="{}"  # For JSON output

for file in "$@"; do
    total_files=$((total_files + 1))
    
    # Skip non-existent files
    if [ ! -f "$file" ]; then
        text_output "${YELLOW}⚠${NC} Skipping non-existent file: $file"
        skipped_files=$((skipped_files + 1))
        continue
    fi
    
    # Convert to absolute path
    abs_file="$(realpath "$file" 2>/dev/null || echo "$PROJECT_ROOT/$file")"
    
    # Find which component this file belongs to
    found_component=false
    for component in $COMPONENTS; do
        component_dir="$PROJECT_ROOT/$component"
        if [[ "$abs_file" == "$component_dir"/* ]]; then
            echo "$abs_file" >> "$temp_dir/$component.files"
            found_component=true
            break
        fi
    done
    
    if [ "$found_component" = false ]; then
        skipped_files=$((skipped_files + 1))
    fi
done

# Check if any components need linting
components_with_files=""
for component in $COMPONENTS; do
    if [ -f "$temp_dir/$component.files" ]; then
        components_with_files="$components_with_files $component"
    fi
done

if [ -z "$components_with_files" ]; then
    if [ "$OUTPUT_FORMAT" = "json" ]; then
        echo "{\"status\":\"success\",\"message\":\"No Python files in recognized components\",\"files_processed\":$((total_files - skipped_files)),\"files_skipped\":$skipped_files}"
    else
        text_output "${YELLOW}→${NC} No Python files in recognized components"
        text_output "   Processed: $total_files files, Skipped: $skipped_files files"
    fi
    exit 0
fi

# Function to run linting for a component
lint_component() {
    local component=$1
    local mode=$2
    local files_list="$temp_dir/$component.files"
    local file_count=$(wc -l < "$files_list")
    
    text_output "\n${BLUE}→${NC} Linting ${component} (${file_count} files)..."
    
    # Change to component directory
    cd "$PROJECT_ROOT/$component" || {
        echo "Error: Failed to change to component directory $component" >&2
        return 1
    }
    
    # Ensure dependencies are available (with better check)
    if [ ! -d ".venv" ] || [ "pyproject.toml" -nt ".venv/pyvenv.cfg" ]; then
        text_output "  ${YELLOW}↻${NC} Syncing dependencies..."
        if ! uv sync -q --all-extras; then
            echo "Error: Failed to sync dependencies for $component" >&2
            return 1
        fi
    fi
    
    # Read files into array
    local files=$(cat "$files_list")
    
    # Run ruff based on mode
    local status=0
    local format_status=0
    local check_status=0
    
    if [ "$mode" = "fix" ]; then
        # Format and fix issues
        text_output "  ${BLUE}▸${NC} Running formatter..."
        if [ "$OUTPUT_FORMAT" = "json" ]; then
            uv run ruff format $files >/dev/null 2>&1 || format_status=$?
        else
            if ! uv run ruff format $files; then
                format_status=$?
                echo "Warning: Formatter returned non-zero status for $component" >&2
            fi
        fi
        
        text_output "  ${BLUE}▸${NC} Running linter with fixes..."
        if [ "$OUTPUT_FORMAT" = "json" ]; then
            uv run ruff check --fix $files >/dev/null 2>&1 || check_status=$?
        else
            if ! uv run ruff check --fix $files; then
                check_status=$?
                echo "Warning: Linter returned non-zero status for $component" >&2
            fi
        fi
    else
        # Check only
        text_output "  ${BLUE}▸${NC} Checking format..."
        if [ "$OUTPUT_FORMAT" = "json" ]; then
            uv run ruff format --check $files >/dev/null 2>&1 || format_status=$?
        else
            if ! uv run ruff format --check $files; then
                format_status=$?
            fi
        fi
        
        text_output "  ${BLUE}▸${NC} Checking lint rules..."
        if [ "$OUTPUT_FORMAT" = "json" ]; then
            uv run ruff check $files >/dev/null 2>&1 || check_status=$?
        else
            if ! uv run ruff check $files; then
                check_status=$?
            fi
        fi
    fi
    
    # Determine overall status
    if [ $format_status -ne 0 ] || [ $check_status -ne 0 ]; then
        status=1
    fi
    
    # Store result for JSON output
    if [ "$OUTPUT_FORMAT" = "json" ]; then
        echo "{\"component\":\"$component\",\"files\":$file_count,\"format_status\":$format_status,\"check_status\":$check_status,\"status\":$status}" >> "$temp_dir/results.json"
    fi
    
    if [ $status -eq 0 ]; then
        text_output "  ${GREEN}✓${NC} ${component} passed all checks"
    else
        text_output "  ${RED}✗${NC} ${component} has issues"
    fi
    
    return $status
}

# Count components to process
component_count=$(echo "$components_with_files" | wc -w)

# Header
if [ "$OUTPUT_FORMAT" = "text" ]; then
    echo -e "\n${BLUE}═══════════════════════════════════════${NC}"
    if [ "$MODE" = "fix" ]; then
        echo -e "${GREEN}Fixing${NC} files in ${component_count} component(s)"
    else
        echo -e "${GREEN}Checking${NC} files in ${component_count} component(s)"
    fi
    echo -e "${BLUE}═══════════════════════════════════════${NC}"
fi

# Process each component sequentially (removed parallel processing for simplicity)
exit_code=0
json_results="["
first_result=true

for component in $components_with_files; do
    if [ -f "$temp_dir/$component.files" ]; then
        if ! lint_component "$component" "$MODE"; then
            exit_code=1
        fi
        
        # Collect JSON results
        if [ "$OUTPUT_FORMAT" = "json" ] && [ -f "$temp_dir/results.json" ]; then
            if [ "$first_result" = true ]; then
                first_result=false
            else
                json_results="$json_results,"
            fi
            json_results="$json_results$(tail -1 "$temp_dir/results.json")"
        fi
    fi
done

json_results="$json_results]"

# Output final results
if [ "$OUTPUT_FORMAT" = "json" ]; then
    echo "{\"mode\":\"$MODE\",\"total_files\":$total_files,\"files_processed\":$((total_files - skipped_files)),\"files_skipped\":$skipped_files,\"components_checked\":$component_count,\"status\":$exit_code,\"components\":$json_results}"
else
    # Print summary
    echo -e "\n${BLUE}═══════════════════════════════════════${NC}"
    echo -e "${GREEN}Summary:${NC}"
    echo -e "  ${BLUE}▸${NC} Mode: ${MODE}"
    echo -e "  ${BLUE}▸${NC} Files processed: $((total_files - skipped_files))/$total_files"
    echo -e "  ${BLUE}▸${NC} Components checked: ${component_count}"
    
    if [ $exit_code -eq 0 ]; then
        echo -e "  ${GREEN}✓${NC} All checks passed!"
    else
        echo -e "  ${RED}✗${NC} Some checks failed"
    fi
    echo -e "${BLUE}═══════════════════════════════════════${NC}"
fi

exit $exit_code