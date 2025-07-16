#!/bin/bash
# Buttercup CRS - Local Development Start Script
# Starts all services with proper order and health checks

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Get script directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$( cd "$SCRIPT_DIR/../.." && pwd )"

echo -e "${GREEN}Starting Buttercup CRS Local Development Environment${NC}"

# Check for required environment variables
if [ ! -f "$PROJECT_ROOT/.env" ] && [ ! -f "$PROJECT_ROOT/env.local" ] && [ ! -f "$PROJECT_ROOT/env.dev.compose" ]; then
    echo -e "${RED}Error: No environment file found!${NC}"
    echo "Please create one of the following:"
    echo "  - .env (for LiteLLM)"
    echo "  - env.dev.compose (for all services)"
    echo "  - env.local (template provided)"
    echo "You can start with: cp .env.example .env"
    exit 1
fi

# Create env.dev.compose from env.local or .env if it doesn't exist
if [ ! -f "$PROJECT_ROOT/env.dev.compose" ]; then
    if [ -f "$PROJECT_ROOT/env.local" ]; then
        echo "Creating env.dev.compose from env.local"
        cp "$PROJECT_ROOT/env.local" "$PROJECT_ROOT/env.dev.compose"
    elif [ -f "$PROJECT_ROOT/.env" ]; then
        echo "Creating env.dev.compose from .env"
        cp "$PROJECT_ROOT/.env" "$PROJECT_ROOT/env.dev.compose"
    fi
fi

# Also ensure .env exists for LiteLLM
if [ ! -f "$PROJECT_ROOT/.env" ]; then
    if [ -f "$PROJECT_ROOT/env.local" ]; then
        echo "Creating .env from env.local for LiteLLM"
        cp "$PROJECT_ROOT/env.local" "$PROJECT_ROOT/.env"
    elif [ -f "$PROJECT_ROOT/env.dev.compose" ]; then
        echo "Creating .env from env.dev.compose for LiteLLM"
        cp "$PROJECT_ROOT/env.dev.compose" "$PROJECT_ROOT/.env"
    fi
fi

# Load environment variables
if [ -f "$PROJECT_ROOT/.env" ]; then
    echo "Loading environment from .env"
    export $(grep -v '^#' "$PROJECT_ROOT/.env" | xargs)
fi

# Check for required API keys
if [ -z "$OPENAI_API_KEY" ] || [ "$OPENAI_API_KEY" = "<your-openai-api-key>" ]; then
    if [ -z "$ANTHROPIC_API_KEY" ] || [ "$ANTHROPIC_API_KEY" = "<your-anthropic-api-key>" ]; then
        echo -e "${RED}Error: No LLM API key configured!${NC}"
        echo "Please set either OPENAI_API_KEY or ANTHROPIC_API_KEY in your environment file"
        exit 1
    fi
fi

# Create local directories if they don't exist
echo "Creating local storage directories..."
mkdir -p "$PROJECT_ROOT/crs_scratch"
mkdir -p "$PROJECT_ROOT/tasks_storage"
mkdir -p "$PROJECT_ROOT/node_data"

# Change to project root
cd "$PROJECT_ROOT"

# Check if docker-compose is installed
if ! command -v docker-compose &> /dev/null && ! command -v docker &> /dev/null; then
    echo -e "${RED}Error: docker-compose is not installed!${NC}"
    exit 1
fi

# Use docker compose (v2) if available, otherwise fall back to docker-compose
if docker compose version &> /dev/null; then
    COMPOSE_CMD="docker compose"
else
    COMPOSE_CMD="docker-compose"
fi

# Pull latest images (optional, can be skipped for faster starts)
echo -e "${YELLOW}Pulling latest images...${NC}"
$COMPOSE_CMD pull || true

# Start services in order
echo -e "${GREEN}Starting core infrastructure...${NC}"
$COMPOSE_CMD up -d redis

# Wait for Redis to be ready
echo "Waiting for Redis to be ready..."
until $COMPOSE_CMD exec redis redis-cli ping 2>/dev/null | grep -q PONG; do
    echo -n "."
    sleep 1
done
echo -e " ${GREEN}Ready!${NC}"

# Start LiteLLM proxy with Docker (use --profile full)
echo -e "${GREEN}Starting LiteLLM proxy with Docker...${NC}"
$COMPOSE_CMD --profile full up -d litellm

# Wait for LiteLLM to be ready
echo "Waiting for LiteLLM to be ready..."
sleep 5  # Give it a moment to start
until curl -s http://localhost:8080/health > /dev/null 2>&1; do
    echo -n "."
    sleep 1
done
echo -e " ${GREEN}Ready!${NC}"

# Start remaining services
echo -e "${GREEN}Starting all services...${NC}"
$COMPOSE_CMD up -d

# Show status
echo -e "\n${GREEN}All services started!${NC}"
echo -e "\nService URLs:"
echo -e "  ${YELLOW}Task Server:${NC} http://localhost:8000"
echo -e "  ${YELLOW}LiteLLM Proxy:${NC} http://localhost:8080"
echo -e "  ${YELLOW}Redis:${NC} localhost:6379"

echo -e "\n${GREEN}To view logs:${NC} $SCRIPT_DIR/logs.sh"
echo -e "${GREEN}To check status:${NC} $SCRIPT_DIR/status.sh"
echo -e "${GREEN}To stop:${NC} $SCRIPT_DIR/stop.sh"

# Run a quick health check
sleep 3
"$SCRIPT_DIR/status.sh"