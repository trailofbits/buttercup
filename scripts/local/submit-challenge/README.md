# Submit Challenge Tool

A Python tool for submitting local OSS-Fuzz projects to the Buttercup CRS.

## Installation

This tool is designed to be run with `uvx` (no installation needed):

```bash
uvx --from . submit-challenge --help
```

Or use the wrapper script:
```bash
../submit-challenge.sh --help
```

## Development

If you need to modify the tool:

```bash
# Install dependencies
uv sync

# Run in development mode
uv run submit-challenge --help
```

## Dependencies

- `requests` - For HTTP API calls
- Python 3.10+

The tool is packaged with `uv` for easy dependency management and execution.