#!/bin/bash
# Lint changed files, automatically detecting which components they belong to
# This script is used by both pre-commit hooks and can be run manually

set -e

# Parse arguments
MODE="${1:-check}"  # "check" or "fix"
shift || true

# If no files provided, exit successfully
if [ $# -eq 0 ]; then
    echo "No files to lint"
    exit 0
fi

# Detect project root (where this script lives in ./scripts/)
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

# Components in the project
COMPONENTS="common orchestrator fuzzer patcher program-model seed-gen"

# Process files and group by component
temp_dir=$(mktemp -d)
trap "rm -rf $temp_dir" EXIT

for file in "$@"; do
    # Convert to absolute path
    abs_file="$(realpath "$file" 2>/dev/null || echo "$PROJECT_ROOT/$file")"
    
    # Find which component this file belongs to
    for component in $COMPONENTS; do
        component_dir="$PROJECT_ROOT/$component"
        if [[ "$abs_file" == "$component_dir"/* ]] && [[ -f "$component_dir/pyproject.toml" ]]; then
            echo "$abs_file" >> "$temp_dir/$component.files"
            break
        fi
    done
done

# Exit if no components need linting
if [ -z "$(ls -A $temp_dir 2>/dev/null)" ]; then
    echo "No Python files in recognized components"
    exit 0
fi

# Function to run linting for a component
lint_component() {
    local component=$1
    local mode=$2
    local files_list="$temp_dir/$component.files"
    
    echo "Linting $component..."
    cd "$PROJECT_ROOT/$component"
    
    # Ensure dependencies are available
    if [ ! -d ".venv" ]; then
        uv sync -q --all-extras
    fi
    
    # Read files into array
    local files=$(cat "$files_list")
    
    # Run ruff based on mode
    if [ "$mode" = "fix" ]; then
        # Format and fix issues
        uv run ruff format $files
        uv run ruff check --fix $files
    else
        # Check only
        uv run ruff format --check $files
        uv run ruff check $files
    fi
}

# Process each component that has changed files
exit_code=0
for component in $COMPONENTS; do
    if [ -f "$temp_dir/$component.files" ]; then
        if ! lint_component "$component" "$MODE"; then
            exit_code=1
        fi
    fi
done

exit $exit_code