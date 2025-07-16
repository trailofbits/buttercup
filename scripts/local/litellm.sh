#!/bin/bash
# Run LiteLLM proxy locally without Docker

set -e

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Get script directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$( cd "$SCRIPT_DIR/../.." && pwd )"

echo -e "${GREEN}Starting LiteLLM Proxy Server${NC}"

# Check for environment file
if [ ! -f "$PROJECT_ROOT/.env" ]; then
    echo -e "${RED}Error: .env file not found!${NC}"
    echo "Please create .env file with your API keys"
    echo "You can start with: cp .env.example .env"
    exit 1
fi

# Load environment variables
export $(grep -v '^#' "$PROJECT_ROOT/.env" | xargs)

# Check for API keys
if [ -z "$OPENAI_API_KEY" ] || [ "$OPENAI_API_KEY" = "sk-PLACEHOLDER-ADD-YOUR-KEY-HERE" ]; then
    if [ -z "$ANTHROPIC_API_KEY" ]; then
        echo -e "${RED}Error: No LLM API key configured!${NC}"
        echo "Please set either OPENAI_API_KEY or ANTHROPIC_API_KEY in .env"
        exit 1
    fi
fi

# Set LiteLLM master key
export BUTTERCUP_LITELLM_KEY="${BUTTERCUP_LITELLM_KEY:-sk-1234}"

# Database URL for LiteLLM (optional - for usage tracking)
# If you want to use PostgreSQL for tracking, uncomment and configure:
# export DATABASE_URL="postgresql://litellm_user:litellm_password11@localhost:5432/litellm"

echo -e "${YELLOW}Configuration:${NC}"
echo "  Config file: $PROJECT_ROOT/litellm/litellm_config.yaml"
echo "  Port: 8080"
echo "  Master key: $BUTTERCUP_LITELLM_KEY"

# Change to project root
cd "$PROJECT_ROOT"

# Run LiteLLM with uvx (with proxy extras)
echo -e "${GREEN}Starting LiteLLM...${NC}"
uvx --from "litellm[proxy]" litellm \
    --config "$PROJECT_ROOT/litellm/litellm_config.yaml" \
    --port 8080 \
    --host 0.0.0.0 \
    --num_workers 1