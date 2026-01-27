#!/usr/bin/env bash
# Generate protobuf files using grpcio-tools from the common venv.
# MUST be run from within the common venv: cd common && uv run ../protoc.sh
set -euo pipefail

localpath="$( cd -- "$(dirname "$0")" >/dev/null 2>&1 || exit ; pwd -P )"
echo "$localpath"
echo "$localpath/common/protos"

python -m grpc_tools.protoc \
    --pyi_out="$localpath/common/src/buttercup/common/datastructures/" \
    --python_out="$localpath/common/src/buttercup/common/datastructures/" \
    -I"$localpath/common/protos" \
    "$localpath"/common/protos/*.proto
