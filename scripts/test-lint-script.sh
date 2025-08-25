#!/bin/bash
# Test suite for lint-changed-files.sh
# Verifies the script works correctly in various scenarios

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Test counter
TESTS_PASSED=0
TESTS_FAILED=0

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LINT_SCRIPT="$SCRIPT_DIR/lint-changed-files.sh"

# Check script exists
if [ ! -f "$LINT_SCRIPT" ]; then
    echo -e "${RED}Error: lint-changed-files.sh not found${NC}"
    exit 1
fi

echo "Testing lint-changed-files.sh..."
echo "================================"

# Test helper
run_test() {
    local test_name="$1"
    local command="$2"
    local expected_exit="$3"
    
    echo -n "Testing: $test_name... "
    
    # Run command and capture exit code
    set +e
    output=$(eval "$command" 2>&1)
    actual_exit=$?
    set -e
    
    if [ "$actual_exit" -eq "$expected_exit" ]; then
        echo -e "${GREEN}PASS${NC}"
        ((TESTS_PASSED++))
        return 0
    else
        echo -e "${RED}FAIL${NC}"
        echo "  Expected exit code: $expected_exit"
        echo "  Actual exit code: $actual_exit"
        echo "  Output: $output"
        ((TESTS_FAILED++))
        return 1
    fi
}

# Test 1: No arguments should succeed
run_test "No arguments" "$LINT_SCRIPT" 0

# Test 2: Invalid mode should fail
run_test "Invalid mode" "$LINT_SCRIPT invalid" 1

# Test 3: Check mode with no files should succeed
run_test "Check mode no files" "$LINT_SCRIPT check" 0

# Test 4: Fix mode with no files should succeed  
run_test "Fix mode no files" "$LINT_SCRIPT fix" 0

# Test 5: Unknown flag should fail
run_test "Unknown flag" "$LINT_SCRIPT --unknown check" 1

# Test 6: JSON format with no files
run_test "JSON format no files" "$LINT_SCRIPT --format=json check" 0

# Test 7: JSON output should be valid JSON
echo -n "Testing: JSON output validity... "
json_output=$($LINT_SCRIPT --format=json check 2>&1)
if echo "$json_output" | python3 -m json.tool > /dev/null 2>&1; then
    echo -e "${GREEN}PASS${NC}"
    ((TESTS_PASSED++))
else
    echo -e "${RED}FAIL${NC}"
    echo "  Invalid JSON: $json_output"
    ((TESTS_FAILED++))
fi

# Test 8: Plain output flag
run_test "Plain output flag" "$LINT_SCRIPT --plain check" 0

# Test 9: Non-existent file should skip gracefully
run_test "Non-existent file" "$LINT_SCRIPT check /tmp/nonexistent.py" 0

# Test 10: Check actual Python file (if exists)
# Find a real Python file to test with
SAMPLE_FILE=""
for component in common orchestrator fuzzer patcher program-model seed-gen; do
    if [ -d "$SCRIPT_DIR/../$component" ]; then
        # Find first .py file
        SAMPLE_FILE=$(find "$SCRIPT_DIR/../$component" -name "*.py" -type f | head -1)
        if [ -n "$SAMPLE_FILE" ]; then
            break
        fi
    fi
done

if [ -n "$SAMPLE_FILE" ]; then
    echo -n "Testing: Real file check mode... "
    # This might fail if file has lint issues, but should not error
    set +e
    output=$($LINT_SCRIPT check "$SAMPLE_FILE" 2>&1)
    exit_code=$?
    set -e
    
    if [ $exit_code -eq 0 ] || [ $exit_code -eq 1 ]; then
        echo -e "${GREEN}PASS${NC} (exit code: $exit_code)"
        ((TESTS_PASSED++))
    else
        echo -e "${RED}FAIL${NC}"
        echo "  Unexpected exit code: $exit_code"
        echo "  Output: $output"
        ((TESTS_FAILED++))
    fi
else
    echo -e "${YELLOW}SKIP${NC}: No Python files found for real file test"
fi

# Summary
echo ""
echo "================================"
echo "Test Results:"
echo -e "  Passed: ${GREEN}$TESTS_PASSED${NC}"
echo -e "  Failed: ${RED}$TESTS_FAILED${NC}"

if [ $TESTS_FAILED -eq 0 ]; then
    echo -e "${GREEN}All tests passed!${NC}"
    exit 0
else
    echo -e "${RED}Some tests failed${NC}"
    exit 1
fi