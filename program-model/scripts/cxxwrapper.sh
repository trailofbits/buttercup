# cxx_wrapper.sh
#!/bin/bash -e

# TODO(Ian): we need to share the code from ccwrapper.sh that moves kzip files between temp and original directories
echo "Called with $@"
echo "done"
$KYTHE_RELEASE_DIR/extractors/cxx_extractor "$@" & pid=$!
$ORIG_CXX "$@"
wait "$pid"