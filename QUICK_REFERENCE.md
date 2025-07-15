# Buttercup CRS - Quick Reference Guide

## Setup Commands

### Initial Setup
```bash
# Clone repository
git clone --recurse-submodules https://github.com/your-org/buttercup.git
cd buttercup

# Configure environment
cp env.template env.dev.compose
# Edit env.dev.compose with your API keys

# Start services
./local-dev.sh up
```

### Quick Start
```bash
# Automated setup (includes all steps)
./local-dev.sh setup

# Manual setup
docker compose up -d

# Verify installation
./local-dev.sh status
curl http://localhost:8000/health
```

## Common Commands

### Service Management
```bash
# Start/stop services
./local-dev.sh up              # Start all services
./local-dev.sh down            # Stop all services
./local-dev.sh restart         # Restart all services
./local-dev.sh restart patcher # Restart specific service

# Check status
./local-dev.sh status          # Show all services
docker compose ps              # Docker native command

# View logs
./local-dev.sh logs            # All services
./local-dev.sh logs scheduler  # Specific service
docker compose logs -f patcher # Follow logs

# Shell access
./local-dev.sh shell patcher   # Enter container
docker compose exec scheduler /bin/bash
```

### Testing
```bash
# Submit test challenges
./orchestrator/scripts/task_integration_test.sh   # Basic test
./orchestrator/scripts/challenge.sh               # Full challenge
./orchestrator/scripts/task_upstream_libpng.sh    # Specific test

# Send SARIF message
./orchestrator/scripts/send_sarif.sh <TASK-ID>

# Monitor progress
open http://localhost:1323                        # Web UI
docker compose logs -f scheduler                  # Logs
```

### Development
```bash
# Code quality
just lint-python-all           # Lint all components
just lint-python patcher       # Lint specific component

# Run tests
cd patcher && uv run pytest    # Component tests
cd orchestrator && uv run pytest --cov  # With coverage

# Rebuild services
./local-dev.sh rebuild         # Rebuild all
./local-dev.sh rebuild patcher # Rebuild specific

# Clean environment
./local-dev.sh clean           # Remove all data
docker system prune -a         # Clean Docker
```

### Docker Management
```bash
# Resource monitoring
docker stats                   # Live resource usage
docker compose top             # Running processes

# Volume management  
docker volume ls               # List volumes
docker volume inspect buttercup_crs_scratch

# Network debugging
docker network ls
docker compose port task-server 8000

# Clean up
docker compose down -v         # Remove volumes
docker system prune -a         # Full cleanup
```

## Configuration

### Environment Variables
```bash
# Core settings (env.dev.compose)
OPENAI_API_KEY=sk-...         # Required
ANTHROPIC_API_KEY=sk-ant-...  # Optional
LOG_LEVEL=INFO                # DEBUG for development
TELEMETRY_ENABLED=false       # Disable for local

# Service URLs (auto-configured)
REDIS_URL=redis://redis:6379
DOCKER_HOST=tcp://dind:2375
COMPETITION_API_URL=http://competition-api:31323
```

### Service Endpoints
- Task Server: http://localhost:8000
- Web UI: http://localhost:1323
- LiteLLM: http://localhost:8080
- Redis: localhost:6379
- Mock Competition API: http://localhost:31323

## Troubleshooting

### Common Issues

#### Docker Issues
```bash
# Docker Desktop not running (macOS)
open -a Docker
# Wait for Docker to start
docker ps

# Permission issues
sudo chown -R $(whoami):$(whoami) ./crs_scratch ./tasks_storage

# Reset Docker Desktop (macOS)
rm -rf ~/Library/Group\ Containers/group.com.docker
rm -rf ~/Library/Containers/com.docker.docker
```

#### Service Issues
```bash
# Service won't start
docker compose logs <service>  # Check error logs
docker compose restart <service>

# Port conflicts
lsof -i :8000                  # Find conflicting process
kill -9 <PID>                  # Kill process

# Dependencies not ready
docker compose up -d redis litellm-db
sleep 10
docker compose up -d
```

#### LLM/API Issues  
```bash
# Check API keys
grep -E "OPENAI|ANTHROPIC" env.dev.compose

# Test LiteLLM
curl http://localhost:8080/health
docker compose logs litellm

# Verify model access
curl -X POST http://localhost:8080/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model": "gpt-4", "messages": [{"role": "user", "content": "test"}]}'
```

#### Memory/Performance Issues
```bash
# Check Docker resources
docker system df
docker stats --no-stream

# Increase Docker memory (Docker Desktop)
# Settings -> Resources -> Memory: 16GB+

# Clean up
./local-dev.sh clean
docker system prune -a --volumes
```

### Log Analysis

#### Monitor Workflow Progress
```bash
# Check patch submission
docker compose logs scheduler | grep "WAIT_PATCH_PASS -> SUBMIT_BUNDLE"

# Monitor task progress
docker compose logs -f scheduler | grep -E "State transition|Task.*completed"

# Check fuzzing results  
docker compose logs unified-fuzzer | grep -E "crash|vulnerability"
```

#### Debug Specific Issues
```bash
# LLM errors
docker compose logs patcher | grep -E "ERROR|Exception"

# Build failures
docker compose logs unified-fuzzer | grep "BUILD_FAILED"

# Redis connection issues
docker compose exec redis redis-cli ping
```

## File Locations

### Configuration Files
- `env.dev.compose` - Main environment configuration
- `env.template` - Configuration template
- `compose.yaml` - Docker Compose services
- `compose.override.yaml` - Local overrides
- `litellm/litellm_config.yaml` - LLM proxy config

### Data Directories
- `./crs_scratch/` - Working directory for builds/fuzzing
- `./tasks_storage/` - Downloaded challenge tasks
- `./node_data_storage/` - Persistent node data

### Scripts
- `./local-dev.sh` - Main development script
- `orchestrator/scripts/` - Test and task scripts
- `docker/` - Docker configurations

### Documentation
- `README.md` - Getting started guide
- `LOCAL_DEVELOPMENT.md` - Detailed local dev guide
- `QUICK_REFERENCE.md` - This file
- `MIGRATION_GUIDE.md` - K8s to Docker migration
- `deployment/README.md` - Docker Compose details

## Quick Tips

### Performance
```bash
# Monitor resource usage
watch -n 2 'docker stats --no-stream'

# Limit service resources
# Add to compose.override.yaml:
services:
  patcher:
    deploy:
      resources:
        limits:
          memory: 4G
          cpus: '2'
```

### Development
```bash
# Enable hot reload
# Add to compose.override.yaml:
services:
  patcher:
    volumes:
      - ./patcher/src:/app/src:delegated
    environment:
      - DEVELOPMENT=true

# Quick restart after code changes
./local-dev.sh restart patcher
```

### Debugging
```bash
# Interactive debugging
docker compose exec patcher python -m pdb /app/src/main.py

# Check Redis queues
docker compose exec redis redis-cli
> KEYS *
> LLEN task_queue
> LRANGE task_queue 0 -1
```

## Support

- Logs: `./local-dev.sh logs <service>`
- Shell: `./local-dev.sh shell <service>`  
- Web UI: http://localhost:1323
- Documentation: See `/docs` directory 
