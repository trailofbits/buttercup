# cxx_wrapper.sh
#!/bin/bash -e
echo "Called with $@"
echo "done"
$KYTHE_RELEASE_DIR/extractors/cxx_extractor "$@" & pid=$!
$ORIG_CXX "$@"
wait "$pid"