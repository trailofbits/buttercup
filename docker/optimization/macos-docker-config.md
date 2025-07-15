# macOS Docker Desktop Configuration Guide

This guide provides optimal Docker Desktop configuration for running Buttercup CRS on Apple Silicon Macs.

## Docker Desktop Settings

### Resources

Configure Docker Desktop resources for optimal performance on Apple Silicon:

1. **Open Docker Desktop** → **Preferences** → **Resources**

2. **CPU Limit**: 
   - Recommended: 6-8 CPUs (for M1/M2 Pro)
   - Recommended: 8-12 CPUs (for M1/M2 Max/Ultra)
   - Leave at least 2 CPUs for the host system

3. **Memory Limit**:
   - Recommended: 8-16 GB
   - Minimum: 6 GB for running the full CRS stack
   - Leave at least 8 GB for the host system

4. **Swap**:
   - Recommended: 2-4 GB
   - Helps with memory-intensive operations

5. **Disk Size**:
   - Recommended: 60-100 GB
   - Required for building and storing container images

### Advanced Settings

1. **Enable VirtioFS**:
   - Go to **Preferences** → **General**
   - Enable "Use Virtualization framework"
   - Go to **Preferences** → **Resources** → **File Sharing**
   - Select "VirtioFS" for better file system performance

2. **Enable Rosetta for x86/amd64 emulation**:
   - Go to **Preferences** → **General**
   - Enable "Use Rosetta for x86/amd64 emulation on Apple Silicon"
   - This improves performance for x86 containers

### Docker Engine Configuration

Add the following to Docker Desktop's daemon configuration:

```json
{
  "builder": {
    "gc": {
      "enabled": true,
      "defaultKeepStorage": "20GB"
    }
  },
  "features": {
    "buildkit": true
  },
  "experimental": true,
  "default-runtime": "runc",
  "max-concurrent-downloads": 10,
  "max-concurrent-uploads": 5,
  "storage-driver": "overlay2"
}
```

## Performance Optimization

### Build Cache Management

```bash
# Clear build cache when needed
docker builder prune -a

# Use BuildKit inline cache
export DOCKER_BUILDKIT=1
export BUILDKIT_INLINE_CACHE=1
```

### Multi-platform Build Setup

```bash
# Create a new builder instance for multi-platform builds
docker buildx create --name buttercup-builder --use
docker buildx inspect --bootstrap

# Build for both ARM64 and AMD64
docker buildx build --platform linux/arm64,linux/amd64 -t buttercup/service:latest .
```

### Container Runtime Optimization

1. **Use native ARM64 images** whenever possible
2. **Limit container resources** to prevent resource exhaustion:
   ```yaml
   services:
     service-name:
       deploy:
         resources:
           limits:
             cpus: '2'
             memory: 2G
   ```

3. **Enable BuildKit** for faster builds:
   ```bash
   export DOCKER_BUILDKIT=1
   ```

## Troubleshooting

### Common Issues on macOS

1. **Slow file system operations**:
   - Ensure VirtioFS is enabled
   - Avoid mounting large directories
   - Use `.dockerignore` to exclude unnecessary files

2. **High memory usage**:
   - Monitor with `docker stats`
   - Adjust memory limits in Docker Desktop
   - Use `--memory` flag when running containers

3. **Build failures**:
   - Check available disk space
   - Clear Docker cache: `docker system prune -a`
   - Restart Docker Desktop if builds hang

### Performance Monitoring

```bash
# Monitor resource usage
docker stats

# Check system events
docker system events

# Inspect builder cache
docker buildx du
```

## Best Practices for macOS

1. **Regular maintenance**:
   - Clean unused images weekly: `docker image prune -a`
   - Remove stopped containers: `docker container prune`
   - Clear build cache monthly: `docker builder prune`

2. **Development workflow**:
   - Use bind mounts sparingly
   - Prefer named volumes for better performance
   - Use `.dockerignore` to exclude node_modules, .git, etc.

3. **Resource management**:
   - Set appropriate resource limits
   - Monitor resource usage regularly
   - Restart Docker Desktop if performance degrades

## Quick Start Commands

```bash
# Verify Docker is using the correct architecture
docker version

# Check if running on Apple Silicon
docker run --rm alpine uname -m

# Build with BuildKit for better performance
DOCKER_BUILDKIT=1 docker build -t myapp .

# Use buildx for multi-platform builds
docker buildx build --platform linux/arm64 -t myapp:arm64 .
```