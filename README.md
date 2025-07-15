# Buttercup Cyber Reasoning System (CRS)

**Buttercup** is a Cyber Reasoning System (CRS) developed by **Trail of Bits** for the **DARPA AIxCC (AI Cyber Challenge) competition**. It's a comprehensive automated vulnerability detection and patching system designed to compete in AI-driven cybersecurity challenges.

## System Requirements

- **Operating System**: macOS 11+ or Linux (Windows via WSL2)
- **Docker**: Docker Desktop 4.26+ with Docker Compose v2
- **Memory**: 16GB RAM minimum (32GB recommended)
- **Storage**: 50GB+ free disk space
- **API Keys**: OpenAI and/or Anthropic API keys

## Quick Start

Clone the repository with submodules:

```bash
git clone --recurse-submodules https://github.com/your-org/buttercup.git
cd buttercup
```

Then run the automated setup:

```bash
# Automated setup and start
./local-dev.sh setup

# Or manual setup
cp env.template env.dev.compose
# Edit env.dev.compose with your API keys
docker compose up -d
```

## Installation

### Prerequisites

1. **Install Docker Desktop**:
   - **macOS**: [Download Docker Desktop](https://www.docker.com/products/docker-desktop/)
   - **Linux**: Follow the [official Docker installation guide](https://docs.docker.com/engine/install/)
   - **Windows**: Use WSL2 and install Docker Desktop

2. **Configure Docker Resources**:
   - Open Docker Desktop settings
   - Allocate at least 8GB RAM (16GB recommended)
   - Allocate at least 4 CPU cores
   - Ensure 50GB+ disk space available

3. **Get API Keys**:
   - [OpenAI API Key](https://platform.openai.com/api-keys) (required)
   - [Anthropic API Key](https://console.anthropic.com/) (optional)

### Setup

1. **Configure Environment**:
   ```bash
   # Copy the environment template
   cp env.template env.dev.compose
   
   # Edit with your API keys
   # Required: Set OPENAI_API_KEY and/or ANTHROPIC_API_KEY
   nano env.dev.compose
   ```

2. **Start Services**:
   ```bash
   # Using the convenience script (recommended)
   ./local-dev.sh up
   
   # Or using Docker Compose directly
   docker compose up -d
   ```

3. **Verify Installation**:
   ```bash
   # Check service status
   ./local-dev.sh status
   
   # Test the APIs
   curl http://localhost:8000/health   # Task Server
   curl http://localhost:1323/         # Web UI
   ```

### Quick Test

Submit a test challenge to verify everything is working:

```bash
./orchestrator/scripts/task_integration_test.sh
```

Monitor the progress in the web UI at http://localhost:1323

## Service Access

Once running, you can access:

- **Task Server API**: http://localhost:8000
- **Buttercup Web UI**: http://localhost:1323  
- **LiteLLM Proxy**: http://localhost:8080
- **Redis**: localhost:6379
- **Mock Competition API**: http://localhost:31323 (for testing)

## Architecture Overview

Buttercup CRS uses a microservices architecture with the following components:

```
┌─────────────────┐     ┌──────────────┐     ┌─────────────┐
│  Competition    │────▶│ Task Server  │────▶│  Scheduler  │
│     API         │     │   (REST API) │     │ (Orchestrator)│
└─────────────────┘     └──────────────┘     └─────────────┘
                                                     │
                        ┌────────────────────────────┼────────────────────┐
                        │                            │                    │
                        ▼                            ▼                    ▼
┌─────────────────┐     ┌──────────────┐     ┌─────────────┐    ┌──────────────┐
│ Unified Fuzzer  │────▶│    Redis     │◀────│   Patcher   │    │ Program Model│
│ (Build/Fuzz/    │     │ (Message Bus)│     │ (LLM-based) │    │ (Code Analysis)│
│  Coverage/Trace)│     └──────────────┘     └─────────────┘    └──────────────┘
└─────────────────┘              │                                        ▲
                                 │            ┌─────────────┐             │
                                 └───────────▶│  Seed Gen   │─────────────┘
                                              │ (Test Gen)  │
                                              └─────────────┘
```

### Core Components

- **Task Server**: REST API for receiving vulnerability discovery tasks
- **Scheduler**: Orchestrates the entire vulnerability discovery and patching workflow
- **Unified Fuzzer**: Combines build, fuzzing, coverage, and crash analysis in one service
- **Program Model**: Analyzes code structure using CodeQuery and Tree-sitter
- **Patcher**: Uses LLMs to generate patches for discovered vulnerabilities
- **Seed Generator**: Creates intelligent test inputs using LLM-guided generation
- **Redis**: Central message bus for inter-service communication

### Key Features

- **Automated Vulnerability Discovery**: Intelligent fuzzing with coverage guidance
- **LLM-Powered Patching**: Generates contextual patches using GPT-4/Claude
- **Language Support**: C/C++, Java, Python analysis and patching
- **Distributed Architecture**: Scalable microservices design
- **Real-time Monitoring**: Web UI for tracking progress

## Development Workflow

### Common Commands

The `local-dev.sh` script provides convenient commands:

```bash
# Service Management
./local-dev.sh up          # Start all services
./local-dev.sh down        # Stop all services
./local-dev.sh restart     # Restart all services
./local-dev.sh status      # Check service status

# Debugging
./local-dev.sh logs        # View all logs
./local-dev.sh logs patcher # View specific service logs
./local-dev.sh shell patcher # Enter service container

# Development
./local-dev.sh rebuild     # Rebuild all images
./local-dev.sh clean       # Clean up volumes and data
```

### Running Tests

```bash
# Submit test challenges
./orchestrator/scripts/task_integration_test.sh
./orchestrator/scripts/challenge.sh

# Run component tests
cd patcher && uv run pytest
cd orchestrator && uv run pytest

# Lint and format code
just lint-python-all
just lint-python patcher
```

### Live Development

For hot-reloading during development, create `compose.override.yaml`:

```yaml
services:
  patcher:
    volumes:
      - ./patcher/src:/app/src:delegated
    environment:
      - DEVELOPMENT=true
  
  scheduler:
    volumes:
      - ./orchestrator/src:/app/src:delegated
    environment:
      - DEVELOPMENT=true
```

### Monitoring and Debugging

```bash
# Monitor resource usage
docker stats

# Follow scheduler logs
docker compose logs -f scheduler

# Check Redis queues
docker compose exec redis redis-cli
> KEYS *
> LLEN task_queue

# Access web UI
open http://localhost:1323
```

## Troubleshooting

### Common Issues

1. **Docker Desktop not starting (macOS)**:
   ```bash
   # Reset Docker Desktop
   rm -rf ~/Library/Group\ Containers/group.com.docker
   rm -rf ~/Library/Containers/com.docker.docker
   open -a Docker
   ```

2. **Port conflicts**:
   ```bash
   # Check what's using the ports
   lsof -i :8000
   lsof -i :6379
   
   # Change ports in compose.yaml if needed
   ```

3. **Permission issues**:
   ```bash
   # Fix directory permissions
   sudo chown -R $(whoami):$(whoami) ./crs_scratch ./tasks_storage
   ```

4. **Out of memory**:
   - Increase Docker Desktop memory allocation
   - Reduce service replicas in compose.yaml
   - Stop unnecessary services

5. **LLM API errors**:
   - Verify API keys in env.dev.compose
   - Check LiteLLM logs: `./local-dev.sh logs litellm`
   - Ensure you have credits/quota for your API keys

### Getting Help

- **Documentation**:
  - [Local Development Guide](LOCAL_DEVELOPMENT.md) - Detailed setup for macOS
  - [Quick Reference](QUICK_REFERENCE.md) - Common commands
  - [Migration Guide](MIGRATION_GUIDE.md) - Moving from Kubernetes
  - [Deployment README](deployment/README.md) - Docker Compose details

- **Debugging**:
  - Check logs: `./local-dev.sh logs <service-name>`
  - View events: `docker compose events`
  - Shell access: `./local-dev.sh shell <service-name>`

## Project Structure

```
buttercup/
├── orchestrator/        # Central coordination and task management
├── fuzzer/             # Unified fuzzing infrastructure
├── patcher/            # LLM-based patch generation
├── program-model/      # Code analysis and indexing
├── seed-gen/           # Intelligent test case generation
├── common/             # Shared utilities and protobuf definitions
├── docker/             # Docker configurations and optimizations
├── deployment/         # Deployment configurations
├── compose.yaml        # Main Docker Compose configuration
├── compose.override.yaml # Local development overrides
├── env.dev.compose     # Environment configuration
└── local-dev.sh        # Convenience script for development
```

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development guidelines.

## License

This project is licensed under the Apache License 2.0 - see the [LICENSE](LICENSE) file for details.

## Acknowledgments

- Developed by Trail of Bits for the DARPA AIxCC competition
- Built on top of OSS-Fuzz infrastructure
- Powered by OpenAI GPT-4 and Anthropic Claude for intelligent analysis
