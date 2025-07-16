#!/bin/bash
# Test script to verify crashes

set -e

echo "Building crashy..."
cd src
make clean
make
cd ..

echo ""
echo "Testing safe inputs (should NOT crash):"
for input in test-inputs/safe*.txt; do
    echo -n "Testing $input: "
    if ./src/crashy "$input" > /dev/null 2>&1; then
        echo "OK (no crash)"
    else
        echo "UNEXPECTED CRASH!"
    fi
done

echo ""
echo "Testing crash inputs (SHOULD crash):"
for input in test-inputs/crash*.txt test-inputs/div_zero.txt test-inputs/nullptr.txt; do
    echo -n "Testing $input: "
    if ./src/crashy "$input" > /dev/null 2>&1; then
        echo "NO CRASH (unexpected!)"
    else
        echo "CRASHED (expected)"
    fi
done

echo ""
echo "Test complete!"