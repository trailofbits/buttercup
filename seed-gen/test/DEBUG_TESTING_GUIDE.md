# Debug Subagent Testing Guide

This guide explains how to write robust tests for the debug subagent that don't rely on LLM tokens but still test real Docker execution.

## Testing Strategy

### 1. Mock LLM, Test Real Docker

The key insight is to **mock the LLM responses** (to avoid token costs) but **use real Docker execution** (to catch actual bugs).

```python
# Mock LLM to return canned responses
def mock_llm_invoke(prompt_vars):
    if "analysis" in str(prompt_vars):
        return AIMessage(content="Test analysis")
    elif "debug_script" in str(prompt_vars):
        return AIMessage(content="```gdb\n# Test script\nquit\n```")
    return AIMessage(content="No match")

mock_task.llm.invoke = Mock(side_effect=mock_llm_invoke)
```

### 2. Test at Different Levels

#### Level 1: Direct Docker Testing
Test Docker mounting and execution directly, bypassing the subagent:

```python
def test_docker_mount_verification():
    # Create test file
    test_file.write_text("hello")
    
    # Mount and execute
    result = task.exec_docker_cmd(
        ["cat", "/tmp/test.txt"],
        mount_dirs={test_file: Path("/tmp/test.txt")},
    )
    assert result.success
```

#### Level 2: Method-Level Testing
Test `_execute_debug_script` directly:

```python
def test_execute_debug_script():
    script_path = create_gdb_script()
    pov_input = create_test_input()
    
    output = debug_subagent._execute_debug_script(script_path, pov_input)
    assert len(output) > 0
```

#### Level 3: Full Workflow Testing
Test the full `debug()` method with mocked LLM:

```python
def test_full_workflow():
    # Mock LLM responses
    mock_llm_responses()
    
    # Run full workflow
    result = debug_subagent.debug(...)
    assert result.debug_output
```

## Common Issues and Solutions

### Issue 1: "File not found" in Container

**Symptoms:**
- Docker command succeeds but can't find mounted file
- Error: "No such file or directory"

**Causes:**
1. File path not absolute
2. File doesn't exist when Docker tries to mount
3. File deleted before Docker finishes

**Solutions:**
```python
# Always resolve paths
script_path = script_path.resolve()

# Verify file exists before mounting
assert script_path.exists()
assert script_path.is_file()

# Don't delete temp files until after Docker completes
# (The code already handles this with delete=False)
```

### Issue 2: "Is a directory" Error

**Symptoms:**
- GDB complains about script path being a directory
- Error: "Is a directory" when trying to read script

**Causes:**
- Mounting a directory instead of a file
- Incorrect container path

**Solutions:**
```python
# Mount file directly, not parent directory
mount_dirs = {
    script_path: Path("/tmp/debug_script.gdb"),  # File → File
    # NOT: script_path.parent: Path("/tmp")  # This mounts directory
}
```

### Issue 3: Binary Not Found

**Symptoms:**
- GDB can't find the binary
- Error: "No such file or directory" for binary path

**Causes:**
1. Build directory not mounted correctly
2. Binary path doesn't match mount structure
3. Binary doesn't have execute permissions

**Solutions:**
```python
# Verify binary exists
harness_binary = build_dir / harness_name
assert harness_binary.exists()

# Set execute permissions
harness_binary.chmod(0o755)

# Mount build directory correctly
mount_dirs[build_dir] = Path("/out")
# Binary should be at /out/{harness_name}
```

### Issue 4: GDB Script Not Executing

**Symptoms:**
- GDB runs but script doesn't execute
- No output from script commands

**Causes:**
1. Script syntax errors
2. Script path incorrect
3. GDB batch mode issues

**Solutions:**
```python
# Use proper GDB script format
gdb_script = """# GDB script
set confirm off
set pagination off
echo \\n=== Script Start ===\\n
# Your commands here
quit
"""

# Verify script is readable
assert script_path.stat().st_size > 0

# Use -batch and -x flags correctly
gdb_cmd = [
    "gdb",
    "-batch",  # Non-interactive
    "-x", script_path_in_container,  # Execute script
    "--args", binary_path, input_path,
]
```

## Debugging Workflow

### Step 1: Run Diagnostic Script

```bash
python seed-gen/test/debug_docker_execution.py
```

This will test:
- Docker availability
- File mounting
- GDB execution
- Path resolution

### Step 2: Test Individual Components

```python
# Test 1: Can we mount files?
test_docker_mount_verification()

# Test 2: Can we run GDB?
test_gdb_script_execution_direct()

# Test 3: Does _execute_debug_script work?
test_debug_subagent_execute_script()
```

### Step 3: Add Logging

Enable detailed logging to see what's happening:

```python
import logging
logging.basicConfig(level=logging.DEBUG)

# The debug_subagent already logs extensively:
# - Path resolution
# - File existence checks
# - Mount directories
# - GDB output
```

### Step 4: Inspect Docker Command

The code logs the Docker command being executed. Check:
1. Are all paths absolute?
2. Are all files mounted correctly?
3. Is the container image correct?

## Best Practices

### 1. Use Real Docker in Integration Tests

```python
@pytest.mark.integration
def test_with_real_docker():
    # Use real exec_docker_cmd, not mocked
    result = task.exec_docker_cmd(...)
    assert result.success
```

### 2. Mock LLM, Not Docker

```python
# ✅ Good: Mock LLM
mock_task.llm.invoke = Mock(return_value=AIMessage(...))

# ❌ Bad: Mock Docker (unless unit testing)
mock_task.exec_docker_cmd = Mock(...)
```

### 3. Clean Up Temp Files

```python
# Create with delete=False
with tempfile.NamedTemporaryFile(delete=False) as f:
    script_path = Path(f.name)

try:
    # Use script_path
    ...
finally:
    # Clean up after Docker completes
    if script_path.exists():
        script_path.unlink()
```

### 4. Verify File Existence

```python
# Always verify before mounting
assert script_path.exists()
assert script_path.is_file()
assert script_path.stat().st_size > 0
```

### 5. Use Simple Test Scripts

Start with minimal GDB scripts:

```python
simple_script = """# Minimal test
set confirm off
echo Test\\n
quit
"""
```

## Running Tests

### Run Integration Tests

```bash
# Run all integration tests
pytest seed-gen/test/test_debug_subagent_integration.py -v -s

# Run specific test
pytest seed-gen/test/test_debug_subagent_integration.py::test_gdb_script_execution_direct -v -s
```

### Run Diagnostic Script

```bash
python seed-gen/test/debug_docker_execution.py
```

### Run with Logging

```bash
# Enable debug logging
PYTHONPATH=. python -m pytest seed-gen/test/test_debug_subagent_integration.py -v -s --log-cli-level=DEBUG
```

## Example Test Structure

```python
@pytest.mark.integration
def test_debug_subagent_full_workflow():
    """Test full workflow with mocked LLM but real Docker."""
    
    # 1. Set up fixtures
    debug_subagent = DebugSubagent(mock_task, reproduce_multiple)
    
    # 2. Create test data
    pov_input = create_test_input()
    
    # 3. Mock LLM responses
    mock_llm_responses()
    
    # 4. Run debug
    result = debug_subagent.debug(
        harness=harness_info,
        pov_input_path=pov_input,
        debug_context="Test",
    )
    
    # 5. Verify results
    assert result.debug_output
    assert len(result.debug_output) > 0
```

## Troubleshooting Checklist

- [ ] Docker is running: `docker ps`
- [ ] Debug image available: `docker pull gcr.io/oss-fuzz-base/base-runner-debug`
- [ ] Files exist before mounting: `assert path.exists()`
- [ ] Paths are absolute: `path.resolve()`
- [ ] Binary has execute permissions: `chmod 0o755`
- [ ] GDB script syntax is correct
- [ ] Mount paths match container paths
- [ ] Temp files not deleted too early

## Next Steps

1. Run `debug_docker_execution.py` to diagnose issues
2. Write minimal test using `test_debug_subagent_integration.py` as template
3. Add logging to see what's happening
4. Gradually increase test complexity

