# CRS Results Monitoring Guide

## Quick Start

After submitting a challenge, monitor the results with:

```bash
# Live monitoring dashboard
./scripts/local/monitor.sh

# Check specific task
./scripts/local/monitor.sh --task-id <task-id>
```

## Where to Find Results

### 1. Live Monitoring Dashboard

The monitor script shows:
- **Service Status**: Real-time status of all CRS services (Docker + uvx)
  - ✅ Running services with health checks
  - 🚀 LiteLLM running via uvx
  - ❌ Stopped or failed services
- **Queue Status**: Real-time counts of tasks in each processing stage
- **Summary Panel**: Key metrics at a glance
  - Total services running
  - Crashes found
  - Patches generated
  - Tasks ready for processing
- **Recent Crashes**: Latest vulnerabilities found by fuzzing
- **Generated Patches**: Automatic fixes created by the patcher

### 2. Docker Logs

```bash
# Watch for crashes being discovered
docker compose logs -f unified-fuzzer | grep -E "(crash|ERROR|found)"

# Monitor patch generation
docker compose logs -f patcher | grep -E "(patch|vulnerability|fix)"

# Check scheduler for workflow progress
docker compose logs -f scheduler | grep -E "(VULNERABILITY|PATCH|SUBMIT)"
```

### 3. Redis Queues

Check queues directly:
```bash
docker compose exec redis redis-cli

# Check for crashes
LLEN crashes_queue
LRANGE crashes_queue 0 10

# Check for patches
LLEN patches_queue
LRANGE patches_queue 0 10

# Check for confirmed vulnerabilities
LLEN confirmed_vulnerabilities_queue
```

### 4. File System Artifacts

Results are stored in `/node_data/crs_scratch/<task-id>/`:

```bash
# On host (if using Docker volumes)
ls -la ./node_data/crs_scratch/

# Inside containers
docker compose exec scheduler ls -la /node_data/crs_scratch/<task-id>/
```

Look for:
- `crash-*` - Crash reproducer files
- `*.patch` - Generated patches
- `*report*.txt` - Analysis reports
- `*.log` - Processing logs

## Understanding Results

### Crash Detection
When the fuzzer finds a crash:
1. Creates a crash reproducer file
2. Sends crash info to `crashes_queue`
3. Triggers vulnerability analysis

### Patch Generation
When a vulnerability is confirmed:
1. Patcher analyzes the code
2. Generates a fix using LLM
3. Validates the patch
4. Sends to `patches_queue`

### Workflow States
Monitor these state transitions in scheduler logs:
- `BUILD` → Fuzzer is being built
- `FUZZ` → Active fuzzing
- `WAIT_VULNERABILITIES` → Processing crashes
- `WAIT_PATCH_*` → Generating/testing patches
- `SUBMIT_BUNDLE` → Submitting results

## Example: Monitoring the Crashy Project

1. Submit the challenge:
```bash
./scripts/local/submit.sh example-challenges/crashy-project
```

2. Note the task ID from submission output

3. Monitor live:
```bash
./scripts/local/monitor.sh
```

4. Watch for specific patterns:
```bash
# Crashes being found
docker compose logs -f unified-fuzzer | grep "crashy"

# Patches being generated
docker compose logs -f patcher | grep "task_id"
```

5. Check task artifacts:
```bash
./scripts/local/monitor.sh --task-id <your-task-id>
```

## Example Dashboard View

```
╭─ 🔍 CRS Monitor - 2024-01-15 14:32:45 ─────────────────────────────╮
│ ╭─ Service Status ──────╮ ╭─ Queue Status ─────╮ ╭─ Summary ──────╮ │
│ │ Service      Status   │ │ Queue         Count│ │ Services: 8/9  │ │
│ │ redis        ✅       │ │ Crashes         3  │ │ Crashes: 3     │ │
│ │ litellm      🚀       │ │ Patches         2  │ │ Patches: 2     │ │
│ │ scheduler    ✅       │ │ Ready Tasks     1  │ │ Tasks Ready: 1 │ │
│ │ fuzzer       ✅       │ ╰────────────────────╯ ╰────────────────╯ │
│ ╰────────────────────────╯                                          │
│ ╭─ Recent Crashes ──────╮ ╭─ Generated Patches ───────────────────╮ │
│ │ 1. Task: abc-123      │ │ 1. Task: abc-123                   │ │
│ │    Type: buffer_over  │ │    Vuln: VULN-001                  │ │
│ │    Time: 14:31:22     │ │    Time: 14:32:15                  │ │
│ ╰───────────────────────╯ ╰────────────────────────────────────────╯ │
╰─────────────────────────────────────────── Press Ctrl+C to exit ───╯
```

## Typical Timeline

- **0-30s**: Task downloaded and queued
- **30-60s**: Fuzzer built
- **1-2min**: First crashes discovered (for vulnerable code)
- **2-5min**: Vulnerabilities analyzed
- **5-10min**: Patches generated and validated

## Troubleshooting

### No Results Appearing

1. Check service health:
```bash
docker compose ps
```

2. Verify task was processed:
```bash
docker compose logs scheduler | grep <task-id>
```

3. Check for build errors:
```bash
docker compose logs unified-fuzzer | grep -i error
```

### Monitoring Script Connection Error

If monitor script can't connect:
```bash
# Ensure Redis is accessible
docker compose exec redis redis-cli ping

# Check Redis is exposed on localhost
docker compose ps | grep redis
```

### Finding Detailed Logs

For complete analysis logs:
```bash
# Get container logs
docker compose logs unified-fuzzer > fuzzer.log
docker compose logs patcher > patcher.log

# Search for your task
grep <task-id> fuzzer.log
grep <task-id> patcher.log
```