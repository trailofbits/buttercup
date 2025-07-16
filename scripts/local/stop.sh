#!/bin/bash
# Buttercup CRS - Local Development Stop Script
# Performs clean shutdown of all services

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Get script directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$( cd "$SCRIPT_DIR/../.." && pwd )"

echo -e "${YELLOW}Stopping Buttercup CRS Local Development Environment${NC}"

# Change to project root
cd "$PROJECT_ROOT"

# Use docker compose (v2) if available, otherwise fall back to docker-compose
if docker compose version &> /dev/null; then
    COMPOSE_CMD="docker compose"
else
    COMPOSE_CMD="docker-compose"
fi

# Show current status
echo "Current service status:"
$COMPOSE_CMD ps

# Stop all services gracefully (including those with profile)
echo -e "\n${YELLOW}Stopping all services...${NC}"
$COMPOSE_CMD --profile full down

# Optional: Remove volumes (commented out by default to preserve data)
# echo -e "\n${YELLOW}Removing volumes...${NC}"
# $COMPOSE_CMD down -v

echo -e "\n${GREEN}All services stopped successfully!${NC}"

# Check if user wants to clean local data
echo -e "\n${YELLOW}Local data directories still exist in:${NC}"
echo "  - $PROJECT_ROOT/crs_scratch"
echo "  - $PROJECT_ROOT/tasks_storage"
echo "  - $PROJECT_ROOT/node_data"
echo -e "\nTo clean all data, run: ${YELLOW}$SCRIPT_DIR/reset.sh${NC}"