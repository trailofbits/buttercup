# Buttercup Scripts

This directory contains utility scripts for the Buttercup CRS project.

## lint-changed-files.sh

A smart linting orchestrator that automatically detects which component files belong to and runs the appropriate linters.

### Features

- **Dynamic component discovery** - Automatically finds components with `pyproject.toml`
- **Component-aware linting** - Uses each component's specific ruff configuration
- **Multiple output formats** - Human-readable text or machine-parseable JSON
- **Comprehensive error handling** - Never silently fails
- **Smart dependency caching** - Only syncs when needed

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
# - mode: "check" or "fix"
# - total_files: Number of files provided
# - files_processed: Files actually linted
# - files_skipped: Files not in components
# - components_checked: Number of components
# - status: 0 for success, 1 for issues
# - components: Array of per-component results
```

#### Example JSON Output

```json
{
  "mode": "fix",
  "total_files": 2,
  "files_processed": 2,
  "files_skipped": 0,
  "components_checked": 1,
  "status": 0,
  "components": [
    {
      "component": "common",
      "files": 2,
      "format_status": 0,
      "check_status": 0,
      "status": 0
    }
  ]
}
```

### Pre-commit Integration

The script integrates with pre-commit hooks. See `.pre-commit-config.yaml` for configuration.

### Testing

Run the test suite to verify functionality:

```bash
scripts/test-lint-script.sh
```

The test suite includes:
- Unit tests for all major functionality
- JSON output validation
- Error handling verification
- Mutation testing to ensure test quality

## Contributing

When modifying `lint-changed-files.sh`:
1. Keep AI tool compatibility in mind
2. Maintain backward compatibility
3. Update tests in `test-lint-script.sh`
4. Test with both text and JSON output formats
5. Ensure error messages are clear and actionable