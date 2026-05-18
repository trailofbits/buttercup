# Docker Compose Development Setup

This directory contains the legacy Docker Compose setup for Buttercup CRS, preserved for developers who need to run specific components for quick testing and development.

## Usage

From the repository root directory:

```bash
# Run all services
cd dev/docker-compose && docker-compose up -d

# Run specific services or profiles
cd dev/docker-compose && docker-compose --profile fuzzer-test up -d
cd dev/docker-compose && docker-compose --profile graphdb up -d

# Stop services
cd dev/docker-compose && docker-compose down
```

### Using prebuilt images (skip local builds)

`compose.prebuilt.yaml` is an overlay that replaces every locally-built
component with its prebuilt image from GHCR, so nothing is built locally:

```bash
cd dev/docker-compose && docker compose -f compose.yaml -f compose.prebuilt.yaml up -d

# Pin a specific image tag (defaults to "main"):
BUTTERCUP_IMAGE_TAG=<branch-or-tag> docker compose -f compose.yaml -f compose.prebuilt.yaml up -d
```

## Configuration

- `env.template` - Template for environment variables (copy to `.env` and customize)
- `env.dev.compose` - Development-specific environment configuration
- `compose.yaml` - Main compose file with all services
- `compose.prebuilt.yaml` - Overlay that pulls prebuilt GHCR images instead of building locally

## Notes

- This setup is **not recommended for production** - use the Kubernetes deployment instead
- Primarily useful for developers who need to run individual components for testing
- The main deployment method is now Kubernetes via `make deploy` from the repository root
- See the main [README](../../README.md) for the recommended setup instructions
