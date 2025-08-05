#!/bin/bash

# If not enough arguments, show usage
if [ $# -lt 1 ]; then
    echo "Usage: $0 [quick|full]"
    exit 1
fi

# Quick or full test
if [ "$1" == "quick" ]; then
    echo "Running quick test..."
    pytest_args=""
elif [ "$1" == "full" ]; then
    echo "Running full test..."
    pytest_args="--runintegration"
else
    echo "Invalid argument: $1"
    echo "Usage: $0 [quick|full]"
    exit 1
fi

# Build the Docker image with correct context (parent directory)
echo "Building Docker image..."
docker build -t program-model-test -f Dockerfile ..

# Run pytest directly in the container with tests folder mounted
echo "Running tests..."
docker run --rm -v "$(pwd)/tests:/app/tests" program-model-test pytest -svv $pytest_args

# Clean up
docker rmi program-model-test