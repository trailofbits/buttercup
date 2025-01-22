#!/bin/bash

protoc -Iaixcc-kythe/ --python_out=./src/buttercup/program_model/data --pyi_out=./src/buttercup/program_model/data aixcc-kythe/kythe/proto/storage.proto