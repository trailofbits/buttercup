#!/bin/bash

set -euxo pipefail

cp -r ./ $OUT/kythe 
pushd $OUT/kythe 
bazel-7.1.0 build //kythe/release --sandbox_debug
cp bazel-bin/kythe/release/kythe-v0.0.67.tar.gz ./