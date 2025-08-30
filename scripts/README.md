# Buttercup Scripts

This directory contains utility scripts for the Buttercup CRS project.

## lint-changed-files.sh

A smart linting orchestrator that automatically detects which component files belong to and runs the appropriate linters. This script is optimized for use with AI coding assistants.

### Features

- **Dynamic component discovery** - Automatically finds components with `pyproject.toml`
- **Component-aware linting** - Uses each component's specific ruff configuration
- **Multiple output formats** - Human-readable text or machine-parseable JSON
- **Comprehensive error handling** - Never silently fails
- **Smart dependency caching** - Only syncs when pyproject.toml changes
- **AI-optimized** - Deterministic behavior for reliable automation

### Usage

```bash
# Check files (default mode)
scripts/lint-changed-files.sh check path/to/file.py

# Fix issues automatically
scripts/lint-changed-files.sh fix path/to/file.py

# Multiple files
scripts/lint-changed-files.sh fix file1.py file2.py file3.py

# Plain output (no colors) - useful for CI or AI tools
scripts/lint-changed-files.sh --plain check file.py

# JSON output for parsing - ideal for AI tools
scripts/lint-changed-files.sh --format=json check file.py
```

### Integration with AI Coding Assistants

This script is optimized for use with AI coding assistants like Claude Code, Cursor, and GitHub Copilot.

#### Why AI-Optimized?

AI coding assistants need:
- **Deterministic behavior** - Same input always produces same output
- **Clear error messages** - That can be parsed and understood
- **Automatic fixing** - No manual intervention required
- **Structured output** - JSON format for reliable parsing
- **No interactive prompts** - Fully automated operation

#### Recommended Usage for AI Tools

```bash
# For AI tools, use JSON output and fix mode
scripts/lint-changed-files.sh --format=json fix file.py

# The JSON output includes:
# - status: "success" or "error"
# - mode: "check" or "fix"
# - total_files: Number of files provided
# - files_processed: Files actually linted
# - files_skipped: Files not in components
# - components_checked: Number of components
# - errors: Array of components that failed
```

#### Example JSON Output

Success:
```json
{
  "status": "success",
  "mode": "fix",
  "total_files": 3,
  "files_processed": 3,
  "files_skipped": 0,
  "components_checked": 2,
  "errors": []
}
```

Error:
```json
{
  "status": "error",
  "mode": "check",
  "total_files": 2,
  "files_processed": 2,
  "files_skipped": 0,
  "components_checked": 1,
  "errors": ["orchestrator"]
}
```

### How It Works

1. **Component Discovery**: Finds all directories with `pyproject.toml`
2. **File Classification**: Maps each input file to its component
3. **Dependency Management**: Ensures `uv sync` is run when needed
4. **Linting**: Runs both `ruff format` and `ruff check` per component
5. **Result Aggregation**: Combines results from all components

### Requirements

- `uv` package manager installed
- Python 3.12+ 
- Each component must have:
  - `pyproject.toml` file
  - Ruff configuration in pyproject.toml

### Exit Codes

- `0`: All checks passed
- `1`: One or more checks failed

### Environment Variables

The script respects terminal capabilities and will automatically disable colors when:
- Output is piped to another command
- `--plain` flag is used
- `--format=json` is specified

## Other Scripts

### setup-local.sh
Sets up the local development environment for Buttercup.

### setup-azure.sh
Configures Azure resources for production deployment.

### validate-setup.sh
Validates that the environment is correctly configured.

### common.sh
Shared utilities used by other scripts.