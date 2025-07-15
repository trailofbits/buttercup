# Cloud Dependency Removal Documentation

This document describes all changes made to remove cloud-specific dependencies and configurations from the Buttercup CRS system, enabling it to work completely offline except for LLM API calls.

## Overview

The Buttercup CRS has been modified to remove hard dependencies on cloud services, making it suitable for offline deployment. The system can now run entirely on local infrastructure, with optional cloud service integrations that gracefully degrade when unavailable.

## Changes Made

### 1. Cloud Monitoring Services Made Optional

#### Langfuse Integration
- **File**: `common/src/buttercup/common/llm.py`
- **Changes**: 
  - Added try/except block for Langfuse imports
  - Added `LANGFUSE_AVAILABLE` flag to track module availability
  - Modified `is_langfuse_available()` to check module availability first
  - Updated `get_langfuse_callbacks()` to gracefully handle missing module
  - Returns empty callback list when Langfuse is unavailable

#### OpenTelemetry Export
- **File**: `common/src/buttercup/common/telemetry.py`
- **Changes**:
  - Added try/except block for OpenTelemetry imports
  - Added `OPENTELEMETRY_AVAILABLE` flag
  - Created dummy classes (DummySpan, DummyTracer) for when OpenTelemetry is unavailable
  - Modified `init_telemetry()` to gracefully handle missing module
  - Updated `set_crs_attributes()` and `log_crs_action_ok()` to check availability
  - All telemetry operations become no-ops when OpenTelemetry is not installed

#### SignOz References
- **File**: `competition-server/compose.yaml`
- **Status**: Already commented out, no changes needed
- SignOz deployment files remain in `competition-server/signoz/` but are not used

### 2. Container Registry Dependencies

#### Image References Updated
All hardcoded references to `ghcr.io` and `gcr.io` have been replaced with local image names:

- **Files Updated**:
  - `compose.yaml`: litellm image changed to `litellm:local-v1.57.8`
  - `competition-server/compose.yaml`: scantron image changed to `competition-test-api:local-v1.4-rc1`
  - `fuzzer/dockerfiles/runner_image.Dockerfile`: Base image changed to `base-runner:local-v1.3.0`
  - `fuzzer/dockerfiles/unified_fuzzer.Dockerfile`: Base image changed to `base-runner:local-v1.3.0`
  - `program-model/src/buttercup/program_model/settings.py`: Default changed to `local/oss-fuzz`
  - `program-model/src/buttercup/program_model/program_model.py`: Default changed to `local/oss-fuzz`
  - `fuzzer/src/buttercup/unified_fuzzer/config.py`: Default changed to `local/oss-fuzz`
  - `fuzzer/src/buttercup/unified_fuzzer/workers/coverage_worker.py`: Default changed to `local/oss-fuzz`
  - `fuzzer/src/buttercup/fuzzing_infra/settings.py`: Default changed to `local/oss-fuzz`
  - `fuzzer/src/buttercup/fuzzing_infra/coverage_runner.py`: Default changed to `local/oss-fuzz`
  - `common/src/buttercup/common/challenge_task.py`: Default changed to `local/oss-fuzz`

#### UV Installation Method Changed
All Dockerfiles that previously used `COPY --from=ghcr.io/astral-sh/uv:0.5.20` now install UV locally:
- `orchestrator/Dockerfile`
- `program-model/Dockerfile`
- `seed-gen/Dockerfile`
- `patcher/Dockerfile`
- `fuzzer/dockerfiles/runner_image.Dockerfile`
- `fuzzer/dockerfiles/unified_fuzzer.Dockerfile`

The new installation method downloads UV directly from the official installer script.

#### Local LiteLLM Dockerfile Created
- **File**: `docker/litellm/Dockerfile`
- Creates a local build for LiteLLM instead of pulling from ghcr.io

### 3. Cloud-Specific Environment Variables

#### Environment Templates Updated
- **Files**:
  - `.env.example`
  - `env.template`
  - `deployment/env.template`

- **Changes**:
  - Azure configuration commented out by default
  - Langfuse configuration commented out by default
  - OpenTelemetry configuration commented out by default
  - GHCR authentication commented out by default
  - Added comments indicating these are optional for offline mode
  - Updated `FUZZ_TOOLING_CONTAINER_ORG` default to `local/oss-fuzz`

### 4. Azure/Cloud Configurations

#### LiteLLM Configuration
- **File**: `litellm/litellm_config.yaml`
- **Changes**: All Azure model configurations commented out with note about offline mode

#### Tailscale Removed
- **Files**:
  - `scripts/setup-production.sh`: Reference changed from Tailscale to kubectl
  - `scripts/common.sh`: Tailscale validation code removed

### 5. Service Configurations for Offline Mode

#### Docker BuildKit Configuration
- **File**: `docker/buildkitd.toml`
- **Changes**:
  - Removed `mirror.gcr.io` from Docker Hub mirrors
  - Removed ghcr.io registry configuration
  - Added local registry configuration with HTTP support

## Usage Instructions

### Running in Offline Mode

1. **Environment Setup**:
   ```bash
   cp .env.example .env
   # Add only your LLM API keys (OpenAI/Anthropic)
   # Leave all cloud service configurations commented out
   ```

2. **Build Local Images**:
   ```bash
   # Build all service images locally
   docker compose build
   ```

3. **Start Services**:
   ```bash
   docker compose up -d
   ```

### Enabling Cloud Services (Optional)

To re-enable cloud services, uncomment the relevant sections in your `.env` file:

1. **Langfuse**: Uncomment and set:
   - `LANGFUSE_HOST`
   - `LANGFUSE_PUBLIC_KEY`
   - `LANGFUSE_SECRET_KEY`

2. **OpenTelemetry**: Uncomment and set:
   - `OTEL_EXPORTER_OTLP_ENDPOINT`
   - `OTEL_EXPORTER_OTLP_HEADERS`
   - `OTEL_EXPORTER_OTLP_PROTOCOL`

3. **Azure OpenAI**: Uncomment and set:
   - `AZURE_API_BASE`
   - `AZURE_API_KEY`

4. **Container Registries**: Uncomment and set:
   - `GHCR_AUTH` for GitHub Container Registry
   - `DOCKER_USERNAME` and `DOCKER_PAT` for Docker Hub

### Local Image Naming Convention

All images now follow the pattern:
- `<service-name>:local-<version>`
- Base images: `local/oss-fuzz`

Examples:
- `litellm:local-v1.57.8`
- `competition-test-api:local-v1.4-rc1`
- `base-runner:local-v1.3.0`

## Testing

The system has been designed to gracefully handle missing cloud services:

1. **Telemetry**: When OpenTelemetry is not available, all telemetry operations become no-ops
2. **LLM Monitoring**: When Langfuse is not available, LLM calls proceed without monitoring
3. **Container Images**: All images can be built locally without registry access

## Migration Guide

If migrating from a cloud-connected deployment:

1. Update all image references in your deployment files
2. Build images locally or set up a local registry
3. Update environment variables to remove/comment out cloud services
4. Test that all services start successfully without cloud connectivity

## Future Considerations

1. Consider setting up a local container registry for team deployments
2. Implement local alternatives for telemetry/monitoring if needed
3. Cache LLM responses locally for true offline operation (currently LLM APIs still require internet)