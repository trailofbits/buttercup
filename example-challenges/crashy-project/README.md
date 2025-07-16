# Crashy - OSS-Fuzz Test Project

This is a test project for the Buttercup CRS that intentionally contains vulnerabilities:

## Vulnerabilities

1. **Buffer Overflow**: Triggered when input contains "CRASH"
2. **Division by Zero**: Triggered when input starts with "DIV0"
3. **Null Pointer Dereference**: Triggered when input starts with "NULLPTR"

## Structure

```
crashy-project/
├── src/
│   ├── crashy.c           # Main vulnerable program
│   ├── crashy_fuzzer.cc   # LibFuzzer harness
│   └── Makefile           # Build configuration
├── projects/
│   └── crashy/
│       ├── Dockerfile     # OSS-Fuzz container definition
│       ├── build.sh       # OSS-Fuzz build script
│       └── project.yaml   # Project metadata
└── README.md
```

## Testing

### Manual Testing
```bash
cd src
make
echo "CRASH" > test.txt
./crashy test.txt  # Should crash
```

### Submit to Buttercup CRS
```bash
# Make sure CRS is running
./scripts/local/local-dev.sh --minimal up

# Submit the project
./scripts/local/submit.sh example-challenges/crashy-project
```

## Expected Behavior

When fuzzed, this project should:
- Find crashes within seconds
- Generate ~50% crash rate with random inputs
- Trigger all three vulnerability types
- Allow the patcher to generate fixes

## Monitoring

After submission, monitor with:
```bash
docker compose logs -f unified-fuzzer | grep crashy
docker compose logs -f scheduler | grep crashy
```