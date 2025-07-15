# ARM64 Compatibility Notes for Buttercup CRS

This document covers ARM64 compatibility considerations and solutions for running Buttercup CRS on Apple Silicon and other ARM64 platforms.

## Architecture Overview

### Platform Detection

```dockerfile
# Automatic platform detection
FROM --platform=$TARGETPLATFORM python:3.12-slim

# Build arguments for multi-arch support
ARG TARGETPLATFORM
ARG BUILDPLATFORM
ARG TARGETOS
ARG TARGETARCH
```

### Checking Architecture

```bash
# Check Docker's architecture
docker version --format '{{.Server.Arch}}'

# Check container architecture
docker run --rm alpine uname -m

# Check if running under Rosetta
docker run --rm alpine sh -c 'cat /proc/cpuinfo | grep -i "model name"'
```

## Common Compatibility Issues

### 1. Missing ARM64 Images

**Problem**: Some dependencies don't provide ARM64 images.

**Solutions**:
- Use multi-arch base images
- Build from source on ARM64
- Use Rosetta emulation (with performance penalty)

```dockerfile
# Fallback to emulation if needed
FROM --platform=linux/amd64 legacy/image:latest  # Forces x86_64 emulation
```

### 2. Python Package Compatibility

**Problem**: Some Python packages lack ARM64 wheels.

**Solutions**:
```dockerfile
# Install build dependencies for source compilation
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    make \
    python3-dev \
    libffi-dev \
    libssl-dev

# Force source builds when needed
RUN pip install --no-binary :all: problematic-package
```

### 3. Binary Dependencies

**Problem**: Pre-compiled binaries may be x86_64 only.

**Solutions**:
```dockerfile
# Compile from source for ARM64
FROM --platform=$BUILDPLATFORM golang:1.21 AS builder
ARG TARGETARCH
RUN GOARCH=$TARGETARCH go build -o /app/binary ./...

# Or use architecture-specific downloads
RUN case $(uname -m) in \
    x86_64) ARCH=amd64 ;; \
    aarch64) ARCH=arm64 ;; \
    esac && \
    curl -L https://example.com/binary-${ARCH} -o /usr/local/bin/binary
```

## Service-Specific Compatibility

### Orchestrator Service

```dockerfile
# No known ARM64 issues
# Python-based service works well on ARM64
FROM --platform=$TARGETPLATFORM python:3.12-slim-bookworm
```

### Patcher Service

```dockerfile
# Codequery may need compilation for ARM64
FROM --platform=$BUILDPLATFORM ubuntu:24.04 AS cscope-builder
# Build cscope from source for target architecture
```

### Program Model Service

```dockerfile
# Uses Ubuntu base, ensure ARM64 variant
FROM --platform=$TARGETPLATFORM ubuntu:24.04

# May need to compile codequery for ARM64
RUN dpkg --print-architecture && \
    apt-get update && \
    apt-get install -y codequery || \
    (echo "Building codequery from source..." && \
     # Add source build steps here)
```

### Seed Generation Service

```dockerfile
# WebAssembly runtime needs ARM64 version
RUN ARCH=$(dpkg --print-architecture) && \
    if [ "$ARCH" = "arm64" ]; then \
        curl -fsSLO https://github.com/vmware-labs/webassembly-language-runtimes/releases/download/python%2F3.12.0%2B20231211-040d5a6/python-3.12.0-arm64.wasm; \
    else \
        curl -fsSLO https://github.com/vmware-labs/webassembly-language-runtimes/releases/download/python%2F3.12.0%2B20231211-040d5a6/python-3.12.0.wasm; \
    fi
```

## External Dependencies

### 1. UV Package Manager

UV provides ARM64 binaries:
```dockerfile
# UV supports multi-arch
COPY --from=ghcr.io/astral-sh/uv:0.5.20 /uv /uvx /bin/
```

### 2. Docker-in-Docker

```dockerfile
# Docker provides ARM64 packages
RUN curl -fsSL https://get.docker.com | sh
```

### 3. Development Tools

Most standard tools have ARM64 support:
- Git
- curl
- ripgrep
- rsync

## Performance Considerations

### Emulation Overhead

When running x86_64 containers on ARM64:
- 2-4x slower execution
- Higher memory usage
- Increased CPU usage

### Native Performance

ARM64-native containers on Apple Silicon:
- Near-native performance
- Lower power consumption
- Better memory efficiency

## Testing for Compatibility

### Multi-arch Build Test

```bash
# Test build for multiple architectures
docker buildx build --platform linux/amd64,linux/arm64 .

# Test specific architecture
docker buildx build --platform linux/arm64 --load -t test:arm64 .
docker run --rm test:arm64 uname -m
```

### Compatibility Script

```bash
#!/bin/bash
# check-compatibility.sh

echo "Checking ARM64 compatibility..."

# Check Docker architecture
echo "Docker architecture: $(docker version --format '{{.Server.Arch}}')"

# Test each service
for service in orchestrator patcher program-model seed-gen; do
    echo "Testing $service..."
    docker buildx build --platform linux/arm64 -f $service/Dockerfile .
done
```

## Troubleshooting

### Common Error Messages

1. **"exec format error"**
   - Cause: Trying to run x86_64 binary on ARM64
   - Fix: Use ARM64 image or enable Rosetta

2. **"no matching manifest"**
   - Cause: Image doesn't support ARM64
   - Fix: Build from source or use alternative image

3. **"Illegal instruction"**
   - Cause: Binary compiled for different ARM version
   - Fix: Recompile with appropriate flags

### Debug Commands

```bash
# Check image architecture
docker image inspect --format '{{.Architecture}}' image:tag

# List available platforms for an image
docker manifest inspect image:tag

# Force platform
docker run --platform linux/amd64 image:tag
```

## Best Practices

1. **Always specify platform** in FROM statements
2. **Test on both architectures** during development
3. **Use multi-arch base images** when available
4. **Compile from source** when binaries aren't available
5. **Document architecture requirements** in README

## Future Improvements

1. **Add CI/CD for multi-arch builds**
2. **Create architecture-specific optimization flags**
3. **Benchmark performance differences**
4. **Automate compatibility testing**

## Resources

- [Docker Multi-platform Images](https://docs.docker.com/build/building/multi-platform/)
- [Apple Silicon Docker Guide](https://docs.docker.com/desktop/mac/apple-silicon/)
- [BuildKit Cross-compilation](https://docs.docker.com/build/building/multi-platform/)
- [Rosetta 2 for Linux](https://developer.apple.com/documentation/virtualization/running_intel_binaries_in_linux_vms_with_rosetta)