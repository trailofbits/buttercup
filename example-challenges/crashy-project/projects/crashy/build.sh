#!/bin/bash -eu
# OSS-Fuzz build script for crashy project

echo "Building crashy project..."

# Build the library (compile crashy.c as object file)
$CC $CFLAGS -c $SRC/crashy/crashy.c -o $SRC/crashy/crashy.o

# Build fuzzer
$CXX $CXXFLAGS -std=c++11 \
    $SRC/crashy/crashy_fuzzer.cc \
    $SRC/crashy/crashy.o \
    -o $OUT/crashy_fuzzer \
    $LIB_FUZZING_ENGINE

# Create seed corpus with some interesting inputs
mkdir -p $OUT/crashy_fuzzer_seed_corpus

# Add some seeds that will trigger crashes
echo "CRASH" > $OUT/crashy_fuzzer_seed_corpus/seed1.txt
echo "This contains CRASH in middle" > $OUT/crashy_fuzzer_seed_corpus/seed2.txt
echo "DIV0" > $OUT/crashy_fuzzer_seed_corpus/seed3.txt
echo "NULLPTR test" > $OUT/crashy_fuzzer_seed_corpus/seed4.txt

# Add some seeds that won't crash
echo "safe input" > $OUT/crashy_fuzzer_seed_corpus/seed5.txt
echo "another safe test" > $OUT/crashy_fuzzer_seed_corpus/seed6.txt
echo "no problems here" > $OUT/crashy_fuzzer_seed_corpus/seed7.txt

# Create a dictionary file for more efficient fuzzing
cat > $OUT/crashy_fuzzer.dict << EOF
# Crashy fuzzer dictionary
"CRASH"
"DIV"
"NULLPTR"
"0"
"1"
"2"
EOF

echo "Build complete!"