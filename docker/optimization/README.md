# Docker Optimization for ARM64/macOS

This directory contains optimization guides and configurations for running Buttercup CRS efficiently on Apple Silicon Macs and other ARM64 platforms.

## Quick Start

1. **Configure Docker Desktop** - Follow [macos-docker-config.md](./macos-docker-config.md)
2. **Build ARM64 images** - Use the optimized build script:
   ```bash
   cd ../..
   ./docker/build-arm64.sh
   ```
3. **Run with optimized compose** - Use the ARM64-specific compose file:
   ```bash
   docker-compose -f docker/docker-compose.arm64.yml up
   ```

## Documentation

### Configuration Guides
- **[macOS Docker Configuration](./macos-docker-config.md)** - Optimal Docker Desktop settings for Apple Silicon
- **[Performance Tuning](./performance-tuning.md)** - Comprehensive performance optimization strategies
- **[ARM64 Compatibility](./arm64-compatibility.md)** - Compatibility notes and troubleshooting

### Key Optimizations Applied

1. **Multi-platform Support**
   - All Dockerfiles now support `--platform` flag
   - Build and runtime stages use appropriate platforms
   - Architecture detection for conditional builds

2. **Build Performance**
   - BuildKit cache mounts for package managers
   - Parallel compilation with `make -j$(nproc)`
   - Optimized layer ordering
   - Build platform separation for faster builds

3. **Runtime Performance**
   - Python optimization flags enabled
   - Lightweight base images where possible
   - Resource limits to prevent exhaustion
   - Cache volumes for persistent data

4. **macOS-Specific**
   - VirtioFS recommendations
   - Rosetta 2 configuration
   - Docker Desktop resource tuning
   - Network MTU optimization

## Build Script Usage

The `build-arm64.sh` script provides optimized builds for ARM64:

```bash
# Basic usage
./docker/build-arm64.sh

# Custom registry and tag
REGISTRY=myregistry.com TAG=v1.0 ./docker/build-arm64.sh

# With architecture tests
RUN_TESTS=true ./docker/build-arm64.sh

# Specific platform
PLATFORM=linux/arm64 ./docker/build-arm64.sh
```

## Docker Compose Usage

The ARM64-optimized compose file includes:
- Platform specifications
- Resource limits
- Health checks
- Optimized networking

```bash
# Start all services
docker-compose -f docker/docker-compose.arm64.yml up -d

# View logs
docker-compose -f docker/docker-compose.arm64.yml logs -f

# Scale specific service
docker-compose -f docker/docker-compose.arm64.yml up -d --scale patcher=3
```

## Troubleshooting

### Common Issues

1. **"exec format error"**
   ```bash
   # Check image architecture
   docker inspect image:tag | grep Architecture
   
   # Force platform if needed
   docker run --platform linux/amd64 image:tag
   ```

2. **Slow builds on macOS**
   - Enable BuildKit: `export DOCKER_BUILDKIT=1`
   - Use VirtioFS in Docker Desktop
   - Increase Docker Desktop resources

3. **Out of memory**
   - Adjust limits in docker-compose.arm64.yml
   - Increase Docker Desktop memory allocation
   - Monitor with `docker stats`

### Performance Monitoring

```bash
# Monitor resource usage
docker stats

# Check build cache
docker buildx du

# Inspect builder
docker buildx inspect buttercup-arm64
```

## Best Practices

1. **Always use native ARM64 images** when available
2. **Enable BuildKit** for all builds
3. **Use cache mounts** for package managers
4. **Set resource limits** to prevent exhaustion
5. **Regular cleanup** of unused images and volumes

## Future Improvements

- [ ] Add GitHub Actions for multi-arch builds
- [ ] Create slim Alpine-based variants
- [ ] Implement distroless runtime images
- [ ] Add build benchmarking
- [ ] Create architecture test suite

## Contributing

When updating Dockerfiles:
1. Maintain multi-platform support
2. Test on both ARM64 and x86_64
3. Document any architecture-specific code
4. Update this README with changes