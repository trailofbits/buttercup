# Running LiteLLM with uvx (Alternative to Docker)

Yes, LiteLLM can be run directly with `uvx` instead of Docker! This simplifies the setup significantly.

## Option 1: Run LiteLLM with uvx

### Quick Start

```bash
# Export required environment variables
export BUTTERCUP_LITELLM_KEY=sk-1234
export OPENAI_API_KEY="your-openai-key-here"
# or
export ANTHROPIC_API_KEY="your-anthropic-key-here"

# Run LiteLLM directly
uvx litellm \
    --config ./litellm/litellm_config.yaml \
    --port 8080 \
    --host 0.0.0.0 \
    --num_workers 1
```

### Using the Helper Script

```bash
# Run LiteLLM with the provided script
./scripts/local/litellm.sh
```

### Minimal Setup (Redis + PostgreSQL with Docker, LiteLLM with uvx)

```bash
# Start minimal services
./scripts/local/start-minimal.sh

# This will:
# 1. Start Redis and PostgreSQL with Docker
# 2. Start LiteLLM with uvx in the background
# 3. Save the LiteLLM PID to litellm.pid

# Stop all services
./scripts/local/stop-minimal.sh
```

## Option 2: Run Everything Locally with uv

If you want to avoid Docker entirely, you can:

1. **Redis**: Install and run locally
   ```bash
   # macOS with Homebrew
   brew install redis
   brew services start redis
   ```

2. **PostgreSQL** (optional - only needed for LiteLLM usage tracking):
   ```bash
   # macOS with Homebrew
   brew install postgresql
   brew services start postgresql
   ```

3. **LiteLLM**: Run with uvx as shown above

## Benefits of Using uvx

1. **Simpler Setup**: No need to build Docker images
2. **Faster Startup**: Direct execution without container overhead
3. **Easier Debugging**: Direct access to logs and process
4. **Resource Efficient**: No Docker daemon overhead
5. **Easy Updates**: `uvx` always uses the latest version

## Configuration

The LiteLLM configuration is in `litellm/litellm_config.yaml` and supports:
- OpenAI models (gpt-4o, gpt-4o-mini, etc.)
- Anthropic models (claude-3.5-sonnet, etc.)
- Rate limiting and usage tracking
- Master key authentication

## Testing the Setup

```bash
# Test LiteLLM health
curl http://localhost:8080/health

# Test with authentication
curl http://localhost:8080/v1/models \
  -H "Authorization: Bearer sk-1234"
```

## Environment Variables

Create a `.env` file with:
```bash
# LiteLLM Configuration
BUTTERCUP_LITELLM_KEY=sk-1234
BUTTERCUP_LITELLM_HOSTNAME=http://localhost:8080

# LLM API Keys (at least one required)
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...
```

## Docker Compose Integration

The `compose.yaml` has been updated to make LiteLLM optional:
- LiteLLM service now uses profile `full`
- Run with Docker: `docker compose --profile full up`
- Run without Docker: Use uvx as shown above

This gives you flexibility to run LiteLLM however you prefer!