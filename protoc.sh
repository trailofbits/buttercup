#!/usr/bin/env bash
# this is a hack because i dont want to cut a new release of clusterfuzz that 
# supports later versions of grpc
localpath="$( cd -- "$(dirname "$0")" >/dev/null 2>&1 ; pwd -P )"
echo "$localpath"
echo "$localpath/fuzzer/protos"
protoc --pyi_out="$localpath/common/common/datastructures/" --python_out "$localpath/common/common/datastructures/" -I"$localpath/fuzzer/protos" "$localpath/fuzzer/protos/fuzzer_msg.proto"