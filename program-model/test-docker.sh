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
    echo "Full test is not supported yet. Please use 'quick' instead for now."
    exit 1

    echo "Running full test..."
    pytest_args="--runintegration"

    # TODO(Evan): For now, integration tests are only supported on x86_64.
    arch=$(uname -m)
    if [ "$arch" != "x86_64" ]; then
        echo "ERROR: AIxCC OSS-Fuzz Challenges require x86_64 architecture. Running on $arch."
        exit 1
    fi
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

# TODO(Evan): Uncomment this when we have a way to run AIxCC integration tests, or switch to different tests.
#   docker run --rm \
#     -v "$(pwd)/tests:/app/tests" \
#     -v /var/run/docker.sock:/var/run/docker.sock \
#     program-model-test pytest -svv --runintegration --log-cli-level=DEBUG tests/c/test_libpng.py


# Clean up
docker rmi program-model-test