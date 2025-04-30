#!/bin/bash

# Wait for the Docker host to be ready to accept connections
if [ -n "$DOCKER_HOST" ]; then
    echo "Waiting for Docker daemon to be ready..."
    while ! docker info > /dev/null 2>&1; do
        sleep 1
    done
fi

# Run the command passed as arguments
exec "$@"
