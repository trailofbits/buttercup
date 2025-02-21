#!/bin/bash -e

set -euxo pipefail

echo "Called with $@"
echo "done"

KYTHE_OUTPUT_DIRECTORY_ORIG=$KYTHE_OUTPUT_DIRECTORY
KYTHE_OUTPUT_DIRECTORY=$(mktemp -d -t kythe_output_XXXXXXXXXXXXXXX)
mkdir -p $KYTHE_OUTPUT_DIRECTORY
KYTHE_OUTPUT_DIRECTORY=$KYTHE_OUTPUT_DIRECTORY $KYTHE_RELEASE_DIR/extractors/cxx_extractor "$@" & pid=$!
$ORIG_CXX  "$@"
wait "$pid"

for X in $KYTHE_OUTPUT_DIRECTORY/*.kzip; do [[ -e $X ]] && mv "$X" $KYTHE_OUTPUT_DIRECTORY_ORIG/; done
rm -r $KYTHE_OUTPUT_DIRECTORY
