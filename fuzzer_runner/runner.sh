#!/bin/bash

SCRIPT_DIR=$(dirname "$0")

if [ -d "$SCRIPT_DIR/.venv" ]; then
    . "$SCRIPT_DIR/.venv/bin/activate"
else
    echo "Virtual environment not found in $SCRIPT_DIR/.venv"
    exit 1
fi

buttercup-fuzzer-runner "$@" # we use "$@" to pass all the arguments to the python script
