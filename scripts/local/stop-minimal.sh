#!/bin/bash
# Stop minimal Buttercup CRS services

set -e

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Get script directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$( cd "$SCRIPT_DIR/../.." && pwd )"

echo -e "${GREEN}Stopping Buttercup CRS Services${NC}"

# Stop LiteLLM if running with uvx
if [ -f "$PROJECT_ROOT/litellm.pid" ]; then
    PID=$(cat "$PROJECT_ROOT/litellm.pid")
    if ps -p $PID > /dev/null 2>&1; then
        echo "Stopping LiteLLM (PID: $PID)..."
        kill $PID || true
        rm "$PROJECT_ROOT/litellm.pid"
    else
        echo "LiteLLM process not found"
        rm "$PROJECT_ROOT/litellm.pid"
    fi
else
    # Try to find and kill any running LiteLLM process
    pkill -f "litellm --config" || true
fi

# Use docker compose v2 if available
if docker compose version &> /dev/null; then
    COMPOSE_CMD="docker compose"
else
    COMPOSE_CMD="docker-compose"
fi

# Stop Docker services
cd "$PROJECT_ROOT"
echo "Stopping Docker services..."
$COMPOSE_CMD down

echo -e "${GREEN}All services stopped!${NC}"