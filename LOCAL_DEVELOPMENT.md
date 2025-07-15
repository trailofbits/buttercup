# Buttercup CRS - Local Development Guide for macOS

This guide provides comprehensive instructions for setting up and running the Buttercup Cyber Reasoning System on macOS for local development.

## System Requirements

### Hardware
- macOS 11 (Big Sur) or later
- Apple Silicon (M1/M2/M3) or Intel processor
- Minimum 16GB RAM (32GB recommended)
- 50GB+ free disk space

### Software Prerequisites
- Docker Desktop for Mac 4.26+
- Git with LFS support
- Python 3.11+ (for development tools)
- Xcode Command Line Tools

## Installation

### Step 1: Install Docker Desktop

1. **Download Docker Desktop**:
   - For Apple Silicon: [Docker Desktop for Apple Silicon](https://desktop.docker.com/mac/main/arm64/Docker.dmg)
   - For Intel: [Docker Desktop for Intel](https://desktop.docker.com/mac/main/amd64/Docker.dmg)

2. **Install and Configure**:
   ```bash
   # After installation, start Docker Desktop
   open -a Docker
   
   # Wait for Docker to fully start, then verify
   docker --version
   docker compose version
   ```

3. **Configure Docker Resources**:
   - Open Docker Desktop → Settings → Resources
   - Set Memory: Minimum 8GB (16GB recommended)
   - Set CPU: At least 4 cores
   - Set Disk: 50GB+
   - Apply & Restart

### Step 2: Install Development Tools

```bash
# Install Homebrew if not already installed
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# Install Git and Git LFS
brew install git git-lfs
git lfs install

# Install Python and uv for dependency management
brew install python@3.11 uv

# Install useful development tools
brew install jq yq watch tree htop
```

### Step 3: Clone the Repository

```bash
# Clone with submodules
git clone --recurse-submodules https://github.com/your-org/buttercup.git
cd buttercup

# If you already cloned without submodules
git submodule update --init --recursive
```

## Quick Start

### 1. Automated Setup

The fastest way to get started:

```bash
# Run the local development setup script
./local-dev.sh setup

# This will:
# - Check prerequisites
# - Create necessary directories
# - Configure environment
# - Build Docker images
# - Start all services
```

### 2. Manual Setup

If you prefer manual control:

```bash
# Copy environment template
cp env.template env.dev.compose

# Edit configuration (use your preferred editor)
nano env.dev.compose
```

Key settings to configure:
```bash
# Required: Add your LLM API keys
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...

# Optional: Adjust paths for macOS
BUTTERCUP_DATA_PATH=./crs_scratch
BUTTERCUP_TASKS_PATH=./tasks_storage

# Optional: Enable rosetta for x86 containers on Apple Silicon
# Add to Docker Desktop settings under "Use Rosetta for x86/amd64 emulation"
```

### 3. Start Services

```bash
# Start all services
./local-dev.sh up

# Or start with Docker Compose directly
docker compose up -d

# Check status
./local-dev.sh status
```

### 4. Verify Installation

```bash
# Check all services are running
docker compose ps

# Test endpoints
curl http://localhost:8000/health      # Task Server
curl http://localhost:1323/            # Buttercup UI
curl http://localhost:8080/health      # LiteLLM Proxy

# Submit a test task
./orchestrator/scripts/task_integration_test.sh
```

## macOS-Specific Configuration

### Apple Silicon Optimizations

For M1/M2/M3 Macs, optimize performance:

1. **Enable Rosetta 2 in Docker Desktop**:
   - Settings → General → Enable "Use Rosetta for x86/amd64 emulation"
   - This improves compatibility with x86 containers

2. **Use ARM64 Images When Available**:
   ```yaml
   # In compose.override.yaml
   services:
     redis:
       platform: linux/arm64
   ```

3. **Build Multi-Architecture Images**:
   ```bash
   # For custom images
   docker buildx build --platform linux/amd64,linux/arm64 -t myimage:latest .
   ```

### File System Performance

macOS file system can be slow with Docker volumes. Optimize by:

1. **Use delegated mounts**:
   ```yaml
   volumes:
     - ./src:/app/src:delegated
   ```

2. **Minimize bind mounts** in development
3. **Use named volumes** for better performance

### Network Configuration

```bash
# If you have firewall enabled, allow Docker
sudo /usr/libexec/ApplicationFirewall/socketfilterfw --add /Applications/Docker.app/Contents/MacOS/Docker
sudo /usr/libexec/ApplicationFirewall/socketfilterfw --unblockapp /Applications/Docker.app/Contents/MacOS/Docker
```

## Development Workflow

### 1. Code Organization

```
buttercup/
├── orchestrator/     # Central coordination
├── fuzzer/          # Vulnerability discovery
├── patcher/         # Patch generation
├── program-model/   # Code analysis
├── seed-gen/        # Test generation
├── common/          # Shared utilities
└── deployment/      # Docker configs
```

### 2. Development Commands

```bash
# Rebuild a specific service
./local-dev.sh rebuild patcher

# View logs for debugging
./local-dev.sh logs -f scheduler

# Enter a container for debugging
docker compose exec patcher /bin/bash

# Run tests for a component
cd patcher && uv run pytest

# Lint and format code
just lint-python patcher
```

### 3. Hot Reload Setup

Enable hot reload for faster development:

```yaml
# compose.override.yaml
services:
  patcher:
    volumes:
      - ./patcher/src:/app/src:delegated
    environment:
      - PYTHONUNBUFFERED=1
      - DEVELOPMENT=true
```

### 4. Debugging

**VS Code Configuration**:
```json
{
  "version": "0.2.0",
  "configurations": [
    {
      "name": "Python: Remote Attach",
      "type": "python",
      "request": "attach",
      "connect": {
        "host": "localhost",
        "port": 5678
      },
      "pathMappings": [
        {
          "localRoot": "${workspaceFolder}",
          "remoteRoot": "/app"
        }
      ]
    }
  ]
}
```

**Enable debugging in service**:
```python
# Add to your Python service
import debugpy
debugpy.listen(5678)
debugpy.wait_for_client()  # Pause until debugger connects
```

## Common Issues and Solutions

### 1. Docker Desktop Issues

**Problem**: Docker Desktop won't start
```bash
# Reset Docker Desktop
rm -rf ~/Library/Group\ Containers/group.com.docker
rm -rf ~/Library/Containers/com.docker.docker
rm -rf ~/.docker

# Restart Docker Desktop
open -a Docker
```

**Problem**: Out of disk space
```bash
# Clean up Docker resources
docker system prune -a --volumes
```

### 2. Permission Issues

**Problem**: Permission denied errors
```bash
# Fix ownership
sudo chown -R $(whoami):staff ./crs_scratch ./tasks_storage

# Or add to Docker group (create if needed)
sudo dseditgroup -o create docker
sudo dseditgroup -o edit -a $(whoami) -t user docker
```

### 3. Performance Issues

**Problem**: Slow container performance
- Increase Docker Desktop resources
- Disable Spotlight indexing on Docker volumes:
  ```bash
  sudo mdutil -i off /Users/$(whoami)/Library/Containers/com.docker.docker/Data
  ```

### 4. Network Issues

**Problem**: Cannot connect to services
```bash
# Check if ports are in use
lsof -i :8000
lsof -i :6379

# Check Docker network
docker network ls
docker network inspect bridge
```

### 5. Apple Silicon Compatibility

**Problem**: x86 container crashes
- Enable Rosetta in Docker Desktop
- Use platform flag: `docker run --platform linux/amd64 ...`
- Build multi-arch images when possible

## Tips and Tricks

### 1. Aliases for Common Commands

Add to `~/.zshrc` or `~/.bash_profile`:
```bash
alias bc="cd ~/path/to/buttercup"
alias bcup="./local-dev.sh up"
alias bcdown="./local-dev.sh down"
alias bclogs="./local-dev.sh logs -f"
alias bcstatus="./local-dev.sh status"
```

### 2. Resource Monitoring

```bash
# Monitor Docker resource usage
docker stats

# Monitor system resources
htop

# Check disk usage
df -h
du -sh ./crs_scratch
```

### 3. Quick Testing

```bash
# Create a test script
cat > quick-test.sh << 'EOF'
#!/bin/bash
echo "Testing Buttercup CRS..."
curl -s http://localhost:8000/health | jq .
curl -s http://localhost:8080/health | jq .
echo "Submitting test task..."
./orchestrator/scripts/task_integration_test.sh
EOF

chmod +x quick-test.sh
```

### 4. Development Environment Variables

Create `.env.local` for personal overrides:
```bash
# .env.local (git ignored)
LOG_LEVEL=DEBUG
TELEMETRY_ENABLED=false
PYTHONUNBUFFERED=1
```

## Advanced Configuration

### Using Multiple LLM Providers

Configure LiteLLM for multiple providers:
```yaml
# litellm/litellm_config.yaml
model_list:
  - model_name: gpt-4
    litellm_params:
      model: gpt-4
      api_key: ${OPENAI_API_KEY}
  
  - model_name: claude-3
    litellm_params:
      model: claude-3-sonnet-20240229
      api_key: ${ANTHROPIC_API_KEY}
```

### Custom Fuzzing Containers

For specialized fuzzing needs:
```yaml
# compose.override.yaml
services:
  unified-fuzzer:
    build:
      context: ./fuzzer
      dockerfile: dockerfiles/unified_fuzzer.Dockerfile
      args:
        CUSTOM_TOOLS: "afl++ honggfuzz"
```

### Integrating with IDEs

**PyCharm**:
- Use Docker Compose as Python interpreter
- Configure remote debugging
- Set up file watchers for auto-formatting

**VS Code**:
- Install Docker and Python extensions
- Use Dev Containers for isolated development
- Configure task runners for common commands

## Maintenance

### Regular Cleanup

```bash
# Weekly cleanup script
cat > cleanup.sh << 'EOF'
#!/bin/bash
echo "Cleaning up Docker resources..."
docker system prune -f
docker volume prune -f
echo "Cleaning up old logs..."
find ./crs_scratch -name "*.log" -mtime +7 -delete
echo "Done!"
EOF

chmod +x cleanup.sh
```

### Updating Components

```bash
# Update all images
docker compose pull

# Rebuild with latest changes
./local-dev.sh rebuild

# Update dependencies
cd patcher && uv lock --upgrade
```

## Getting Help

- Check logs: `./local-dev.sh logs <service>`
- Join development chat: [link]
- File issues: [GitHub Issues]
- Documentation: See `/docs` directory

Remember: The local development environment is optimized for ease of use and rapid iteration. For production deployments, additional security and scaling considerations apply.