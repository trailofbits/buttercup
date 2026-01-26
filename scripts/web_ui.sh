#!/bin/bash

if [ ! -f deployment/env ]; then
    echo "Error: Deployment environment file not found. Run 'make setup-local' or 'make setup-azure' first."
    exit 1
fi
source ./deployment/env

if ! kubectl get namespace "${BUTTERCUP_NAMESPACE:-crs}" >/dev/null 2>&1; then
    echo "Error: CRS namespace not found. Deploy first with 'make deploy'."
    exit 1
fi

echo "Opening web UI..."

if [ "${TAILSCALE_ENABLED:-false}" = "true" ]; then
    # Use Tailscale domain
    if [ -z "${TAILSCALE_DOMAIN}" ]; then
        echo "Error: TAILSCALE_ENABLED is true but TAILSCALE_DOMAIN is not set"
        exit 1
    fi
    CRS_HOSTNAME="${CRS_HOSTNAME:-buttercup-ui}"
    UI_URL="http://${CRS_HOSTNAME}.${TAILSCALE_DOMAIN}"
else
    # Use local port-forward
    echo "Starting port-forward to buttercup-ui service..."
    kubectl port-forward -n "${BUTTERCUP_NAMESPACE:-crs}" service/buttercup-ui 31323:1323 &
    PORT_FORWARD_PID=$!
    sleep 3
    UI_URL="http://localhost:31323"

    # Function to cleanup on exit
    cleanup() {
        echo ""
        echo "Stopping port-forward..."
        kill "$PORT_FORWARD_PID" 2>/dev/null
        echo "Port-forward stopped. Goodbye!"
        exit 0
    }

    echo ""
    echo "Port-forward is active. Press Ctrl+C to stop the port-forward and exit."
    echo "The web UI will remain accessible at $UI_URL until you stop this process."

    # Set up signal handlers
    trap cleanup SIGINT SIGTERM
fi

echo "Opening web UI at $UI_URL in your browser..."
if command -v xdg-open >/dev/null 2>&1; then
    xdg-open "$UI_URL"
elif command -v open >/dev/null 2>&1; then
    open "$UI_URL"
else
    echo "Please open $UI_URL in your browser."
fi

if [ -n "$PORT_FORWARD_PID" ]; then
    # Keep the script running
    wait "$PORT_FORWARD_PID"
fi
