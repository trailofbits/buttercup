# Contributing to Buttercup CRS

Thank you for contributing to the Buttercup Cyber Reasoning System!

## Quick Start

```bash
# Clone and setup
git clone --recurse-submodules https://github.com/trailofbits/buttercup.git
cd buttercup
make setup-local      # Automated setup
make deploy           # Start environment

# Setup development tools (optional but recommended)
pip install pre-commit
pre-commit install    # Auto-runs checks on commit
```

## Development Workflow

### Essential Commands

```bash
make help                    # View all commands
make lint                    # Lint all components
make lint-component COMPONENT=orchestrator  # Lint specific component
make send-libpng-task        # Run test task
make status                  # Check deployment status
make undeploy                # Clean up resources
```

### Code Quality

- **Tools:** `ruff` (formatting/linting), `mypy` (type checking)
- **Pre-commit:** Automatically validates code, configs, and line endings
- **Manual checks:** `pre-commit run --all-files`

### Testing Strategy

1. **Unit Tests** (5-10 min): Run on all PRs
   ```bash
   cd <component> && uv run pytest
   ```

2. **Integration Tests** (15-30 min): Daily or with `integration-tests` label
   ```bash
   # Requires: codequery, ripgrep, cscope (for program-model, patcher, seed-gen)
   cd <component> && uv run pytest --runintegration
   ```

3. **Full System** (90+ min): Weekly or with `full-integration` label
   ```bash
   make deploy && make send-libpng-task
   ```

## Project Structure

| Component | Purpose |
|-----------|---------|
| `/common/` | Shared utilities, protobufs, Redis queues |
| `/orchestrator/` | Task coordination, scheduling, API client |
| `/fuzzer/` | Vulnerability discovery bots |
| `/program-model/` | Code analysis (CodeQuery, Tree-sitter) |
| `/patcher/` | LLM-powered patch generation |
| `/seed-gen/` | Intelligent input generation |

## Contribution Process

1. **Branch** from main: `git checkout -b feature/your-feature`
2. **Code** following existing patterns and conventions
3. **Test** your changes at appropriate level
4. **Commit** (pre-commit runs automatically if installed)
5. **Push** and create PR with clear description

### Python Dependencies

Each component uses `uv`:
```bash
cd <component>
uv sync                # Install dependencies
uv add <package>       # Add new dependency
uv lock --upgrade      # Update dependencies
```

## Guidelines

### Code Style
- Follow existing patterns in each component
- Use structured logging and Pydantic models
- Handle errors with circuit breakers for external services
- Write tests for new functionality

### PR Labels
- `integration-tests` - Triggers component integration tests
- `full-integration` - Triggers full system test (use sparingly)

## Debugging

```bash
# Kubernetes commands
kubectl logs -n crs -l app=<service> --tail=100
kubectl exec -it -n crs <pod> -- /bin/bash
kubectl port-forward -n crs service/buttercup-competition-api 31323:1323
```

## Getting Help

- **Environment issues?** Run `make validate` to check if your setup is ready
- **Component won't build?** Check if you need codequery, ripgrep, or cscope installed
- **Tests failing?** Verify dependencies with `cd <component> && uv sync`

## Resources

- [Quick Reference](guides/QUICK_REFERENCE.md) - Common commands and troubleshooting
- [Deployment Guide](deployment/README.md) - Detailed deployment information
- [Custom Challenges](guides/CUSTOM_CHALLENGES.md) - Adding new test cases

## Questions?

Open an issue or reach out to the development team.
