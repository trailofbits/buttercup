# Contributing to Buttercup CRS

Thank you for your interest in contributing to the Buttercup Cyber Reasoning System! This guide will help you get started with development and understand our workflows.

## Development Setup

### Prerequisites

- Python 3.12+ (project requirement)
- Docker and Docker Compose
- `uv` for Python dependency management
- `pre-commit` for code quality checks

### Initial Setup

Before contributing, set up your local development environment:

```bash
# Clone with submodules
git clone --recurse-submodules https://github.com/trailofbits/buttercup.git

# Install Python 3.12 if needed (via uv)
uv python install 3.12

# Quick setup (recommended)
make setup-local

# Install pre-commit hooks
pip install pre-commit
pre-commit install

# Start development environment
make deploy-local
```

### Pre-commit Hooks

This project uses pre-commit hooks to ensure code consistency. The hooks will run automatically on `git commit`. To run manually:

```bash
# Run on staged files
pre-commit run

# Run on all files
pre-commit run --all-files
```

**Note:** Pre-commit requires Python 3.12 to match the project's Python version. If you encounter Python version issues, ensure Python 3.12 is available in your PATH or use `uv` to manage Python versions.

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

### Integration Testing

Buttercup has three tiers of testing to balance thoroughness with CI resources:

#### Test Tiers

1. **Unit Tests** (5-10 min)
   - Run automatically on all PRs and pushes
   - Fast, focused tests without external dependencies
   - Run with: `pytest` (no flags)

2. **Component Integration Tests** (15-30 min)
   - Test interactions with Redis, CodeQuery, file systems
   - Require additional setup (codequery, ripgrep, cscope)
   - Run with: `pytest --runintegration`
   - **When they run:**
     - Daily at 2 AM UTC (automated)
     - PRs labeled with `integration-tests`
     - Manual trigger via Actions tab

3. **Full System Integration** (90+ min)
   - Complete end-to-end test with Minikube
   - Tests full CRS workflow: fuzzing → vuln discovery → patching
   - **When they run:**
     - Weekly on Sundays at 3 AM UTC
     - PRs labeled with `full-integration`
     - Manual trigger via Actions tab

#### Running Integration Tests Locally

```bash
# Component integration tests
cd <component>
uv run pytest --runintegration

# Full system test
make deploy-local
make send-libpng-task
# Monitor with: kubectl logs -n crs -l app=scheduler --tail=-1
```

#### Triggering Integration Tests on PRs

Add labels to your PR:
- `integration-tests` - Runs component integration tests
- `full-integration` - Runs full Minikube system test

**Note:** Use these labels judiciously as integration tests consume significant CI resources.

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

### Pre-commit Hooks

This project uses pre-commit hooks to ensure code quality before commits. To set them up:

```bash
# Install pre-commit (one-time setup)
pip install pre-commit

# Install the git hooks
pre-commit install

# Run hooks manually on all files (optional)
pre-commit run --all-files
```

The hooks will automatically:
- Format code with `ruff format`
- Check for linting issues with `ruff check`
- Fix trailing whitespace and file endings
- Check for merge conflicts and large files

To bypass hooks in an emergency: `git commit --no-verify`

## Getting Help

- **Validate your setup:** `make validate` - Check if your environment is ready
- Check the [Quick Reference Guide](QUICK_REFERENCE.md) for common commands and troubleshooting
- Check the [deployment README](deployment/README.md) for detailed deployment information
- Check logs: `kubectl logs -n crs <pod-name>`

## Questions?

If you have questions about contributing, please feel free to open an issue or reach out to the development team.
