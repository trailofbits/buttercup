# VulnDiscoveryDebugTask Configuration Guide

## Overview

The `VulnDiscoveryDebugTask` has been integrated into the SeedGenBot and can be enabled through environment variables. This guide explains how to configure task probabilities and enable the debug-enhanced vulnerability discovery workflow.

## Quick Start

### Enable Debug Vulnerability Discovery

To use the debug-enabled task instead of the legacy delta/full tasks:

```bash
export BUTTERCUP_USE_DEBUG_VULN_DISCOVERY=true
```

Then restart your seed-gen deployment:

```bash
kubectl rollout restart deployment/seed-gen -n crs
```

### Disable All Other Tasks (Debug Only Mode)

To run **only** the debug vulnerability discovery task:

```bash
# Set probabilities to 0 for seed-init and seed-explore
export BUTTERCUP_SEED_INIT_PROB_FULL=0.0
export BUTTERCUP_SEED_INIT_PROB_DELTA=0.0
export BUTTERCUP_SEED_EXPLORE_PROB_FULL=0.0
export BUTTERCUP_SEED_EXPLORE_PROB_DELTA=0.0

# Set vuln-discovery to 100%
export BUTTERCUP_VULN_DISCOVERY_PROB_FULL=1.0
export BUTTERCUP_VULN_DISCOVERY_PROB_DELTA=1.0

# Enable debug task
export BUTTERCUP_USE_DEBUG_VULN_DISCOVERY=true

# Disable minimum run requirements
export BUTTERCUP_MIN_SEED_INIT_RUNS=0
export BUTTERCUP_MIN_VULN_DISCOVERY_RUNS=0
```

## Environment Variables Reference

### Task Selection Control

| Variable | Default | Description |
|----------|---------|-------------|
| `BUTTERCUP_USE_DEBUG_VULN_DISCOVERY` | `false` | Enable the debug-enhanced vuln discovery task (replaces delta/full tasks) |
| `BUTTERCUP_SEED_GEN_TEST_TASK` | (none) | Force a specific task type: `seed-init`, `seed-explore`, or `vuln-discovery` |

### Full Mode Probabilities

Used when `challenge_task.is_delta_mode() == False`

| Variable | Default | Description |
|----------|---------|-------------|
| `BUTTERCUP_SEED_INIT_PROB_FULL` | `0.05` | Probability of running seed-init (5%) |
| `BUTTERCUP_VULN_DISCOVERY_PROB_FULL` | `0.35` | Probability of running vuln-discovery (35%) |
| `BUTTERCUP_SEED_EXPLORE_PROB_FULL` | `0.60` | Probability of running seed-explore (60%) |

**Note:** Probabilities should sum to 1.0

### Delta Mode Probabilities

Used when `challenge_task.is_delta_mode() == True`

| Variable | Default | Description |
|----------|---------|-------------|
| `BUTTERCUP_SEED_INIT_PROB_DELTA` | `0.05` | Probability of running seed-init (5%) |
| `BUTTERCUP_VULN_DISCOVERY_PROB_DELTA` | `0.45` | Probability of running vuln-discovery (45%) |
| `BUTTERCUP_SEED_EXPLORE_PROB_DELTA` | `0.50` | Probability of running seed-explore (50%) |

**Note:** Probabilities should sum to 1.0

### Minimum Run Counts

Forces certain tasks to run a minimum number of times before using probability-based sampling:

| Variable | Default | Description |
|----------|---------|-------------|
| `BUTTERCUP_MIN_SEED_INIT_RUNS` | `3` | Minimum seed-init runs before using probabilities |
| `BUTTERCUP_MIN_VULN_DISCOVERY_RUNS` | `1` | Minimum vuln-discovery runs before using probabilities |

## Common Configuration Scenarios

### Scenario 1: Debug-Only Mode

**Goal:** Only run debug vulnerability discovery, no seed generation or exploration.

```bash
export BUTTERCUP_USE_DEBUG_VULN_DISCOVERY=true
export BUTTERCUP_SEED_INIT_PROB_FULL=0.0
export BUTTERCUP_SEED_INIT_PROB_DELTA=0.0
export BUTTERCUP_SEED_EXPLORE_PROB_FULL=0.0
export BUTTERCUP_SEED_EXPLORE_PROB_DELTA=0.0
export BUTTERCUP_VULN_DISCOVERY_PROB_FULL=1.0
export BUTTERCUP_VULN_DISCOVERY_PROB_DELTA=1.0
export BUTTERCUP_MIN_SEED_INIT_RUNS=0
export BUTTERCUP_MIN_VULN_DISCOVERY_RUNS=0
```

### Scenario 2: Enable Debug for Testing

**Goal:** Enable debug task while keeping normal task distribution.

```bash
export BUTTERCUP_USE_DEBUG_VULN_DISCOVERY=true
# All other probabilities remain at defaults
```

### Scenario 3: Disable Seed Generation

**Goal:** Focus on vulnerability discovery and exploration only.

```bash
export BUTTERCUP_SEED_INIT_PROB_FULL=0.0
export BUTTERCUP_SEED_INIT_PROB_DELTA=0.0
export BUTTERCUP_VULN_DISCOVERY_PROB_FULL=0.5
export BUTTERCUP_VULN_DISCOVERY_PROB_DELTA=0.5
export BUTTERCUP_SEED_EXPLORE_PROB_FULL=0.5
export BUTTERCUP_SEED_EXPLORE_PROB_DELTA=0.5
export BUTTERCUP_MIN_SEED_INIT_RUNS=0
```

### Scenario 4: Aggressive Vuln Discovery

**Goal:** Maximize vulnerability discovery (with debug enabled).

```bash
export BUTTERCUP_USE_DEBUG_VULN_DISCOVERY=true
export BUTTERCUP_VULN_DISCOVERY_PROB_FULL=0.8
export BUTTERCUP_VULN_DISCOVERY_PROB_DELTA=0.8
export BUTTERCUP_SEED_EXPLORE_PROB_FULL=0.2
export BUTTERCUP_SEED_EXPLORE_PROB_DELTA=0.2
export BUTTERCUP_SEED_INIT_PROB_FULL=0.0
export BUTTERCUP_SEED_INIT_PROB_DELTA=0.0
export BUTTERCUP_MIN_SEED_INIT_RUNS=0
```

## Deployment Methods

### Method 1: Kubernetes ConfigMap

Edit your seed-gen deployment:

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: seed-gen-config
  namespace: crs
data:
  BUTTERCUP_USE_DEBUG_VULN_DISCOVERY: "true"
  BUTTERCUP_VULN_DISCOVERY_PROB_FULL: "1.0"
  BUTTERCUP_VULN_DISCOVERY_PROB_DELTA: "1.0"
  BUTTERCUP_SEED_INIT_PROB_FULL: "0.0"
  BUTTERCUP_SEED_INIT_PROB_DELTA: "0.0"
  BUTTERCUP_SEED_EXPLORE_PROB_FULL: "0.0"
  BUTTERCUP_SEED_EXPLORE_PROB_DELTA: "0.0"
  BUTTERCUP_MIN_SEED_INIT_RUNS: "0"
  BUTTERCUP_MIN_VULN_DISCOVERY_RUNS: "0"
```

Then reference in deployment:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: seed-gen
spec:
  template:
    spec:
      containers:
      - name: seed-gen
        envFrom:
        - configMapRef:
            name: seed-gen-config
```

Apply:

```bash
kubectl apply -f seed-gen-config.yaml
kubectl rollout restart deployment/seed-gen -n crs
```

### Method 2: Helm Values

If using Helm deployment, add to `values.yaml`:

```yaml
seedGen:
  env:
    BUTTERCUP_USE_DEBUG_VULN_DISCOVERY: "true"
    BUTTERCUP_VULN_DISCOVERY_PROB_FULL: "1.0"
    BUTTERCUP_VULN_DISCOVERY_PROB_DELTA: "1.0"
    BUTTERCUP_SEED_INIT_PROB_FULL: "0.0"
    BUTTERCUP_SEED_INIT_PROB_DELTA: "0.0"
    BUTTERCUP_SEED_EXPLORE_PROB_FULL: "0.0"
    BUTTERCUP_SEED_EXPLORE_PROB_DELTA: "0.0"
    BUTTERCUP_MIN_SEED_INIT_RUNS: "0"
```

Then upgrade:

```bash
helm upgrade buttercup ./deployment/k8s/charts/buttercup -f values.yaml
```

### Method 3: Local Development (.env file)

For local testing:

```bash
# Create or edit deployment/env
cat >> deployment/env << 'EOF'
BUTTERCUP_USE_DEBUG_VULN_DISCOVERY=true
BUTTERCUP_VULN_DISCOVERY_PROB_FULL=1.0
BUTTERCUP_VULN_DISCOVERY_PROB_DELTA=1.0
BUTTERCUP_SEED_INIT_PROB_FULL=0.0
BUTTERCUP_SEED_INIT_PROB_DELTA=0.0
BUTTERCUP_SEED_EXPLORE_PROB_FULL=0.0
BUTTERCUP_SEED_EXPLORE_PROB_DELTA=0.0
BUTTERCUP_MIN_SEED_INIT_RUNS=0
BUTTERCUP_MIN_VULN_DISCOVERY_RUNS=0
EOF

# Redeploy
make deploy
```

## Verification

### Check Configuration is Applied

```bash
# View seed-gen logs to confirm settings
kubectl logs -n crs deployment/seed-gen --tail=100 | grep "Task probabilities"
```

You should see:

```
Task probabilities (FULL): seed-init=0.0, vuln-discovery=1.0, seed-explore=0.0
Task probabilities (DELTA): seed-init=0.0, vuln-discovery=1.0, seed-explore=0.0
Min runs: seed-init=0, vuln-discovery=0
Use debug vuln discovery: True
```

### Monitor Task Selection

```bash
# Watch which tasks are being executed
kubectl logs -n crs deployment/seed-gen -f | grep "Running seed-gen task"
```

You should see only:

```
Running seed-gen task: vuln-discovery
```

### Check Debug Activity

```bash
# Look for debug session logs
kubectl logs -n crs deployment/seed-gen -f | grep "Starting debug session"
```

## Key Differences: Legacy vs Debug Task

| Feature | Legacy (Delta/Full Tasks) | Debug Task |
|---------|--------------------------|------------|
| **Mode Detection** | Separate classes | Single unified class |
| **Delta Support** | ✅ `VulnDiscoveryDeltaTask` | ✅ Runtime detection |
| **Full Support** | ✅ `VulnDiscoveryFullTask` | ✅ Runtime detection |
| **GDB Debugging** | ❌ None | ✅ Automatic after failed PoV |
| **Debug Insights** | ❌ None | ✅ Fed back into next iteration |
| **Debug After** | N/A | After iteration 1 (configurable) |
| **Max Debug Iterations** | N/A | 5 (in `DebugSubagent`) |

## Troubleshooting

### Task Still Running seed-init

**Symptom:** Logs show seed-init running despite setting probabilities to 0.

**Cause:** `MIN_SEED_INIT_RUNS` is still > 0.

**Solution:**
```bash
export BUTTERCUP_MIN_SEED_INIT_RUNS=0
```

### Debug Task Not Running

**Symptom:** Logs show `VulnDiscoveryDeltaTask` or `VulnDiscoveryFullTask`.

**Cause:** `BUTTERCUP_USE_DEBUG_VULN_DISCOVERY` not set or set to `false`.

**Solution:**
```bash
export BUTTERCUP_USE_DEBUG_VULN_DISCOVERY=true
# Restart pod
kubectl rollout restart deployment/seed-gen -n crs
```

### Import Error

**Symptom:** `ImportError: cannot import name 'VulnDiscoveryDebugTask'`

**Cause:** The new file wasn't included in the build.

**Solution:**
```bash
# Rebuild and redeploy
make build-images
make deploy
```

## Advanced Configuration

### Adjust Debug Trigger Point

Edit `vuln_discovery_debug_task.py`:

```python
class VulnDiscoveryDebugTask(VulnBaseTask):
    DEBUG_AFTER_ITERATION = 1  # ← Change this to trigger debug earlier/later
```

- `0` = Debug on first failure
- `1` = Debug after first iteration fails
- `2` = Debug after second iteration fails, etc.

### Adjust Max Debug Iterations

Edit `debug_subagent.py`:

```python
class DebugSubagent:
    MAX_DEBUG_ITERATIONS: ClassVar[int] = 5  # ← Increase for more thorough debugging
```

## Performance Considerations

**Debug Mode Impact:**
- ✅ More accurate PoV generation (GDB insights)
- ✅ Better understanding of why PoVs fail
- ⚠️ Slightly slower per-task (GDB execution time)
- ⚠️ Requires debug container image

**Recommended for:**
- 🎯 Testing and validation
- 🎯 Difficult vulnerabilities
- 🎯 Delta mode challenges
- 🎯 When PoV success rate is low

**Not recommended for:**
- ❌ High-throughput fuzzing campaigns
- ❌ Simple buffer overflows (usually work without debugging)
- ❌ When compute resources are constrained

## See Also

- [VULN_DISCOVERY_DEBUG_TASK.md](./VULN_DISCOVERY_DEBUG_TASK.md) - Architecture and design
- [TESTING_DEBUG_SUBAGENT.md](./TESTING_DEBUG_SUBAGENT.md) - Testing guide
- [debug_subagent.py](./src/buttercup/seed_gen/debug_subagent.py) - Implementation
- [vuln_discovery_debug_task.py](./src/buttercup/seed_gen/vuln_discovery_debug_task.py) - Task implementation

