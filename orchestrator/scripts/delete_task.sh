#!/bin/bash

# delete_task.sh - Script to delete tasks from the task-server
# Usage: 
#   ./delete_task.sh <task_id> [task_server_url]  - Delete a specific task
#   ./delete_task.sh --all [task_server_url]      - Delete all tasks

set -e

# Get authentication credentials from environment or use default values
API_KEY_ID="${CRS_API_KEY_ID:-515cc8a0-3019-4c9f-8c1c-72d0b54ae561}"
API_KEY_TOKEN="${CRS_API_KEY_TOKEN:-VGuAC8axfOnFXKBB7irpNDOKcDjOlnyB}"

# Function to make a DELETE request to the API
make_delete_request() {
    local endpoint=$1
    local server_url=$2
    local description=$3
    
    echo "Deleting $description from server: $server_url"
    
    # Make API call
    response=$(curl -s -w "\n%{http_code}" \
        -X DELETE \
        -u "$API_KEY_ID:$API_KEY_TOKEN" \
        "$server_url$endpoint")
    
    # Extract HTTP status code and response body
    http_code=$(echo "$response" | tail -n1)
    response_body=$(echo "$response" | sed '$d')
    
    # Check if the request was successful
    if [[ "$http_code" == 2* ]]; then
        echo "Delete operation successful"
        echo "Response: $response_body"
        return 0
    else
        echo "Error deleting $description. HTTP status code: $http_code"
        echo "Response: $response_body"
        return 1
    fi
}

# Check arguments
if [ $# -lt 1 ]; then
    echo "Error: Arguments required"
    echo "Usage: $0 <task_id> [task_server_url]  - Delete a specific task"
    echo "       $0 --all [task_server_url]      - Delete all tasks"
    exit 1
fi

# Set server URL (2nd arg or default)
TASK_SERVER_URL="${2:-http://127.0.0.1:8000}"

# Handle different modes
if [ "$1" == "--all" ]; then
    # Delete all tasks
    make_delete_request "/v1/task/" "$TASK_SERVER_URL" "ALL tasks"
else
    # Delete specific task
    TASK_ID="$1"
    make_delete_request "/v1/task/$TASK_ID/" "$TASK_SERVER_URL" "task with ID: $TASK_ID"
fi

# Exit with the status from the delete request
exit $?