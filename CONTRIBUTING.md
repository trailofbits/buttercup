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
cargo install prek    # Fast Rust-based git hooks
prek install          # Auto-runs checks on commit
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

- **Tools:** `ruff` (formatting/linting), `ty` (type checking)
- **Git hooks:** `prek` automatically validates code, configs, and line endings on commit
- **Manual checks:** `prek run` or `make lint`

### Test Prerequisites

**Redis** (required for unit tests):
```bash
# Start Redis with Docker
docker run -d -p 6379:6379 --name buttercup-redis redis:7.4

# Or on macOS with Homebrew
brew install redis && brew services start redis
```

**System dependencies** (varies by component):

| Component | Dependencies |
|-----------|-------------|
| common, orchestrator | `ripgrep` |
| fuzzer, fuzzer_runner | `ripgrep` |
| program-model, patcher, seed-gen | `ripgrep`, `codequery`, `universal-ctags`, custom cscope |

```bash
# macOS
brew install ripgrep codequery universal-ctags autoconf automake
git submodule update --init external/buttercup-cscope
make install-cscope

# IMPORTANT: universal-ctags must be in PATH before BSD ctags (macOS default).
# BSD ctags is incompatible with cscope/codequery. Add to ~/.zshrc or ~/.bashrc:
export PATH="/opt/homebrew/bin:$PATH"

# Ubuntu/Debian
sudo apt-get install -y ripgrep codequery universal-ctags autoconf automake
git submodule update --init external/buttercup-cscope
make install-cscope
```

**seed-gen only** - requires WASM Python build path:
```bash
export PYTHON_WASM_BUILD_PATH="python-3.12.0.wasm"
```

### Testing Strategy

1. **Unit Tests** (5-10 min): Run on all PRs
   ```bash
   cd <component> && uv run pytest
   ```

2. **Integration Tests** (15-30 min): Daily or with `integration-tests` label
   ```bash
   # Requires: codequery, ripgrep, cscope (for program-model, patcher, seed-gen)
   # Requires: NODE_DATA_DIR env var pointing to writable scratch directory
   NODE_DATA_DIR=/tmp/buttercup_test uv run pytest --runintegration
   ```

   **macOS limitations:** Some integration tests require Docker builds that only work on
   x86_64 Linux (CI). Tests that work locally on macOS ARM64:
   - `common/tests/test_reliable_queue.py` - Redis queue tests
   - `program-model/tests/test_tree_sitter.py` - Tree-sitter parsing
   - `patcher/tests/test_utils.py`, `test_context_retriever.py` - Patcher utilities
   - `seed-gen/test/test_find_harness.py` - Harness finding (some skipped)

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
| `/fuzzer_runner/` | Fuzzer execution runner |
| `/program-model/` | Code analysis (CodeQuery, Tree-sitter) |
| `/patcher/` | LLM-powered patch generation |
| `/seed-gen/` | Intelligent input generation |

## Contribution Process

1. **Branch** from main: `git checkout -b feature/your-feature`
2. **Code** following existing patterns and conventions
3. **Test** your changes at appropriate level
4. **Commit** (prek hooks run automatically if installed)
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
- **Tests failing?** Ensure Redis is running (see [Test Prerequisites](#test-prerequisites)) and dependencies are installed with `cd <component> && uv sync`
- **Missing system tools?** See the [Test Prerequisites](#test-prerequisites) table for component-specific dependencies

## Resources

- [Quick Reference](guides/QUICK_REFERENCE.md) - Common commands and troubleshooting
- [Deployment Guide](deployment/README.md) - Detailed deployment information
- [Custom Challenges](guides/CUSTOM_CHALLENGES.md) - Adding new test cases

## Questions?

Open an issue or reach out to the development team.
