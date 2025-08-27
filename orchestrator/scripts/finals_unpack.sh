#!/bin/bash

if [ "$#" -ne 0 ]; then
    echo "usage: $0"
    exit 1
fi

# Clean up
rm -rf tasks_storage

# Unpack
tar xvf tasks_storage.tar

# Decompress
for fn in `find tasks_storage -name *.tgz`; do
    dst="${fn%.tgz}"
    mkdir $dst
    tar xvzf $fn -C $dst
    rm $fn
done