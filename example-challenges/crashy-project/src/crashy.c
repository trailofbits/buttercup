/*
 * Crashy - A test program that crashes 50% of the time
 * 
 * This program has an intentional buffer overflow vulnerability
 * that triggers when the input contains the byte sequence "CRASH"
 * at any position.
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>

// Vulnerable function with buffer overflow
void process_data(const uint8_t *data, size_t size) {
    char buffer[16];  // Small buffer - vulnerability!
    
    // Check if input is large enough
    if (size < 5) {
        return;
    }
    
    // Look for "CRASH" pattern in input
    // This gives roughly 50% crash rate with random fuzzing
    for (size_t i = 0; i <= size - 5; i++) {
        if (memcmp(data + i, "CRASH", 5) == 0) {
            // Intentional buffer overflow!
            printf("Found crash trigger at position %zu\n", i);
            
            // Copy way too much data into small buffer
            memcpy(buffer, data, size);  // BUG: size can be > 16!
            
            // Use the buffer so it's not optimized away
            printf("Buffer content: %s\n", buffer);
        }
    }
    
    // Another vulnerability: division by zero
    if (size >= 10 && data[0] == 'D' && data[1] == 'I' && data[2] == 'V') {
        int divisor = data[3] - '0';  // Can be 0!
        int result = 100 / divisor;   // Potential crash
        printf("Division result: %d\n", result);
    }
    
    // Null pointer dereference
    if (size >= 8 && memcmp(data, "NULLPTR", 7) == 0) {
        int *ptr = NULL;
        *ptr = 42;  // Crash!
    }
}

// For testing with regular input
int main(int argc, char **argv) {
    if (argc < 2) {
        printf("Usage: %s <input_file>\n", argv[0]);
        return 1;
    }
    
    FILE *fp = fopen(argv[1], "rb");
    if (!fp) {
        perror("Failed to open input file");
        return 1;
    }
    
    fseek(fp, 0, SEEK_END);
    size_t size = ftell(fp);
    fseek(fp, 0, SEEK_SET);
    
    uint8_t *data = malloc(size);
    if (!data) {
        fclose(fp);
        return 1;
    }
    
    if (fread(data, 1, size, fp) != size) {
        free(data);
        fclose(fp);
        return 1;
    }
    
    fclose(fp);
    
    process_data(data, size);
    
    free(data);
    return 0;
}