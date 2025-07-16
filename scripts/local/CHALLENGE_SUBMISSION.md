# Challenge Submission Guide

## Overview

The `submit-challenge.py` script allows you to submit local OSS-Fuzz projects to the Buttercup CRS for vulnerability discovery and fuzzing. It supports both full analysis and delta analysis (comparing two git commits).

## Prerequisites

1. Buttercup CRS services must be running:
   ```bash
   ./scripts/local/local-dev.sh --minimal up
   ```

2. Your challenge must follow OSS-Fuzz structure:
   ```
   your-project/
   ├── projects/
   │   └── your-project-name/
   │       ├── Dockerfile
   │       ├── build.sh
   │       └── project.yaml
   ├── src/           # Or your source code location
   │   └── ...
   └── ...
   ```

## Usage

The submission script uses `uv` for dependency management and execution. You can use it in two ways:

### Using the wrapper script (recommended)

```bash
# Full analysis
./scripts/local/submit.sh /path/to/oss-fuzz-project

# Delta analysis
./scripts/local/submit.sh /path/to/oss-fuzz-project --delta abc123 def456
```

### Using uvx directly

```bash
# Full analysis
./scripts/local/submit-challenge.sh /path/to/oss-fuzz-project

# Delta analysis  
./scripts/local/submit-challenge.sh /path/to/oss-fuzz-project \
    --commit1 abc123 \
    --commit2 def456
```

### Options

- `--deadline HOURS`: Set task deadline (default: 24 hours)
- `--port PORT`: File server port (default: 8888)
- `--debug`: Enable debug logging

## How It Works

1. **Dependencies**: Uses `uv` to automatically manage Python dependencies (requests)
2. **Validation**: Checks that your project has the required OSS-Fuzz structure
3. **Packaging**: Creates separate tarballs for:
   - Source code (excluding OSS-Fuzz tooling)
   - Fuzz tooling (projects directory)
   - Git diff (for delta analysis)
4. **File Server**: Starts a local HTTP server to serve the tarballs
5. **Submission**: Sends task to CRS API with download URLs
6. **Monitoring**: Provides commands to monitor progress

The script uses `uv run` to execute with inline dependencies, so no manual installation is needed.

## Expected Project Structure

### Minimal OSS-Fuzz Project
```
my-fuzzer/
├── projects/
│   └── myproject/
│       ├── Dockerfile
│       ├── build.sh
│       └── project.yaml
└── src/
    ├── main.c
    └── lib.c
```

### Example Dockerfile
```dockerfile
FROM gcr.io/oss-fuzz-base/base-builder
RUN apt-get update && apt-get install -y make
COPY . $SRC/myproject
WORKDIR $SRC/myproject
COPY ./*.sh $SRC/
```

### Example build.sh
```bash
#!/bin/bash -eu
# Build project
make -C $SRC/myproject

# Build fuzzers
$CXX $CXXFLAGS -std=c++11 -I$SRC/myproject \
    $SRC/myproject/fuzzer.cc \
    -o $OUT/fuzzer \
    $LIB_FUZZING_ENGINE
```

## Monitoring Progress

After submission, monitor the task progress:

```bash
# Watch scheduler for task processing
docker compose logs -f scheduler

# Watch fuzzer for build and fuzzing
docker compose logs -f unified-fuzzer

# Watch patcher for vulnerability patching
docker compose logs -f patcher

# Check Redis queues
docker compose exec redis redis-cli
> LLEN fuzzer_build_queue
> LLEN patches_queue
```

## Troubleshooting

### Tasks Not Being Processed
If your tasks are submitted but not processed:
- **Check task-server logs**: Look for "Skipping Unharnessed Task"
- **Solution**: The CRS expects `harnesses_included=True` for OSS-Fuzz projects
- The submission script has been updated to set this correctly

### Authentication Failed
Ensure the API credentials in the script match your `.env` file:
- API Key ID: `515cc8a0-3019-4c9f-8c1c-72d0b54ae561`
- API Token: `VGuAC8axfOnFXKBB7irpNDOKcDjOlnyB`

### File Server Issues
- Check that port 8888 is not in use
- Use `--port` to specify a different port
- **Docker Networking**: The script uses `host.docker.internal` for containers to reach the host
- If running on Linux, you may need to use `--add-host host.docker.internal:host-gateway` in Docker

### Missing OSS-Fuzz Structure
The script expects:
- `projects/` directory with at least one project
- Project subdirectory with Dockerfile

### Git Diff Errors
For delta analysis:
- Ensure the directory is a git repository
- Commits must exist in the repository
- Working directory should be clean

## Example: Submitting a Test Project

1. Create a minimal test project:
```bash
mkdir -p test-fuzzer/projects/testproject
mkdir -p test-fuzzer/src

# Create Dockerfile
cat > test-fuzzer/projects/testproject/Dockerfile << 'EOF'
FROM gcr.io/oss-fuzz-base/base-builder
COPY . $SRC/testproject
EOF

# Create source
echo "int main() { return 0; }" > test-fuzzer/src/main.c
```

2. Submit for analysis:
```bash
./scripts/local/submit-challenge.py test-fuzzer
```

3. Monitor progress:
```bash
docker compose logs -f scheduler | grep test
```