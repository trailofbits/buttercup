# Buttercup CRS - Local Development Setup

This simplified Docker Compose configuration is optimized for local development on macOS.

## Quick Start

1. **Prerequisites**
   - Docker Desktop for Mac installed and running
   - At least 8GB RAM allocated to Docker
   - Port 6379, 8000, 8080, 1323, and 31323 available

2. **Start the system**
   ```bash
   ./local-dev.sh up
   ```

3. **Access the services**
   - Task Server API: http://localhost:8000
   - Buttercup UI: http://localhost:1323
   - LiteLLM Proxy: http://localhost:8080
   - Redis: localhost:6379
   - Competition API: http://localhost:31323

## Key Changes from Production

- **Unified Fuzzer**: All 4 fuzzer components (build-bot, fuzzer-bot, coverage-bot, tracer-bot) run in a single container
- **Single Replica**: All services run with 1 instance for simplicity
- **No Resource Limits**: Docker manages resources automatically
- **Simplified Volumes**: Direct bind mounts instead of named volumes
- **Local Networking**: All services bound to 127.0.0.1 for security
- **GraphDB Removed**: Optional component not needed for basic development

## Common Commands

```bash
# Start all services
./local-dev.sh up

# View logs for a specific service
./local-dev.sh logs unified-fuzzer

# Restart a service
./local-dev.sh restart patcher

# Check service status
./local-dev.sh status

# Stop everything
./local-dev.sh down

# Clean up all data
./local-dev.sh clean

# Rebuild all services
./local-dev.sh rebuild
```

## Development Tips

1. **Logs**: Services run with debug logging by default (configured in compose.override.yaml)

2. **Live Code Reloading**: Uncomment volume mounts in compose.override.yaml to mount source code

3. **Environment Variables**: 
   - Core settings in `env.dev.compose`
   - Local overrides in `compose.override.yaml`
   - LLM keys in `.env`

4. **Data Directories**:
   - `./crs_scratch/` - Working directory for builds and fuzzing
   - `./tasks_storage/` - Downloaded task data
   - `./node_data_storage/` - Persistent node data

## Troubleshooting

- **Port conflicts**: Ensure ports 6379, 8000, 8080, 1323, 31323 are free
- **Docker issues**: Restart Docker Desktop
- **Service failures**: Check logs with `./local-dev.sh logs <service-name>`
- **Clean start**: Run `./local-dev.sh clean` then `./local-dev.sh up`

## Service Architecture

```
┌─────────────────┐     ┌──────────────┐     ┌─────────────┐
│  Competition    │────▶│ Task Server  │────▶│  Scheduler  │
│     API         │     │              │     │             │
└─────────────────┘     └──────────────┘     └─────────────┘
                                                     │
                                                     ▼
┌─────────────────┐     ┌──────────────┐     ┌─────────────┐
│ Unified Fuzzer  │────▶│    Redis     │◀────│   Patcher   │
│ (4-in-1)        │     │              │     │             │
└─────────────────┘     └──────────────┘     └─────────────┘
                                │
                                ▼
                        ┌──────────────┐     ┌─────────────┐
                        │ Program Model│     │  Seed Gen   │
                        │              │     │             │
                        └──────────────┘     └─────────────┘
```

The unified fuzzer combines:
- Build Bot - Compiles fuzzing harnesses
- Fuzzer Bot - Runs fuzzing campaigns
- Coverage Bot - Tracks code coverage
- Tracer Bot - Analyzes crashes

All services communicate through Redis queues and share data via mounted volumes.