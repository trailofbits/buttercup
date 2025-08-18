#!/bin/bash
# Lint changed files, automatically detecting which components they belong to
# This script is used by both pre-commit hooks and can be run manually

set -e

# Color codes for better output
if [ -t 1 ]; then
    # Terminal supports colors
    RED='\033[0;31m'
    GREEN='\033[0;32m'
    YELLOW='\033[1;33m'
    BLUE='\033[0;34m'
    NC='\033[0m' # No Color
else
    # No color support (CI, redirected output, etc.)
    RED=''
    GREEN=''
    YELLOW=''
    BLUE=''
    NC=''
fi

# Parse arguments
MODE="${1:-check}"  # "check" or "fix"
shift || true

# If no files provided, exit successfully
if [ $# -eq 0 ]; then
    echo -e "${YELLOW}→${NC} No files to lint"
    exit 0
fi

# Detect project root (where this script lives in ./scripts/)
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

# Dynamically discover components (any directory with pyproject.toml)
echo -e "${BLUE}→${NC} Discovering components..."
COMPONENTS=""
for dir in */; do
    if [ -f "${dir}pyproject.toml" ] && [ "$dir" != "external/" ] && [ "$dir" != "deployment/" ]; then
        component="${dir%/}"  # Remove trailing slash
        COMPONENTS="$COMPONENTS $component"
    fi
done

if [ -z "$COMPONENTS" ]; then
    echo -e "${RED}✗${NC} No components found with pyproject.toml"
    exit 1
fi

echo -e "${GREEN}✓${NC} Found components:${COMPONENTS}"

# Process files and group by component
temp_dir=$(mktemp -d)
trap "rm -rf $temp_dir" EXIT

# Track statistics
total_files=0
skipped_files=0

for file in "$@"; do
    total_files=$((total_files + 1))
    
    # Skip non-existent files
    if [ ! -f "$file" ]; then
        echo -e "${YELLOW}⚠${NC} Skipping non-existent file: $file"
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
    echo -e "${YELLOW}→${NC} No Python files in recognized components"
    echo -e "   Processed: $total_files files, Skipped: $skipped_files files"
    exit 0
fi

# Function to run linting for a component
lint_component() {
    local component=$1
    local mode=$2
    local files_list="$temp_dir/$component.files"
    local file_count=$(wc -l < "$files_list")
    
    echo -e "\n${BLUE}→${NC} Linting ${component} (${file_count} files)..."
    cd "$PROJECT_ROOT/$component"
    
    # Ensure dependencies are available (with better check)
    if [ ! -d ".venv" ] || [ "pyproject.toml" -nt ".venv/pyvenv.cfg" ]; then
        echo -e "  ${YELLOW}↻${NC} Syncing dependencies..."
        uv sync -q --all-extras
    fi
    
    # Read files into array
    local files=$(cat "$files_list")
    
    # Run ruff based on mode
    local status=0
    if [ "$mode" = "fix" ]; then
        # Format and fix issues
        echo -e "  ${BLUE}▸${NC} Running formatter..."
        uv run ruff format $files || status=$?
        
        echo -e "  ${BLUE}▸${NC} Running linter with fixes..."
        uv run ruff check --fix $files || status=$?
    else
        # Check only
        echo -e "  ${BLUE}▸${NC} Checking format..."
        uv run ruff format --check $files || status=$?
        
        echo -e "  ${BLUE}▸${NC} Checking lint rules..."
        uv run ruff check $files || status=$?
    fi
    
    if [ $status -eq 0 ]; then
        echo -e "  ${GREEN}✓${NC} ${component} passed all checks"
    else
        echo -e "  ${RED}✗${NC} ${component} has issues"
    fi
    
    return $status
}

# Count components to process
component_count=$(echo "$components_with_files" | wc -w)

echo -e "\n${BLUE}═══════════════════════════════════════${NC}"
if [ "$MODE" = "fix" ]; then
    echo -e "${GREEN}Fixing${NC} files in ${component_count} component(s)"
else
    echo -e "${GREEN}Checking${NC} files in ${component_count} component(s)"
fi
echo -e "${BLUE}═══════════════════════════════════════${NC}"

# Process components in parallel if multiple components
exit_code=0
if [ $component_count -gt 1 ]; then
    # Parallel processing for multiple components
    echo -e "${BLUE}→${NC} Running in parallel..."
    
    # Array to store background job PIDs
    pids=""
    
    for component in $components_with_files; do
        if [ -f "$temp_dir/$component.files" ]; then
            # Run in background and capture output
            (
                lint_component "$component" "$MODE" 2>&1 | sed "s/^/  /"
                echo $? > "$temp_dir/$component.status"
            ) &
            pids="$pids $!"
        fi
    done
    
    # Wait for all background jobs
    for pid in $pids; do
        wait $pid
    done
    
    # Check exit codes
    for component in $components_with_files; do
        if [ -f "$temp_dir/$component.status" ]; then
            status=$(cat "$temp_dir/$component.status")
            if [ "$status" -ne 0 ]; then
                exit_code=1
            fi
        fi
    done
else
    # Sequential processing for single component
    for component in $components_with_files; do
        if [ -f "$temp_dir/$component.files" ]; then
            if ! lint_component "$component" "$MODE"; then
                exit_code=1
            fi
        fi
    done
fi

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

exit $exit_code