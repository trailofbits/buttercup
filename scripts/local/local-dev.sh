#!/bin/bash
# Buttercup CRS - Local Development Helper Script

set -e

# Get script directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# Default to 'up' if no command provided
COMMAND="${1:-up}"

# Check for --minimal flag
MINIMAL=false
if [ "$1" = "--minimal" ] || [ "$2" = "--minimal" ]; then
    MINIMAL=true
    if [ "$1" = "--minimal" ]; then
        COMMAND="${2:-up}"
    fi
fi

case "$COMMAND" in
    up)
        if [ "$MINIMAL" = true ]; then
            "$SCRIPT_DIR/start-minimal.sh"
        else
            "$SCRIPT_DIR/start.sh"
        fi
        ;;
    down)
        if [ "$MINIMAL" = true ]; then
            "$SCRIPT_DIR/stop-minimal.sh"
        else
            "$SCRIPT_DIR/stop.sh"
        fi
        ;;
    logs)
        shift
        [ "$1" = "--minimal" ] && shift
        "$SCRIPT_DIR/logs.sh" "$@"
        ;;
    status)
        "$SCRIPT_DIR/status.sh"
        ;;
    *)
        echo "Usage: $0 [--minimal] {up|down|logs|status}"
        echo "  up     - Start all services"
        echo "  down   - Stop all services"
        echo "  logs   - View service logs (optionally specify service name)"
        echo "  status - Check service status"
        echo ""
        echo "Options:"
        echo "  --minimal  Use minimal setup (LiteLLM via uvx instead of Docker)"
        echo ""
        echo "Examples:"
        echo "  $0 up              # Start with Docker LiteLLM"
        echo "  $0 --minimal up    # Start with uvx LiteLLM"
        exit 1
        ;;
esac