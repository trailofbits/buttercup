#!/bin/bash
# Monitor CRS results

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Use uv run to execute the script with inline dependencies
exec uv run "$SCRIPT_DIR/monitor-results.py" "$@"