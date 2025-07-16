#!/bin/bash
# Run the submit-challenge tool using uv

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Use uv run to execute the script with inline dependencies
exec uv run "$SCRIPT_DIR/submit-challenge.py" "$@"