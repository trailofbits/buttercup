/*
 * Crashy - Fixed version with patches applied
 * 
 * This version fixes the buffer overflow vulnerability
 * but leaves the other vulnerabilities for testing.
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>

// Fixed function - no more buffer overflow
void process_data(const uint8_t *data, size_t size) {
    char buffer[16];
    
    if (size < 5) {
        return;
    }
    
    // Look for "CRASH" pattern in input
    for (size_t i = 0; i <= size - 5; i++) {
        if (memcmp(data + i, "CRASH", 5) == 0) {
            printf("Found crash trigger at position %zu\n", i);
            
            // FIX: Check size before copying
            size_t copy_size = size < sizeof(buffer) ? size : sizeof(buffer) - 1;
            memcpy(buffer, data, copy_size);
            buffer[copy_size] = '\0';  // Ensure null termination
            
            printf("Buffer content (truncated): %s\n", buffer);
        }
    }
    
    // Division by zero still exists (for testing)
    if (size >= 10 && data[0] == 'D' && data[1] == 'I' && data[2] == 'V') {
        int divisor = data[3] - '0';
        int result = 100 / divisor;
        printf("Division result: %d\n", result);
    }
    
    // Null pointer dereference still exists (for testing)
    if (size >= 8 && memcmp(data, "NULLPTR", 7) == 0) {
        int *ptr = NULL;
        *ptr = 42;
    }
}

// Main function remains the same
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