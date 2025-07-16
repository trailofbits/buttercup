# Example Challenges Usage Guide

## Crashy Project

The `crashy-project` is a test OSS-Fuzz project that demonstrates how to submit challenges to Buttercup CRS.

### Features
- **Intentional vulnerabilities** for testing fuzzing effectiveness
- **OSS-Fuzz compatible** structure
- **Multiple crash types**: buffer overflow, division by zero, null pointer dereference
- **~50% crash rate** with random fuzzing

### Quick Test

1. **Verify the vulnerabilities work locally**:
   ```bash
   cd example-challenges/crashy-project
   ./test.sh
   ```

2. **Submit to Buttercup CRS**:
   ```bash
   # Start CRS if not running
   ./scripts/local/local-dev.sh --minimal up
   
   # Submit the challenge
   ./scripts/local/submit.sh example-challenges/crashy-project
   ```

3. **Monitor fuzzing progress**:
   ```bash
   # Watch for crashes being found
   docker compose logs -f unified-fuzzer | grep -E "(crash|ERROR)"
   
   # Watch for build completion
   docker compose logs -f unified-fuzzer | grep "crashy"
   
   # Check if patches are being generated
   docker compose logs -f patcher
   ```

### Expected Timeline

1. **0-30 seconds**: Task downloaded and extracted
2. **30-60 seconds**: Fuzzer builds the target
3. **1-2 minutes**: First crashes discovered
4. **2-5 minutes**: Multiple vulnerabilities found
5. **5-10 minutes**: Patcher generates fixes

### Verifying Success

Check that the system found vulnerabilities:
```bash
# Check Redis for crashes
docker compose exec redis redis-cli
> LLEN crashes_queue
> LRANGE crashes_queue 0 10

# Check for patches
> LLEN patches_queue
```

### Delta Analysis Example

To test delta analysis (comparing two versions):

1. **Initialize git repo**:
   ```bash
   cd example-challenges/crashy-project
   git init
   git add .
   git commit -m "Initial vulnerable version"
   ```

2. **Apply fix and commit**:
   ```bash
   cp src/crashy_fixed.c src/crashy.c
   git add src/crashy.c
   git commit -m "Fix buffer overflow"
   ```

3. **Submit delta analysis**:
   ```bash
   ./scripts/local/submit.sh example-challenges/crashy-project --delta HEAD~1 HEAD
   ```

This will analyze the differences between the vulnerable and fixed versions.

### Troubleshooting

**No crashes found**:
- Check unified-fuzzer logs for build errors
- Ensure OSS-Fuzz base images are available
- Verify the fuzzer binary was created

**Submission fails**:
- Check task-server is running: `docker compose ps`
- Verify port 8888 is available for file server
- Check API credentials match .env file

**Fuzzer doesn't start**:
- Check scheduler logs for task processing
- Ensure Redis is healthy
- Verify all services are connected

### Creating Your Own Test Project

Use crashy-project as a template:

1. Copy the structure
2. Replace `src/crashy.c` with your code
3. Update `projects/crashy/build.sh` for your build
4. Modify `projects/crashy/project.yaml` metadata
5. Submit with the same script!

The key requirements:
- `projects/` directory with OSS-Fuzz configuration
- Valid Dockerfile that uses OSS-Fuzz base
- Build script that creates fuzzer binaries in `$OUT`
- Source code to fuzz