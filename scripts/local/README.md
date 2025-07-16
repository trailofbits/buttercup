# Buttercup CRS - Local Development Scripts

This directory contains helper scripts for running Buttercup CRS locally on macOS.

## Quick Start

1. **Set up environment**:
   ```bash
   # Copy the example environment file
   cp .env.example .env
   
   # Edit .env and add your OpenAI API key
   # OPENAI_API_KEY="sk-..."
   ```

2. **Start services**:
   ```bash
   # Option 1: Full setup with Docker LiteLLM
   ./scripts/local/start.sh
   
   # Option 2: Minimal setup with uvx LiteLLM (recommended)
   ./scripts/local/start-minimal.sh
   
   # Or use the unified script:
   ./scripts/local/local-dev.sh --minimal up
   ```

3. **Verify setup**:
   ```bash
   ./scripts/local/quick-test.sh
   ```

## Available Scripts

### local-dev.sh
Unified script for managing the development environment.
```bash
# Start with Docker LiteLLM
./scripts/local/local-dev.sh up

# Start with uvx LiteLLM (minimal, recommended)
./scripts/local/local-dev.sh --minimal up

# Stop services
./scripts/local/local-dev.sh --minimal down

# View logs
./scripts/local/local-dev.sh logs
./scripts/local/local-dev.sh --minimal logs litellm

# Check status
./scripts/local/local-dev.sh status
```

### start.sh / start-minimal.sh
Starts all Buttercup CRS services in the correct order with health checks.
- `start.sh`: Full Docker setup including LiteLLM container
- `start-minimal.sh`: Minimal setup using uvx for LiteLLM (faster, simpler)
- Creates required directories
- Validates environment configuration
- Starts services with proper dependencies
- Shows service URLs when ready

### stop.sh / stop-minimal.sh
Performs a clean shutdown of all services.
- Stops Docker containers gracefully
- For minimal setup: also stops uvx LiteLLM process
- Preserves local data

### litellm.sh
Runs LiteLLM standalone with uvx (no Docker required).
```bash
# Start LiteLLM proxy server
./scripts/local/litellm.sh
```

### reset.sh
Completely resets the environment.
- Stops all services
- Removes Docker volumes
- Cleans local data directories
- Optionally restarts with fresh state

### logs.sh
Aggregates logs from all services.
```bash
# View all logs
./scripts/local/logs.sh

# Follow logs in real-time
./scripts/local/logs.sh -f

# View specific service logs
./scripts/local/logs.sh -s scheduler -f

# Show last 200 lines
./scripts/local/logs.sh -n 200
```

### status.sh
Checks the health of all services.
- Shows Docker container status
- Verifies service connectivity
- Displays queue lengths
- Shows disk usage
- Reports recent errors

### quick-test.sh
Runs a simple test to verify the setup.
- Checks API connectivity
- Verifies LLM configuration
- Tests Redis operations
- Validates local directories

## Environment Configuration

The scripts support multiple environment file formats:
- `.env` - Used by LiteLLM and uvx
- `env.dev.compose` - Used by Docker Compose services
- `env.local` - Template with local development defaults

The start script will automatically create the required files from whichever you provide.

### Minimal Setup Benefits

Using `--minimal` or `start-minimal.sh` runs LiteLLM with uvx instead of Docker:
- **Faster startup**: No Docker image building required
- **Less resource usage**: No container overhead
- **Easier debugging**: Direct access to process and logs
- **Always latest**: uvx automatically uses the latest LiteLLM version

## Service URLs

When running locally:
- **Task Server**: http://localhost:8000
- **LiteLLM Proxy**: http://localhost:8080
- **Redis**: localhost:6379

## Troubleshooting

### Services won't start
- Check Docker is running: `docker info`
- Verify ports are available: `lsof -i :8000 -i :8080 -i :6379`
- Check environment file: API keys must be set

### LLM errors
- Verify your OpenAI/Anthropic API key is valid
- Check LiteLLM logs: `./logs.sh -s litellm`

### Permission errors
- Ensure scripts are executable: `chmod +x scripts/local/*.sh`
- Check Docker permissions: you may need to run Docker Desktop

### Port conflicts
- The scripts bind to localhost only (127.0.0.1) to avoid conflicts
- If you still have conflicts, check what's using the ports with `lsof`