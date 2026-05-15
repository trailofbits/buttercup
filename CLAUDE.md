# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Buttercup is a Cyber Reasoning System (CRS) developed by Trail of Bits for the AIxCC Finals competition. It automatically finds, analyzes, and patches vulnerabilities in software systems through a distributed microservices architecture.

## Common Development Commands

### Build and Development

```bash
# Build specific component (from project root)
make lint-component COMPONENT=<component>  # Format, lint, and type-check a component
make lint                                   # Format, lint, and type-check all components

# Example: lint the patcher component
make lint-component COMPONENT=patcher

# Regenerate protobuf files (MUST run from common venv for correct grpcio-tools)
cd common && uv run ../protoc.sh
```

### Testing

```bash
# Run tests in specific component
cd <component> && uv run pytest

# Run tests with coverage
cd <component> && uv run pytest --cov

# Common test commands per component:
cd common && uv run pytest
cd orchestrator && uv run pytest
cd fuzzer && uv run pytest
cd patcher && uv run pytest
cd program-model && uv run pytest
cd seed-gen && uv run pytest
```

### Local Development Setup

```bash
# Start the full CRS system
cd deployment && make up

# Stop the system
cd deployment && make down

# Port forward for local testing
kubectl port-forward -n crs service/buttercup-competition-api 31323:1323
```

### Python Package Management

Each component uses `uv` for dependency management:

```bash
# Install dependencies
cd <component> && uv sync

# Install with dev dependencies
cd <component> && uv sync --all-extras

# Add new dependency
cd <component> && uv add <package>

# Update dependencies
cd <component> && uv lock --upgrade
```

## System Architecture

### Core Components

**Common** (`/common/`): Shared utilities, protobuf definitions, Redis queue management, telemetry
**Orchestrator** (`/orchestrator/`): Central coordination, task server, scheduler, competition API client
**Fuzzer** (`/fuzzer/`): Automated vulnerability discovery (build-bot, fuzzer-bot, coverage-bot, tracer-bot)
**Program Model** (`/program-model/`): Semantic code analysis using CodeQuery and Tree-sitter
**Patcher** (`/patcher/`): LLM-powered automated patch generation
**Seed Generation** (`/seed-gen/`): Intelligent test case generation

### Key Data Flow

1. Competition API → Task Server → Task Downloader
2. Program Model indexes code → Graph database
3. Build Bot compiles fuzzing harnesses
4. Fuzzer Bot executes tests, Coverage/Tracer Bots monitor
5. Seed-gen creates targeted inputs
6. Patcher generates/validates fixes
7. Results submitted back to competition API

### Inter-service Communication

- **Redis**: Primary message broker with reliable queues
- **Protobuf**: Structured message serialization
- **REST APIs**: External interfaces and coordination
- **Shared Storage**: Docker volumes for large artifacts

## Key Technologies

- **Languages**: Python (primary), supports C/C++/Java analysis
- **Containerization**: Docker, Kubernetes microservices
- **AI/ML**: OpenAI GPT, Anthropic Claude via LiteLLM proxy
- **Fuzzing**: OSS-Fuzz, libfuzzer
- **Code Analysis**: CodeQuery, Tree-sitter
- **Databases**: Redis
- **Monitoring**: OpenTelemetry, Langfuse

## Development Patterns

### Error Handling

- Use structured logging via the common logging module
- Implement circuit breakers for external service calls
- Handle Redis connection failures gracefully

### Configuration

- Environment variables defined in `deployment/env.template`
- Pydantic Settings for type-safe configuration
- Component-specific settings in each module's `config.py`

### Dev Testing

- Use pytest for all Python components
- Mock external dependencies (Redis, LLM APIs, file system)
- Integration tests use Docker containers
- Test data stored in `<component>/tests/data/`
- **Redis-dependent tests**: Several components (common, orchestrator, patcher, fuzzer, seed-gen) have tests that require a running Redis instance. Do not skip these tests. Start a temporary Redis container before running tests:
  ```bash
  docker run -d --name redis-temp -p 6379:6379 redis:latest
  # Run tests...
  docker stop redis-temp && docker rm redis-temp
  ```

### Code Quality

- All components use `ruff` for formatting and linting
- `mypy` for static type checking
- Line length: 120 characters
- Pydantic models for data validation

### Code Navigation

- Use `get_symbols_overview` before reading full files to understand structure
- Use `find_symbol` to locate classes/functions across components
- Use `find_referencing_symbols` to trace message flow between services
- Use `search_for_pattern` for non-code files (YAML, proto, configs)
- Prefer symbol-based edits (`replace_symbol_body`, `insert_after_symbol`) over line-based edits

## Deployment Architecture

The system runs as Kubernetes microservices with Helm charts in `/deployment/k8s/`:

- **API Layer**: task-server, competition-api
- **Processing**: scheduler, downloader, program-model
- **Fuzzing**: build-bot, fuzzer-bot, coverage-bot, tracer-bot
- **Analysis**: patcher, seed-gen
- **Infrastructure**: redis, litellm, dind-daemon

## Common Debugging Commands

```bash
# Check pod status
kubectl get pods -n crs

# View logs
kubectl logs -n crs -l app=<service-name> --tail=100

# Debug inside pod
kubectl exec -it -n crs <pod-name> -- /bin/bash

# Monitor scheduler workflow
kubectl logs -n crs -l app=scheduler --tail=-1 --prefix | grep "WAIT_PATCH_PASS -> SUBMIT_BUNDLE"
```

## Security Considerations

- All untrusted code execution happens in isolated Docker containers
- DinD (Docker-in-Docker) provides additional isolation
- Redis queues use consumer groups for reliable message processing
- No direct file system access between components (shared volumes only)
