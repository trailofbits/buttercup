#!/bin/bash
# Buttercup CRS - Local Development Status Script
# Checks health of all services

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Get script directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$( cd "$SCRIPT_DIR/../.." && pwd )"

# Change to project root
cd "$PROJECT_ROOT"

# Use docker compose (v2) if available, otherwise fall back to docker-compose
if docker compose version &> /dev/null; then
    COMPOSE_CMD="docker compose"
else
    COMPOSE_CMD="docker-compose"
fi

echo -e "${BLUE}=== Buttercup CRS Service Status ===${NC}\n"

# Check if services are running
if ! $COMPOSE_CMD ps --quiet 2>/dev/null | grep -q .; then
    echo -e "${RED}No services are running!${NC}"
    echo -e "Start services with: ${YELLOW}$SCRIPT_DIR/start.sh${NC}"
    exit 1
fi

# Show docker-compose status
echo -e "${YELLOW}Docker Compose Services:${NC}"
$COMPOSE_CMD ps

echo -e "\n${YELLOW}Service Health Checks:${NC}"

# Function to check service health
check_service() {
    local service=$1
    local check_cmd=$2
    local check_name=${3:-$service}
    
    printf "%-20s" "$check_name:"
    
    if eval "$check_cmd" >/dev/null 2>&1; then
        echo -e " ${GREEN}✓ Healthy${NC}"
        return 0
    else
        echo -e " ${RED}✗ Unhealthy${NC}"
        return 1
    fi
}

# Check core services
check_service "Redis" "$COMPOSE_CMD exec -T redis redis-cli ping 2>/dev/null | grep -q PONG"

# Check LiteLLM (could be Docker or uvx)
if $COMPOSE_CMD ps 2>/dev/null | grep -q litellm; then
    check_service "LiteLLM Proxy" "curl -s http://localhost:8080/health" "LiteLLM (Docker)"
elif [ -f "$PROJECT_ROOT/litellm.pid" ] && ps -p $(cat "$PROJECT_ROOT/litellm.pid") > /dev/null 2>&1; then
    check_service "LiteLLM Proxy" "curl -s http://localhost:8080/health" "LiteLLM (uvx)"
else
    # Try to check if it's running anyway
    check_service "LiteLLM Proxy" "curl -s http://localhost:8080/health"
fi

check_service "Task Server" "curl -s http://localhost:8000/ping"

# Check if scheduler is processing
echo -e "\n${YELLOW}Queue Status:${NC}"
if $COMPOSE_CMD exec -T redis redis-cli ping >/dev/null 2>&1; then
    # Get Redis queue lengths
    SCHEDULER_QUEUE=$($COMPOSE_CMD exec -T redis redis-cli llen scheduler_queue 2>/dev/null || echo "0")
    FUZZER_QUEUE=$($COMPOSE_CMD exec -T redis redis-cli llen fuzzer_queue 2>/dev/null || echo "0")
    PATCHER_QUEUE=$($COMPOSE_CMD exec -T redis redis-cli llen patcher_queue 2>/dev/null || echo "0")
    
    echo "  Scheduler Queue: $SCHEDULER_QUEUE items"
    echo "  Fuzzer Queue: $FUZZER_QUEUE items"
    echo "  Patcher Queue: $PATCHER_QUEUE items"
else
    echo -e "  ${RED}Unable to connect to Redis${NC}"
fi

# Check disk usage for local directories
echo -e "\n${YELLOW}Local Storage Usage:${NC}"
for dir in crs_scratch tasks_storage node_data; do
    if [ -d "$PROJECT_ROOT/$dir" ]; then
        size=$(du -sh "$PROJECT_ROOT/$dir" 2>/dev/null | cut -f1)
        count=$(find "$PROJECT_ROOT/$dir" -type f 2>/dev/null | wc -l | tr -d ' ')
        printf "  %-20s %8s (%s files)\n" "$dir:" "$size" "$count"
    else
        printf "  %-20s %s\n" "$dir:" "Not created"
    fi
done

# Check for recent errors in logs
echo -e "\n${YELLOW}Recent Errors (last 5 minutes):${NC}"
ERROR_COUNT=$($COMPOSE_CMD logs --since 5m 2>/dev/null | grep -iE "error|exception|failed" | wc -l | tr -d ' ')
if [ "$ERROR_COUNT" -gt 0 ]; then
    echo -e "  ${RED}Found $ERROR_COUNT error messages${NC}"
    echo -e "  Run ${YELLOW}$SCRIPT_DIR/logs.sh${NC} to view details"
else
    echo -e "  ${GREEN}No recent errors found${NC}"
fi

# Show useful commands
echo -e "\n${BLUE}Useful Commands:${NC}"
echo -e "  View logs:        ${YELLOW}$SCRIPT_DIR/logs.sh -f${NC}"
echo -e "  View service log: ${YELLOW}$SCRIPT_DIR/logs.sh -s <service> -f${NC}"
echo -e "  Stop services:    ${YELLOW}$SCRIPT_DIR/stop.sh${NC}"
echo -e "  Reset all:        ${YELLOW}$SCRIPT_DIR/reset.sh${NC}"
echo -e "  Run test:         ${YELLOW}$SCRIPT_DIR/quick-test.sh${NC}"