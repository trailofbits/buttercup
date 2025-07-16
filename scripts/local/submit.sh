#!/bin/bash
# Simple wrapper for challenge submission

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Check if services are running
if ! docker compose ps | grep -q "task-server.*Up"; then
    echo -e "${RED}Error: CRS services are not running${NC}"
    echo "Start them with: ./scripts/local/local-dev.sh --minimal up"
    exit 1
fi

# Check arguments
if [ $# -lt 1 ]; then
    echo "Usage: $0 <project-directory> [--delta commit1 commit2]"
    echo ""
    echo "Examples:"
    echo "  # Full analysis"
    echo "  $0 /path/to/oss-fuzz-project"
    echo ""
    echo "  # Delta analysis"
    echo "  $0 /path/to/oss-fuzz-project --delta abc123 def456"
    exit 1
fi

PROJECT_DIR="$1"
shift

# Check if project directory exists
if [ ! -d "$PROJECT_DIR" ]; then
    echo -e "${RED}Error: Project directory not found: $PROJECT_DIR${NC}"
    exit 1
fi

# Check for OSS-Fuzz structure
if [ ! -d "$PROJECT_DIR/projects" ]; then
    echo -e "${RED}Error: Missing projects/ directory in $PROJECT_DIR${NC}"
    echo "This doesn't look like an OSS-Fuzz project"
    exit 1
fi

# Parse delta mode arguments
DELTA_ARGS=""
if [ "$1" == "--delta" ]; then
    if [ $# -lt 3 ]; then
        echo -e "${RED}Error: --delta requires two commit arguments${NC}"
        exit 1
    fi
    DELTA_ARGS="--commit1 $2 --commit2 $3"
    echo -e "${YELLOW}Delta mode: comparing $2 to $3${NC}"
fi

# Submit the challenge
echo -e "${GREEN}Submitting challenge from $PROJECT_DIR${NC}"
"$SCRIPT_DIR/submit-challenge.sh" "$PROJECT_DIR" $DELTA_ARGS

echo ""
echo -e "${GREEN}Challenge submitted!${NC}"
echo ""
echo "Monitor progress with:"
echo "  docker compose logs -f scheduler"
echo "  docker compose logs -f unified-fuzzer"
echo "  docker compose logs -f patcher"