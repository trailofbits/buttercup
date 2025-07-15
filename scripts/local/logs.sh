#!/bin/bash
# Buttercup CRS - Local Development Logs Script
# Aggregates logs from all services

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

# Default options
FOLLOW=false
TAIL_LINES=100
SERVICE=""

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        -f|--follow)
            FOLLOW=true
            shift
            ;;
        -n|--tail)
            TAIL_LINES="$2"
            shift 2
            ;;
        -s|--service)
            SERVICE="$2"
            shift 2
            ;;
        -h|--help)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  -f, --follow          Follow log output (like tail -f)"
            echo "  -n, --tail LINES      Show last LINES lines (default: 100)"
            echo "  -s, --service NAME    Show logs for specific service only"
            echo "  -h, --help           Show this help message"
            echo ""
            echo "Available services:"
            $COMPOSE_CMD ps --services | sed 's/^/  - /'
            exit 0
            ;;
        *)
            echo -e "${RED}Unknown option: $1${NC}"
            echo "Use -h for help"
            exit 1
            ;;
    esac
done

# Build docker-compose logs command
LOGS_CMD="$COMPOSE_CMD logs --tail=$TAIL_LINES"

if [ "$FOLLOW" = true ]; then
    LOGS_CMD="$LOGS_CMD -f"
fi

if [ -n "$SERVICE" ]; then
    # Check if service exists
    if ! $COMPOSE_CMD ps --services | grep -q "^$SERVICE$"; then
        echo -e "${RED}Error: Service '$SERVICE' not found${NC}"
        echo "Available services:"
        $COMPOSE_CMD ps --services | sed 's/^/  - /'
        exit 1
    fi
    LOGS_CMD="$LOGS_CMD $SERVICE"
    echo -e "${BLUE}Showing logs for service: $SERVICE${NC}"
else
    echo -e "${BLUE}Showing logs for all services${NC}"
fi

echo -e "${YELLOW}Tail: $TAIL_LINES lines${NC}"
if [ "$FOLLOW" = true ]; then
    echo -e "${YELLOW}Following logs (Ctrl+C to stop)...${NC}"
fi
echo ""

# Execute logs command
$LOGS_CMD