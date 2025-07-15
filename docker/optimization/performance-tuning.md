# Performance Tuning Guide for Buttercup CRS on ARM64

This guide provides performance optimization strategies for running Buttercup CRS on Apple Silicon and other ARM64 platforms.

## Image Optimization

### Base Image Selection

Choose ARM64-optimized base images for better performance:

```dockerfile
# Good - Uses official ARM64-optimized Python image
FROM python:3.12-slim-bookworm

# Better - Uses Alpine for smaller size (when applicable)
FROM python:3.12-alpine3.19

# Best - Uses multi-arch base with platform specification
FROM --platform=$TARGETPLATFORM python:3.12-slim-bookworm
```

### Multi-stage Build Optimization

```dockerfile
# Use specific platform for builder stage
FROM --platform=$BUILDPLATFORM python:3.12-slim-bookworm AS builder

# Use target platform for runtime
FROM --platform=$TARGETPLATFORM python:3.12-slim-bookworm AS runtime
```

## Build Performance

### BuildKit Optimizations

1. **Enable BuildKit**:
   ```bash
   export DOCKER_BUILDKIT=1
   ```

2. **Use cache mounts**:
   ```dockerfile
   RUN --mount=type=cache,target=/root/.cache/pip \
       pip install -r requirements.txt
   ```

3. **Parallel builds**:
   ```dockerfile
   RUN --mount=type=cache,target=/root/.cache/uv \
       --mount=type=bind,source=.,target=/src \
       cd /src && make -j$(nproc) build
   ```

### Layer Caching Strategies

1. **Order Dockerfile commands by change frequency**:
   ```dockerfile
   # Less frequently changed
   RUN apt-get update && apt-get install -y \
       build-essential \
       git \
       curl
   
   # More frequently changed
   COPY requirements.txt .
   RUN pip install -r requirements.txt
   
   # Most frequently changed
   COPY . .
   ```

2. **Combine RUN commands**:
   ```dockerfile
   # Bad - Creates multiple layers
   RUN apt-get update
   RUN apt-get install -y git
   RUN apt-get install -y curl
   
   # Good - Single layer
   RUN apt-get update && apt-get install -y \
       git \
       curl \
       && rm -rf /var/lib/apt/lists/*
   ```

## Runtime Performance

### Container Resource Limits

```yaml
# docker-compose.yml
services:
  orchestrator:
    deploy:
      resources:
        limits:
          cpus: '4'
          memory: 4G
        reservations:
          cpus: '2'
          memory: 2G
```

### Process Management

1. **Use exec form for ENTRYPOINT**:
   ```dockerfile
   # Good - Direct process execution
   ENTRYPOINT ["python", "-m", "app"]
   
   # Bad - Adds shell overhead
   ENTRYPOINT python -m app
   ```

2. **Enable Python optimizations**:
   ```dockerfile
   ENV PYTHONUNBUFFERED=1 \
       PYTHONDONTWRITEBYTECODE=1 \
       PYTHONOPTIMIZE=1
   ```

## Network Performance

### Service Communication

1. **Use internal networks**:
   ```yaml
   networks:
     internal:
       driver: bridge
       internal: true
   ```

2. **Optimize DNS resolution**:
   ```yaml
   services:
     app:
       dns:
         - 8.8.8.8
         - 8.8.4.4
       dns_opt:
         - ndots:0
   ```

## Storage Performance

### Volume Optimization

1. **Use named volumes over bind mounts**:
   ```yaml
   # Better performance
   volumes:
     - app-data:/data
   
   # Slower on macOS
   volumes:
     - ./data:/data
   ```

2. **Optimize bind mount performance**:
   ```yaml
   volumes:
     - type: bind
       source: ./src
       target: /app
       consistency: delegated  # For macOS
   ```

### Build Cache Management

```bash
# Set up persistent BuildKit cache
docker buildx create --name buttercup \
  --driver docker-container \
  --driver-opt env.BUILDKIT_CACHE_MOUNT_MODE=max \
  --driver-opt env.BUILDKIT_INLINE_CACHE=1

# Use external cache
docker buildx build \
  --cache-from type=local,src=/tmp/.buildx-cache \
  --cache-to type=local,dest=/tmp/.buildx-cache \
  .
```

## ARM64-Specific Optimizations

### Compiler Flags

```dockerfile
# Optimize for ARM64 during compilation
ENV CFLAGS="-march=armv8-a+crc+crypto -mtune=cortex-a72"
ENV CXXFLAGS="${CFLAGS}"
```

### Python Package Installation

```dockerfile
# Use pre-compiled wheels when available
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --prefer-binary -r requirements.txt
```

## Monitoring and Profiling

### Performance Metrics

```bash
# Monitor container stats
docker stats --format "table {{.Container}}\t{{.CPUPerc}}\t{{.MemUsage}}"

# Check build performance
docker buildx build --progress=plain --no-cache .
```

### Profiling Tools

```dockerfile
# Add profiling capabilities
RUN pip install py-spy memory-profiler

# Enable profiling
ENV PYTHONPROFILEIMPORTTIME=1
```

## Best Practices Summary

1. **Image Size**:
   - Use slim or Alpine base images
   - Remove unnecessary packages and files
   - Combine RUN commands
   - Use multi-stage builds

2. **Build Speed**:
   - Enable BuildKit
   - Use cache mounts
   - Parallelize builds
   - Order layers by change frequency

3. **Runtime Performance**:
   - Set appropriate resource limits
   - Use exec form for commands
   - Enable compiler optimizations
   - Use named volumes

4. **ARM64 Specific**:
   - Use native ARM64 images
   - Enable Rosetta for x86 compatibility
   - Use platform-specific optimizations
   - Monitor emulation overhead

## Quick Performance Wins

```bash
# 1. Enable all optimizations
export DOCKER_BUILDKIT=1
export BUILDKIT_INLINE_CACHE=1
export COMPOSE_DOCKER_CLI_BUILD=1

# 2. Build with optimal settings
docker buildx build \
  --platform linux/arm64 \
  --cache-from type=registry,ref=myapp:buildcache \
  --cache-to type=registry,ref=myapp:buildcache,mode=max \
  --build-arg BUILDKIT_INLINE_CACHE=1 \
  -t myapp:latest .

# 3. Run with resource limits
docker run -d \
  --memory="2g" \
  --memory-swap="3g" \
  --cpus="2.0" \
  --restart=unless-stopped \
  myapp:latest
```