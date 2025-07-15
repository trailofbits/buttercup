# Buttercup CRS - Local Docker Compose Deployment

## Overview

This directory contains configuration and scripts for deploying the Buttercup Cyber Reasoning System (CRS) locally using Docker Compose. The deployment has been simplified to focus on local development and testing scenarios.

## Prerequisites

- Docker Engine 20.10+ with Docker Compose v2
- At least 16GB of RAM available for Docker
- 50GB+ of free disk space
- Linux or macOS (Windows users should use WSL2)

### Required API Keys

You'll need at least one LLM API key:
- OpenAI API key, OR
- Anthropic API key

## Quick Start

1. **Copy the environment template**:
   ```bash
   cp env.template ../env.dev.compose
   ```

2. **Edit the environment file** (`../env.dev.compose`):
   - Add your OpenAI and/or Anthropic API keys
   - Configure any optional services you need
   - Review and adjust other settings as needed

3. **Start the services**:
   ```bash
   make up
   ```

4. **Check service status**:
   ```bash
   make status
   ```

5. **View logs**:
   ```bash
   make logs  # All services
   make logs-scheduler  # Specific service
   ```

## Available Commands

The Makefile provides convenient commands for managing the deployment:

- `make up` - Start all services
- `make down` - Stop all services  
- `make restart` - Restart all services
- `make logs` - View logs for all services
- `make status` - Show status of all services
- `make clean` - Remove volumes and clean up
- `make logs-<service>` - View logs for a specific service
- `make restart-<service>` - Restart a specific service

## Services

The Docker Compose deployment includes the following services:

### Core Infrastructure
- **redis** - Message broker and cache
- **dind** - Docker-in-Docker for isolated container execution
- **litellm** - LLM proxy for unified API access
- **litellm-db** - PostgreSQL database for LiteLLM

### CRS Components
- **task-server** - REST API for task management
- **task-downloader** - Downloads challenge tasks
- **scheduler** - Orchestrates the vulnerability discovery workflow
- **program-model** - Code analysis and indexing service
- **build-bot** - Builds fuzzing harnesses
- **fuzzer-bot** - Executes fuzzing campaigns
- **coverage-bot** - Monitors code coverage
- **tracer-bot** - Traces program execution
- **seed-gen** - Generates test inputs using LLMs
- **patcher** - Creates patches for discovered vulnerabilities
- **buttercup-ui** - Web interface for monitoring

### Optional Services
- **mock-competition-api** - Local testing API
- **graphdb** - JanusGraph for code relationship storage (profile: graphdb)

## Directory Structure

```
deployment/
├── Makefile          # Convenience commands for Docker Compose
├── env.template      # Environment configuration template
└── README.md         # This file
```

## Environment Configuration

The `env.template` file contains all configurable options grouped by category:

- **Core Service Configuration** - Basic CRS settings
- **LLM Configuration** - API keys for language models
- **Container Registry Configuration** - Docker registry authentication
- **Optional Services** - Telemetry, monitoring, etc.
- **Competition API Configuration** - For connecting to competitions
- **Local Development Settings** - Paths and development options

## Accessing Services

Once deployed, you can access:

- **Task Server API**: http://localhost:8000
- **Buttercup UI**: http://localhost:1323
- **LiteLLM Proxy**: http://localhost:8080
- **Redis**: localhost:6379

## Storage Volumes

The deployment creates several Docker volumes for persistent storage:

- `crs_scratch` - Working directory for tasks
- `tasks_storage` - Downloaded task data
- `node_data_storage` - Node-specific data
- `cache` - Redis data (if persistence enabled)
- `graphdb_data` - Graph database storage

## Troubleshooting

### Services failing to start
- Check Docker daemon is running: `docker ps`
- Ensure sufficient resources are available
- Review logs: `make logs-<service>`

### LLM errors
- Verify API keys are correctly set in env.dev.compose
- Check LiteLLM service is healthy: `make logs-litellm`

### Out of disk space
- Clean up volumes: `make clean`
- Remove unused Docker images: `docker image prune`

### Permission issues
- Ensure the crs_scratch directory has proper permissions
- On Linux, you may need to adjust Docker group membership

## Development Tips

1. **Selective service startup**: Edit compose.yaml to comment out unneeded services
2. **Resource limits**: Add resource constraints to services in compose.yaml if needed
3. **Debugging**: Use `docker compose exec <service> /bin/bash` to access containers
4. **Hot reload**: Most Python services support hot reload during development

## Advanced Configuration

### Using Graph Database

To enable the graph database for advanced code analysis:

```bash
docker compose --profile graphdb up -d
```

### Custom Fuzzing Containers

Set `FUZZ_TOOLING_CONTAINER_ORG` in your environment file to use custom fuzzing containers.

### Monitoring and Telemetry

Configure LangFuse or OpenTelemetry endpoints in the environment file for observability.

## Support

For issues and questions:
- Check the main project README
- Review service-specific documentation in their directories
- Examine logs for error messages