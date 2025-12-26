# Testing the Debug Subagent

This guide covers different ways to test the `DebugSubagent` utility.

## 1. Unit Tests (Recommended First Step)

Run the pytest unit tests:

```bash
cd seed-gen
uv run pytest test/test_debug_subagent.py -v
```

The tests mock all dependencies and verify:
- Basic workflow execution
- GDB script generation and execution
- PoV validation
- Error handling

## 2. Manual Testing with a Real Task

### Prerequisites

1. A challenge task directory with:
   - Built fuzzers (in `build/out/<project_name>/`)
   - A PoV input file to test
   - OSS-Fuzz infrastructure set up

2. Environment variables:
   ```bash
   export BUTTERCUP_LITELLM_HOSTNAME=http://localhost:8080
   export BUTTERCUP_LITELLM_KEY=sk-...
   export LANGFUSE_HOST=http://localhost:3000  # Optional
   export LANGFUSE_PUBLIC_KEY=...  # Optional
   export LANGFUSE_SECRET_KEY=...  # Optional
   ```

### Option A: Using Python Script

Create a test script `test_debug_manual.py`:

```python
#!/usr/bin/env python3
"""Manual test script for DebugSubagent"""

import sys
from pathlib import Path

# Add seed-gen to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from buttercup.common.challenge_task import ChallengeTask
from buttercup.common.datastructures.msg_pb2 import BuildOutput
from buttercup.common.project_yaml import ProjectYaml
from buttercup.common.reproduce_multiple import ReproduceMultiple
from buttercup.program_model.codequery import CodeQueryPersistent
from buttercup.seed_gen.debug_subagent import DebugSubagent
from buttercup.seed_gen.seed_init import SeedInitTask
from buttercup.seed_gen.find_harness import get_harness_source

def main():
    # Configuration
    task_dir = Path("/path/to/challenge/task")
    package_name = "your_package"
    harness_name = "your_harness"
    pov_input_path = Path("/path/to/pov_input.bin")
    debug_context = "This POV is designed to exploit the buffer overflow on line 197 of parser.py, figure out why it is failing to cause a crash."
    
    # Initialize challenge task
    challenge_task = ChallengeTask(read_only_task_dir=task_dir)
    
    # Get writable copy
    with challenge_task.get_rw_copy(work_dir="/tmp/debug-test") as rw_task:
        # Initialize dependencies
        codequery = CodeQueryPersistent(rw_task, work_dir=Path("/tmp"))
        project_yaml = ProjectYaml(rw_task, package_name)
        
        # Create a Task instance (needed for DebugSubagent)
        task = SeedInitTask(
            package_name=package_name,
            harness_name=harness_name,
            challenge_task=rw_task,
            codequery=codequery,
            project_yaml=project_yaml,
            redis=None,
        )
        
        # Get harness
        harness = get_harness_source(None, codequery, harness_name)
        if harness is None:
            print(f"Error: No harness found for {harness_name}")
            return
        
        # Create build output
        build_output = BuildOutput()
        build_output.task_dir = str(rw_task.task_dir)
        build_output.build_type = "fuzzer"
        build_output.engine = "libfuzzer"
        build_output.sanitizer = "address"
        build_output.apply_diff = False
        
        # Create ReproduceMultiple
        reproduce_multiple = ReproduceMultiple(Path("/tmp/debug-test"), [build_output])
        
        # Create debug subagent
        debug_agent = DebugSubagent(task, reproduce_multiple)
        
        # Run debug
        print(f"Starting debug session for {harness_name}...")
        print(f"PoV input: {pov_input_path}")
        print(f"Debug context: {debug_context}")
        print()
        
        result = debug_agent.debug(
            harness=harness,
            pov_input_path=pov_input_path,
            debug_context=debug_context,
            output_dir=Path("/tmp/debug-output"),
        )
        
        # Print results
        print("=" * 60)
        print("DEBUG RESULTS")
        print("=" * 60)
        print(f"PoV Valid: {result.pov_valid}")
        print(f"Debug Attempts: {len(result.attempts)}")
        print()
        print("Analysis:")
        print(result.analysis)
        print()
        print("Debug Script:")
        print(result.debug_script)
        print()
        print("Debug Output:")
        print(result.debug_output)
        print()
        print(f"Output files written to: /tmp/debug-output")

if __name__ == "__main__":
    main()
```

Run it:
```bash
cd seed-gen
uv run python test_debug_manual.py
```

### Option B: Integration with VulnDiscovery

You can also test it by integrating it into `vuln_discovery` and calling it when a PoV fails:

```python
# In vuln_base_task.py or a new method
from buttercup.seed_gen.debug_subagent import DebugSubagent

# After testing a PoV that doesn't crash:
if not result.did_crash() and state.pov_iteration > 0:
    debug_agent = DebugSubagent(self, self.reproduce_multiple)
    debug_result = debug_agent.debug(
        harness=state.harness,
        pov_input_path=final_path,
        debug_context=f"Previous analysis: {state.analysis}\nWhy did this PoV fail to crash?",
    )
    # Use debug_result to inform next iteration
```

## 3. Testing Specific Scenarios

### Test Case 1: Simple Function Call Check

```python
debug_context = "Check if the function parse_input is called when processing this input"
```

### Test Case 2: Variable Value Inspection

```python
debug_context = "What is the value of buffer_size on line 203 of parser.c when processing this input?"
```

### Test Case 3: Memory State Check

```python
debug_context = "This POV is designed to exploit the buffer overflow on line 197 of parser.py, figure out why it is failing to cause a crash. Check the buffer size and the input length."
```

### Test Case 4: Conditional Branch Verification

```python
debug_context = "Verify that the code takes the vulnerable path (the if statement on line 150 evaluates to true)"
```

## 4. Debugging the Debug Subagent

If something goes wrong:

1. **Check GDB execution**: Look at the `debug_output.txt` file to see GDB's output
2. **Check LLM responses**: If using LangFuse, check the traces for the debug-subagent tag
3. **Check container execution**: Verify that the debug container image is available:
   ```bash
   docker pull gcr.io/oss-fuzz-base/base-runner-debug
   ```
4. **Check file paths**: Ensure the PoV input file exists and is readable
5. **Check build directory**: Verify that the build directory contains the fuzzer binary

## 5. Expected Output Files

When `output_dir` is provided, the debug subagent creates:

- `debug_script.gdb` - The generated GDB script
- `debug_output.txt` - Output from running GDB
- `analysis.txt` - LLM's analysis of the debugging task
- `pov_valid.txt` - Whether the PoV is valid (True/False)
- `debug_attempts.txt` - All debug attempts with their results

## 6. Common Issues

### Issue: "Build cache not available"
- **Solution**: Ensure `ReproduceMultiple.open()` context manager is used correctly

### Issue: "GDB execution failed"
- **Solution**: Check that:
  - Debug container image is available
  - Build directory is mounted correctly
  - PoV input file is accessible
  - Binary exists at `/out/<harness_name>`

### Issue: "No harness found"
- **Solution**: Verify the harness name matches the actual harness in the project

### Issue: LLM generates invalid GDB script
- **Solution**: Check the prompts in `prompt/debug.py` and adjust if needed
