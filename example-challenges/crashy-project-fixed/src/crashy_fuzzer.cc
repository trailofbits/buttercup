/*
 * LibFuzzer harness for crashy.c
 */

#include <stdint.h>
#include <stddef.h>

// Declaration of the function we want to fuzz
extern "C" {
    void process_data(const uint8_t *data, size_t size);
}

// LibFuzzer entry point
extern "C" int LLVMFuzzerTestOneInput(const uint8_t *data, size_t size) {
    // Call the function we want to test
    process_data(data, size);
    return 0;
}