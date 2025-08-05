# Contributing to Buttercup CRS

Thank you for your interest in contributing to the Buttercup Cyber Reasoning System! This guide will help you get started with development and understand our workflows.

## Development Setup

Before contributing, set up your local development environment:

```bash
# Clone with submodules
git clone --recurse-submodules https://github.com/trailofbits/buttercup.git

# Quick setup (recommended)
make setup-local

# Start development environment
make deploy-local
```

## Development Workflow

### Using Makefile Shortcuts

The **Buttercup CRS** project includes a Makefile with convenient shortcuts for common tasks:

```bash
# View all available commands
make help

# Setup
make setup-local          # Automated local development setup
make setup-azure          # Automated production AKS setup
make validate             # Validate current setup and configuration

# Deployment
make deploy               # Deploy to current environment (local or azure)
make deploy-local         # Deploy to local Minikube environment
make deploy-azure         # Deploy to production AKS environment

# Status
make status               # Check the status of the deployment

# Testing
make send-libpng-task          # Run libpng test task

# Development
make lint                 # Lint all Python code
make lint-component COMPONENT=orchestrator  # Lint specific component

# Cleanup
make undeploy             # Remove deployment and clean up resources
make clean-local          # Delete Minikube cluster and remove local config
```

### Code Quality Standards

All Python components use consistent formatting and linting standards:

- **Formatter:** `ruff format`
- **Linter:** `ruff check`
- **Type Checker:** `mypy` (for common, patcher, and program-model components)

### Running Tests

```bash
# Lint all Python code
make lint

# Lint specific component
make lint-component COMPONENT=orchestrator

# Run test task
make send-libpng-task
```


### Development Tools


#### Kubernetes Development

```bash
# Port forward for local access  
kubectl port-forward -n crs service/buttercup-competition-api 31323:1323

# View logs
kubectl logs -n crs -l app=scheduler --tail=-1 --prefix

# Debug pods
kubectl exec -it -n crs <pod-name> -- /bin/bash
```

## Component Architecture

The system consists of several key components:

- **Common** (`/common/`): Shared utilities, protobuf definitions, Redis queue management, telemetry
- **Orchestrator** (`/orchestrator/`): Central coordination, task server, scheduler, competition API client
- **Fuzzer** (`/fuzzer/`): Automated vulnerability discovery (build-bot, fuzzer-bot, coverage-bot, tracer-bot)
- **Program Model** (`/program-model/`): Semantic code analysis using CodeQuery and Tree-sitter
- **Patcher** (`/patcher/`): LLM-powered automated patch generation
- **Seed Generation** (`/seed-gen/`): Intelligent input generation

## Contribution Guidelines

### Code Style

- Follow existing code patterns and conventions in each component
- Use structured logging via the common logging module
- Implement proper error handling with circuit breakers for external service calls
- Use Pydantic models for data validation
- Write comprehensive tests for new functionality

### Testing

Each component should include:

- Unit tests using pytest
- Mock external dependencies (Redis, LLM APIs, file system)
- Integration tests using Docker containers
- Test data stored in `<component>/tests/data/`

### Security Considerations

- All untrusted code execution must happen in isolated Docker containers
- Never expose or log secrets and keys
- Never commit secrets or keys to the repository

### Submitting Changes

1. **Create a feature branch** from the main branch
2. **Make your changes** following the code style guidelines
3. **Test your changes** using the appropriate test commands
4. **Lint your code** using `make lint` or component-specific linting
5. **Create a pull request** with a clear description of your changes


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

## Getting Help

- **Validate your setup:** `make validate` - Check if your environment is ready
- Check the [Quick Reference Guide](QUICK_REFERENCE.md) for common commands and troubleshooting
- Check the [deployment README](deployment/README.md) for detailed deployment information
- Check logs: `kubectl logs -n crs <pod-name>`

## Questions?

If you have questions about contributing, please feel free to open an issue or reach out to the development team.