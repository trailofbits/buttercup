#!/bin/bash

python -m grpc_tools.protoc -Ikythe/ --python_out=./program_model/data --pyi_out=./program_model/data --grpc_python_out=./program_model/services kythe/kythe/proto/storage.proto