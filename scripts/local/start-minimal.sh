#!/bin/bash
# Minimal Buttercup CRS start script using uvx for LiteLLM

set -e

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Get script directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$( cd "$SCRIPT_DIR/../.." && pwd )"

echo -e "${GREEN}Starting Minimal Buttercup CRS Environment${NC}"

# Check for environment file
if [ ! -f "$PROJECT_ROOT/.env" ]; then
    echo -e "${RED}Error: .env file not found!${NC}"
    echo "Please create .env file with your API keys"
    echo "You can start with: cp .env.example .env"
    exit 1
fi

# Load environment variables
export $(grep -v '^#' "$PROJECT_ROOT/.env" | xargs)

# Create directories
echo "Creating local storage directories..."
mkdir -p "$PROJECT_ROOT/crs_scratch"
mkdir -p "$PROJECT_ROOT/tasks_storage"
mkdir -p "$PROJECT_ROOT/node_data"

cd "$PROJECT_ROOT"

# Use docker compose v2 if available
if docker compose version &> /dev/null; then
    COMPOSE_CMD="docker compose"
else
    COMPOSE_CMD="docker-compose"
fi

# Start only Redis with Docker (PostgreSQL not needed without database tracking)
echo -e "${GREEN}Starting Redis...${NC}"
$COMPOSE_CMD up -d redis

# Wait for Redis
echo "Waiting for Redis..."
until $COMPOSE_CMD exec redis redis-cli ping 2>/dev/null | grep -q PONG; do
    echo -n "."
    sleep 1
done
echo -e " ${GREEN}Ready!${NC}"

# Start LiteLLM with uvx in background
echo -e "${GREEN}Starting LiteLLM with uvx...${NC}"
export BUTTERCUP_LITELLM_KEY="${BUTTERCUP_LITELLM_KEY:-sk-1234}"
# Don't set DATABASE_URL - we don't need database tracking for local dev
# export DATABASE_URL="postgresql://litellm_user:litellm_password11@localhost:5432/litellm"

# Kill any existing LiteLLM process
pkill -f "litellm --config" || true

# Start LiteLLM in background
nohup uvx --from "litellm[proxy]" litellm \
    --config "$PROJECT_ROOT/litellm/litellm_config.yaml" \
    --port 8080 \
    --host 0.0.0.0 \
    --num_workers 1 \
    > "$PROJECT_ROOT/litellm.log" 2>&1 &

echo "LiteLLM PID: $!"
echo $! > "$PROJECT_ROOT/litellm.pid"

# Wait for LiteLLM
echo "Waiting for LiteLLM..."
sleep 5
until curl -s http://localhost:8080/health > /dev/null 2>&1; do
    echo -n "."
    sleep 1
done
echo -e " ${GREEN}Ready!${NC}"

echo -e "\n${GREEN}Minimal services started!${NC}"
echo -e "\nService URLs:"
echo -e "  ${YELLOW}LiteLLM Proxy:${NC} http://localhost:8080"
echo -e "  ${YELLOW}Redis:${NC} localhost:6379"

echo -e "\n${GREEN}LiteLLM logs:${NC} tail -f $PROJECT_ROOT/litellm.log"
echo -e "${GREEN}To stop LiteLLM:${NC} kill \$(cat $PROJECT_ROOT/litellm.pid)"
echo -e "${GREEN}To stop Docker services:${NC} $COMPOSE_CMD down"