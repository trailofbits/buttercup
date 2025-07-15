#!/bin/bash
# Buttercup CRS - Local Development Reset Script
# Cleans all data and restarts the environment

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Get script directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$( cd "$SCRIPT_DIR/../.." && pwd )"

echo -e "${RED}WARNING: This will delete all local data and reset the environment!${NC}"
echo -e "This includes:"
echo -e "  - All fuzzing results"
echo -e "  - All downloaded tasks"
echo -e "  - All patch attempts"
echo -e "  - Redis data"
echo -e "  - Docker volumes"

# Confirm with user
read -p "Are you sure you want to continue? (y/N) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Reset cancelled."
    exit 1
fi

# Change to project root
cd "$PROJECT_ROOT"

# Use docker compose (v2) if available, otherwise fall back to docker-compose
if docker compose version &> /dev/null; then
    COMPOSE_CMD="docker compose"
else
    COMPOSE_CMD="docker-compose"
fi

# Stop all services and remove volumes
echo -e "\n${YELLOW}Stopping all services and removing volumes...${NC}"
$COMPOSE_CMD down -v

# Clean local directories
echo -e "\n${YELLOW}Cleaning local data directories...${NC}"

# Function to safely clean directory
clean_directory() {
    local dir=$1
    if [ -d "$dir" ]; then
        echo "Cleaning $dir..."
        rm -rf "$dir"/*
        # Keep the directory but add .gitkeep
        touch "$dir/.gitkeep"
    fi
}

clean_directory "$PROJECT_ROOT/crs_scratch"
clean_directory "$PROJECT_ROOT/tasks_storage"
clean_directory "$PROJECT_ROOT/node_data"

# Remove any stale Docker resources
echo -e "\n${YELLOW}Cleaning Docker resources...${NC}"
docker system prune -f --volumes || true

echo -e "\n${GREEN}Reset complete!${NC}"

# Ask if user wants to start fresh
read -p "Do you want to start the services now? (Y/n) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Nn]$ ]]; then
    echo -e "\n${GREEN}Starting fresh environment...${NC}"
    exec "$SCRIPT_DIR/start.sh"
else
    echo -e "\nTo start the services later, run: ${YELLOW}$SCRIPT_DIR/start.sh${NC}"
fi