# Writing Custom Challenges

Buttercup is an automated cyber reasoning system originally developed for DARPA's [AI Cyber Challenge][1]. While it was designed to work seamlessly with existing oss-fuzz projects, you can also configure it to analyze custom projects with some additional setup.

This guide walks you through creating custom challenges for Buttercup, covering everything from the basic input format to debugging common issues.

## Prerequisites

To analyze a custom project, you'll need to provide:

- **Fuzzing harnesses** that serve as entry points for analysis
- **Build configuration** in a forked oss-fuzz repository
- **Project metadata** defining how to compile and run your fuzzers

## Challenge Input Format

Buttercup accepts challenges through a JSON configuration that specifies both the target project and the fuzzing infrastructure. Here's a complete example:

```json
{
    "challenge_repo_url": "https://github.com/tob-challenges/integration-test.git",
    "challenge_repo_head_ref": "challenges/integration-test-delta-01",
    "fuzz_tooling_url": "https://github.com/tob-challenges/oss-fuzz-aixcc",
    "fuzz_tooling_ref": "challenge-state/integration-test-delta-01",
    "fuzz_tooling_project_name": "integration-test",
    "duration": 1800,
}
```

### Field Descriptions

**Project Repository Fields:**
- `challenge_repo_url`: URL to the repository containing your source code
- `challenge_repo_head_ref`: Git branch, tag, or commit to analyze
- `challenge_repo_base_ref`: *(Delta mode only)* The "clean" commit before vulnerabilities were introduced

**Fuzzing Infrastructure Fields:**
- `fuzz_tooling_url`: URL to your forked oss-fuzz repository with build instructions
- `fuzz_tooling_ref`: Git reference in the oss-fuzz fork that can build your project
- `fuzz_tooling_project_name`: Directory name under `projects/` in your oss-fuzz fork

**Analysis Configuration:**
- `duration`: Analysis time limit in seconds (typically 1800-86400)

For additional context, consult the official oss-fuzz documentation on "[Setting Up a new project][2]".

## Writing Fuzzing Harnesses

Fuzzing harnesses are small programs that act as entry points for Buttercup's analysis. They define how to feed random input into your code to discover vulnerabilities.

### Key Principles

- **Coverage is critical**: Buttercup can only find bugs in code paths reached by your harnesses
- **Keep them simple**: Complex harnesses can introduce their own bugs, which will confuse the analysis
- **Optimize for speed**: The faster your harness runs, the more test cases Buttercup can explore and the better it can find vulnerabilities
- **Handle edge cases**: Your harness should gracefully handle empty inputs, malformed data, etc.

### C/C++ Projects (LibFuzzer)

For C/C++ projects, Buttercup looks for harnesses that implement the `LLVMFuzzerTestOneInput` function:

```c
#include <stdint.h>
#include <stddef.h>

int LLVMFuzzerTestOneInput(const uint8_t *data, size_t size) {
    // Your fuzzing logic here
    // Call the functions you want to test with the provided data
    return 0;
}
```

### Java Projects (Jazzer)

For Java projects, Buttercup looks for harnesses that implement the `fuzzerTestOneInput` method:

```java
import com.code_intelligence.jazzer.api.FuzzedDataProvider;

public class MyFuzzer {
    public static void fuzzerTestOneInput(FuzzedDataProvider data) {
        // Your fuzzing logic here
        // Use data.consume*() methods to extract data for testing
    }
}
```

### Best Practices

- Keep harnesses simple and focused on one API or functionality
- Avoid complex setup/teardown that could introduce bugs
- Handle edge cases (empty input, null pointers, etc.) gracefully
- Use appropriate data extraction methods for structured input
- Ensure the harness can handle the full range of possible inputs

See the [libFuzzer Tutorial](https://github.com/google/fuzzing/blob/master/tutorial/libFuzzerTutorial.md) and [Jazzer Documentation](https://github.com/CodeIntelligenceTesting/jazzer) for detailed guidance.

## Setting Up Your OSS-Fuzz Fork

To integrate your project with Buttercup, you'll need to create a fork of the [oss-fuzz](https://github.com/google/oss-fuzz) repository and add build instructions for your specific project.

This setup tells Buttercup how to compile your code and harnesses in a consistent, isolated environment.

### Directory Structure

In your oss-fuzz fork, create a new directory at `projects/your-project-name/` containing these files:

| File | Purpose |
|------|----------|
| `Dockerfile` | Defines the build environment and dependencies |
| `build.sh` | Compiles your project and creates fuzzer binaries |
| `project.yaml` | Metadata about your project *(recommended)* |

### Creating the Dockerfile

The Dockerfile sets up your build environment. Start with the oss-fuzz base image and add your project's dependencies:

```dockerfile
FROM gcr.io/oss-fuzz-base/base-builder

# Install build dependencies
RUN apt-get update && apt-get install -y \
    make autoconf automake libtool pkg-config

# Clone your project
RUN git clone https://github.com/your-org/your-project.git
WORKDIR /src/your-project

# Copy the build script
COPY build.sh $SRC/
```

### Writing the Build Script

The `build.sh` script compiles your project and creates the fuzzer executables. OSS-Fuzz provides environment variables for consistent builds:

```bash
#!/bin/bash -eu

# Build your project's libraries
make clean
make CC="$CC" CXX="$CXX" CFLAGS="$CFLAGS" CXXFLAGS="$CXXFLAGS"

# Compile each fuzzing harness
# $CC, $CXX, $CFLAGS, $CXXFLAGS are provided by oss-fuzz
# $LIB_FUZZING_ENGINE links the fuzzing engine
# $OUT is where fuzzer binaries should be placed

$CC $CFLAGS -I. -c harness.c -o harness.o
$CXX $CXXFLAGS $LIB_FUZZING_ENGINE harness.o \
    -L. -lyourlib -o $OUT/harness_fuzzer

# Include seed corpus and dictionaries if available
if [ -d "seeds" ]; then
    cp seeds/* $OUT/ 2>/dev/null || true
fi
```

### Project Metadata

The `project.yaml` file provides important metadata about your project:

```yaml
homepage: "https://github.com/your-org/your-project"
language: c  # or jvm
primary_contact: "maintainer@example.com"

# Fuzzing configuration
fuzzing_engines:
  - libfuzzer
  
sanitizers:
  - address      # detects memory corruption
  - undefined    # detects undefined behavior
  - memory       # detects uninitialized reads
```

## Submitting Your Challenge

With your project repository and oss-fuzz fork ready, you can now submit your challenge to Buttercup for analysis. There are two ways to do this:

### Option 1: Direct API Call

For one-off submissions or when testing new configurations, use the HTTP API directly:

```bash
curl -X 'POST' 'http://localhost:31323/webhook/trigger_task' \
  -H 'Content-Type: application/json' \
  -d '{
    "challenge_repo_url": "https://github.com/your-org/your-project.git",
    "challenge_repo_head_ref": "main",
    "fuzz_tooling_url": "https://github.com/your-org/oss-fuzz-fork.git",
    "fuzz_tooling_ref": "main",
    "fuzz_tooling_project_name": "your-project",
    "duration": 3600,
    "harnesses_included": true
  }'
```

### Option 2: Web Interface

For a user-friendly approach, run `make web-ui` and open `http://localhost:31323` in your browser. The web interface provides a form where you can enter all the challenge parameters and submit them with a single click.

## Troubleshooting Your Challenge

When a challenge doesn't behave as expected, Buttercup provides several tools to help you diagnose and fix issues. Here's a systematic approach to debugging:

### Step 1: Check System Status

Start by verifying that all Buttercup components are running properly:

```bash
make status
```

### Step 2: Examine Logs

Logs are your primary source of diagnostic information:

```bash
# View recent logs for a specific component
kubectl logs -n crs -l app=<service-name> --tail=100

# Watch logs in real-time to see what's happening
kubectl logs -n crs -l app=scheduler --tail=-1 -f

# Collect comprehensive logs from all components
./deployment/collect-logs.sh
```

### Step 3: Interactive Debugging

When you need to examine the environment directly:

```bash
# Access a running container's shell
kubectl exec -it -n crs <pod-name> -- /bin/bash

# Examine files, run commands, check environment variables
```

### Step 4: Track Workflow Progress

Monitor how your challenge moves through Buttercup's processing pipeline:

```bash
# Watch the scheduler's state transitions
kubectl logs -n crs -l app=scheduler --tail=-1 --prefix | \
  grep "WAIT_PATCH_PASS -> SUBMIT_BUNDLE"

# This helps identify where processing gets stuck
```

### Common Issues and Solutions

| Problem | Symptoms | Solution |
|---------|----------|----------|
| **Build failures** | Fuzzer compilation errors | Verify your `build.sh` works with oss-fuzz base images. Test locally with `docker run gcr.io/oss-fuzz-base/base-builder` |
| **Missing harnesses** | "No harnesses found" errors | Check `harnesses_included` setting and ensure harness files contain the expected function signatures |
| **Timeouts** | Analysis stops prematurely | Increase the `duration` parameter, especially for large codebases |
| **Resource limits** | Pods getting killed (OOMKilled) | Check pod memory/CPU limits and adjust Kubernetes resource constraints |
| **Git access issues** | Clone/fetch failures | Verify repository URLs are accessible and authentication is configured |
| **Path problems** | File not found errors | Ensure WORKDIR in Dockerfile matches your project structure |

## Analysis Modes

Buttercup supports two analysis modes, each optimized for different use cases:

### Full Mode Analysis

Full mode analyzes an entire project:

| Aspect | Details |
|--------|----------|
| **Scope** | Analyzes the complete codebase |
| **Best for** | Initial assessment |
| **Configuration** | Only requires `challenge_repo_head_ref` |

**Example configuration:**

```json
{
    "challenge_repo_url": "https://github.com/example/project.git",
    "challenge_repo_head_ref": "v1.0.0",
    "fuzz_tooling_url": "https://github.com/example/oss-fuzz-fork.git",
    "fuzz_tooling_ref": "main",
    "fuzz_tooling_project_name": "project",
    "duration": 86400
}
```

### Delta Mode Analysis

Delta mode focuses specifically on changes between two commits, making it ideal for targeted analysis:

| Aspect | Details |
|--------|----------|
| **Scope** | Analyzes only the differences between base and head commits |
| **Best for** | Analyzing specific changes |
| **Configuration** | Requires both `challenge_repo_base_ref` and `challenge_repo_head_ref` |

**Example configuration:**

```json
{
    "challenge_repo_url": "https://github.com/example/project.git",
    "challenge_repo_base_ref": "abc123",
    "challenge_repo_head_ref": "def456",
    "fuzz_tooling_url": "https://github.com/example/oss-fuzz-fork.git",
    "fuzz_tooling_ref": "main",
    "fuzz_tooling_project_name": "project",
    "duration": 28800
}
```

### How Mode Detection Works

Buttercup determines which mode to use based on your challenge configuration:

- **Delta mode** is activated when you provide both `challenge_repo_base_ref` and `challenge_repo_head_ref`
- Internally, Buttercup creates diff files and the `is_delta_mode()` method detects their presence
- Before building, delta mode applies patches using `git apply` to introduce the target changes
- This targeted approach makes delta mode more efficient for analyzing specific code changes

### Choosing the Right Mode

**Choose Full Mode when you want to:**
- Perform an initial assessment of a new project
- Search for vulnerabilities in all code reachable from harnesses
- Analyze a project without specific change targets

**Choose Delta Mode when you want to:**
- Test specific code changes
- Reproduce known vulnerabilities

---

## Next Steps

Now that you understand how to create custom challenges, you can:

1. **Start simple**: Create a basic challenge with one harness to test your setup
2. **Test locally**: Verify your oss-fuzz configuration builds correctly before submitting
3. **Monitor progress**: Use the debugging techniques to track your challenge's execution
4. **Iterate**: Refine your harnesses and build scripts based on the results

For additional help, consult the main [Buttercup documentation](README.md) or check the [troubleshooting guide](CLAUDE.md#common-debugging-commands).


[1]: https://aicyberchallenge.com/
[2]: https://google.github.io/oss-fuzz/getting-started/new-project-guide/