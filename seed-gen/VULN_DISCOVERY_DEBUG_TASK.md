# VulnDiscoveryDebugTask

## Overview

`VulnDiscoveryDebugTask` is a vulnerability discovery task that integrates GDB-based debugging into the workflow. When PoVs fail to crash, it uses `DebugSubagent` to understand why and incorporates those insights into the next iteration.

## Key Features

### 🔍 **Integrated Debugging**
- Automatically debugs failed PoVs after the first iteration
- Uses GDB to inspect execution flow, variable values, and program state
- Captures debug insights and feeds them back into the analysis

### 🔄 **Iterative Improvement**
- First iteration: Generate PoVs based on vulnerability analysis
- Second+ iterations: Incorporate GDB debugging insights
- LLM learns from actual runtime behavior, not just static analysis

### 🎯 **Unified Task**
- Works for both **delta mode** (with diffs) and **full mode** (without diffs)
- Single task that adapts to the challenge type
- No need for separate Delta/Full implementations

## How It Works

### Workflow

```
1. gather_context → tools (context retrieval loop)
                     ↓
2. analyze_bug (with debug insights from previous iteration)
                     ↓
3. write_pov (adjusted based on debug findings)
                     ↓
4. execute_python_funcs (sandbox execution)
                     ↓
5. test_povs (reproduce crashes)
                     ↓
6. Decision:
   - If valid PoVs found → END
   - If max iterations reached → END
   - If iteration <= 1 → retry (back to analyze_bug)
   - Otherwise → debug_povs
                     ↓
7. debug_povs (use GDB to understand why PoV failed)
                     ↓
8. Back to analyze_bug (with new debug insights)
```

### Debug Integration Points

#### 1. **Analysis Phase** (`_analyze_bug`)
```python
# System prompt is augmented with debug insights:
"""
## DEBUG INSIGHTS FROM PREVIOUS ITERATION

When analyzing the vulnerability, consider these insights from GDB debugging:

{debug_insights}

Use these to:
1. Understand why previous PoVs didn't crash
2. Identify what conditions are needed for exploitation
3. Adjust your analysis to account for actual runtime behavior
"""
```

#### 2. **PoV Writing Phase** (`_write_pov`)
```python
# System prompt includes debugging findings:
"""
## DEBUG INSIGHTS

Previous PoVs were debugged with GDB. Here's what we learned:

{debug_insights}

When writing new PoVs:
1. Address the issues identified in debugging
2. Ensure the conditions needed for exploitation are met
3. Adjust input generation based on actual runtime behavior
"""
```

#### 3. **Debug Phase** (`_debug_failed_povs`)
```python
# Creates a detailed debug context:
"""
This PoV was generated based on the following analysis:
{state.analysis}

The PoV is expected to exploit the vulnerability, but it did not cause a crash.
Please investigate:
1. Is the vulnerable code path being executed?
2. Are the necessary conditions for exploitation being met?
3. What is the actual state of the program when processing this input?
4. Why didn't the expected crash occur?
"""
```

## Usage

### As a Task in seed_gen_bot

```python
from buttercup.seed_gen.vuln_discovery_debug_task import VulnDiscoveryDebugTask

task = VulnDiscoveryDebugTask(
    package_name="my_package",
    harness_name="my_harness",
    challenge_task=challenge_task,
    codequery=codequery,
    project_yaml=project_yaml,
    redis=redis,
    reproduce_multiple=reproduce_multiple,
    sarifs=sarifs,
    crash_submit=crash_submit,
)

task.do_task(out_dir=Path("/output"), current_dir=Path("/current"))
```

### Configuration

```python
class VulnDiscoveryDebugTask:
    VULN_DISCOVERY_MAX_POV_COUNT = 5  # Max PoVs per iteration
    MAX_CONTEXT_ITERATIONS = 6         # Max context retrieval iterations
    MAX_POV_ITERATIONS = 3             # Max PoV write iterations
    DEBUG_AFTER_ITERATION = 1          # Start debugging after iteration 1
```

## State Management

### `VulnDiscoveryDebugState`

Extends `VulnBaseState` with debug-specific fields:

```python
class VulnDiscoveryDebugState(VulnBaseState):
    diff_content: str                  # Diff (for delta mode)
    debug_insights: str                # Accumulated debug findings
    should_debug: bool                 # Internal flag for workflow control
```

## Debug Output

For each debug session, creates:

```
output_dir/
├── debug_iter1/
│   ├── debug_script.gdb          # Generated GDB script
│   ├── debug_output.txt          # GDB execution output
│   ├── analysis.txt              # LLM's debug analysis
│   ├── pov_valid.txt             # Whether PoV crashes
│   └── debug_attempts.txt        # All debug attempts
├── iter0_gen_seed_1.seed         # PoVs from iteration 0
├── iter0_gen_seed_2.seed
├── iter1_gen_seed_1.seed         # PoVs from iteration 1 (with debug insights)
└── ...
```

## Example Scenario

### Iteration 1: Initial Attempt
```
1. Analysis: "Buffer overflow in strcpy at line 197"
2. PoV generated: sends 200 'A' characters
3. Testing: PoV doesn't crash
4. Debug triggered
```

### Debug Session
```
GDB reveals:
- Buffer size check was added that limits input to 100 bytes
- Input is truncated before reaching strcpy
- No overflow occurs

Debug insight: "The vulnerable code path is not reached 
because input is truncated by the new size check at line 190"
```

### Iteration 2: Adjusted Attempt
```
1. Analysis (with debug insights): "Need to bypass the size check 
   or exploit a different vulnerability"
2. PoV generated: tries to bypass the check or targets a different bug
3. Testing: Better success rate
```

## Advantages Over Standard Vuln Discovery

| Feature | Standard Task | Debug Task |
|---------|--------------|-----------|
| **Insight** | Static analysis only | Static + dynamic runtime analysis |
| **Iteration** | Retries blindly | Learns from actual execution |
| **Debugging** | Manual post-mortem | Automatic in-loop debugging |
| **Context** | Code + diffs | Code + diffs + GDB traces |
| **Efficiency** | May waste iterations | Targeted improvements |

## When to Use

### ✅ **Use VulnDiscoveryDebugTask when:**
- PoVs frequently fail for unclear reasons
- Need to understand runtime behavior
- Dealing with complex vulnerabilities
- Want maximum insight into failures
- Have GDB debugging infrastructure available

### ⚠️ **Stick with standard tasks when:**
- PoVs usually work on first try
- Fast iteration is more important than deep insight
- Debugging overhead is not justified
- Running in environments without GDB support

## Performance Considerations

- **Time:** Adds ~30-60 seconds per debug session (GDB execution)
- **Iterations:** May reduce total iterations needed due to better targeting
- **Resources:** Requires debug container (`gcr.io/oss-fuzz-base/base-runner-debug`)
- **Overall:** May be faster end-to-end despite per-iteration overhead

## Future Enhancements

Potential improvements:
1. **Multi-PoV debugging**: Debug multiple failed PoVs per iteration
2. **Smart debugging**: Only debug if LLM confidence is low
3. **Debug caching**: Reuse insights across similar vulnerabilities
4. **Parallel debugging**: Debug multiple PoVs simultaneously
5. **Lightweight debugging**: Use faster debugging methods for simple cases

