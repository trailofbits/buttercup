#!/bin/bash
# Buttercup CRS - Quick Test Script
# Runs a simple test to verify the setup is working

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Get script directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$( cd "$SCRIPT_DIR/../.." && pwd )"

echo -e "${BLUE}=== Buttercup CRS Quick Test ===${NC}\n"

# Check if services are running
if ! "$SCRIPT_DIR/status.sh" >/dev/null 2>&1; then
    echo -e "${RED}Services are not running!${NC}"
    echo -e "Please start services first: ${YELLOW}$SCRIPT_DIR/start.sh${NC}"
    exit 1
fi

# Test 1: Check API connectivity
echo -e "${YELLOW}Test 1: Checking API connectivity...${NC}"
if curl -s http://localhost:8000/ping | grep -q "pong"; then
    echo -e "${GREEN}✓ Task Server API is responding${NC}"
else
    echo -e "${RED}✗ Task Server API is not responding${NC}"
    exit 1
fi

# Test 2: Check LiteLLM proxy
echo -e "\n${YELLOW}Test 2: Checking LLM proxy...${NC}"
if curl -s http://localhost:8080/health | grep -q "healthy"; then
    echo -e "${GREEN}✓ LiteLLM proxy is healthy${NC}"
else
    echo -e "${RED}✗ LiteLLM proxy is not healthy${NC}"
    exit 1
fi

# Test 3: Check Redis connectivity
echo -e "\n${YELLOW}Test 3: Checking Redis connectivity...${NC}"
cd "$PROJECT_ROOT"
if docker compose version &> /dev/null; then
    COMPOSE_CMD="docker compose"
else
    COMPOSE_CMD="docker-compose"
fi

if $COMPOSE_CMD exec -T redis redis-cli ping 2>/dev/null | grep -q PONG; then
    echo -e "${GREEN}✓ Redis is responding${NC}"
else
    echo -e "${RED}✗ Redis is not responding${NC}"
    exit 1
fi

# Test 4: Test LLM API key configuration
echo -e "\n${YELLOW}Test 4: Checking LLM configuration...${NC}"
LITELLM_RESPONSE=$(curl -s -X POST http://localhost:8080/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer d5179c62ae1c7366e3ee09775d0993d5" \
  -d '{
    "model": "gpt-3.5-turbo",
    "messages": [{"role": "user", "content": "Say hello"}],
    "max_tokens": 10
  }' 2>/dev/null)

if echo "$LITELLM_RESPONSE" | grep -q "choices"; then
    echo -e "${GREEN}✓ LLM API is configured correctly${NC}"
elif echo "$LITELLM_RESPONSE" | grep -q "invalid_api_key"; then
    echo -e "${RED}✗ LLM API key is invalid or not set${NC}"
    echo "  Please check your OPENAI_API_KEY or ANTHROPIC_API_KEY in the environment file"
    exit 1
else
    echo -e "${YELLOW}⚠ Could not verify LLM configuration${NC}"
    echo "  Response: $LITELLM_RESPONSE"
fi

# Test 5: Check if mock competition API is enabled
echo -e "\n${YELLOW}Test 5: Checking competition API mode...${NC}"
if [ "${MOCK_COMPETITION_API_ENABLED}" = "true" ]; then
    echo -e "${GREEN}✓ Mock competition API is enabled (good for local testing)${NC}"
else
    echo -e "${YELLOW}⚠ Mock competition API is disabled${NC}"
    echo "  You may need to configure external competition API settings"
fi

# Test 6: Verify local directories
echo -e "\n${YELLOW}Test 6: Checking local directories...${NC}"
all_dirs_ok=true
for dir in crs_scratch tasks_storage node_data; do
    if [ -d "$PROJECT_ROOT/$dir" ] && [ -w "$PROJECT_ROOT/$dir" ]; then
        echo -e "${GREEN}✓ $dir directory exists and is writable${NC}"
    else
        echo -e "${RED}✗ $dir directory is missing or not writable${NC}"
        all_dirs_ok=false
    fi
done

# Test 7: Simple queue test
echo -e "\n${YELLOW}Test 7: Testing Redis queues...${NC}"
TEST_VALUE="test_$(date +%s)"
if $COMPOSE_CMD exec -T redis redis-cli LPUSH test_queue "$TEST_VALUE" >/dev/null 2>&1; then
    RETRIEVED=$($COMPOSE_CMD exec -T redis redis-cli RPOP test_queue 2>/dev/null)
    if [ "$RETRIEVED" = "$TEST_VALUE" ]; then
        echo -e "${GREEN}✓ Redis queue operations working${NC}"
    else
        echo -e "${RED}✗ Redis queue test failed${NC}"
    fi
else
    echo -e "${RED}✗ Could not test Redis queues${NC}"
fi

# Summary
echo -e "\n${BLUE}=== Test Summary ===${NC}"
if [ "$all_dirs_ok" = true ]; then
    echo -e "${GREEN}All tests passed! Your Buttercup CRS environment is ready.${NC}"
    echo -e "\nNext steps:"
    echo -e "  1. Check the logs: ${YELLOW}$SCRIPT_DIR/logs.sh -f${NC}"
    echo -e "  2. Monitor status: ${YELLOW}$SCRIPT_DIR/status.sh${NC}"
    echo -e "  3. Submit a task using the orchestrator scripts"
else
    echo -e "${YELLOW}Some tests had warnings. The system may still work but check the issues above.${NC}"
fi