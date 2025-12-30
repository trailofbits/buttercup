# Quick Start: Debug Vulnerability Discovery

## TL;DR - Enable Debug Task

```bash
# 1. Enable debug task
export BUTTERCUP_USE_DEBUG_VULN_DISCOVERY=true

cccbeibrtuebbevirbkcuirjcchlirdkurjglibhci

export BUTTERCUP_SEED_INIT_PROB_FULL=0.0
export BUTTERCUP_SEED_INIT_PROB_DELTA=0.0
export BUTTERCUP_SEED_EXPLORE_PROB_FULL=0.0
export BUTTERCUP_SEED_EXPLORE_PROB_DELTA=0.0
export BUTTERCUP_VULN_DISCOVERY_PROB_FULL=1.0
export BUTTERCUP_VULN_DISCOVERY_PROB_DELTA=1.0
export BUTTERCUP_MIN_SEED_INIT_RUNS=0
export BUTTERCUP_MIN_VULN_DISCOVERY_RUNS=0

# 3. Restart seed-gen
kubectl rollout restart deployment/seed-gen -n crs
```

## What You Get

✅ **Automatic GDB debugging** when PoVs fail to crash  
✅ **Debug insights** fed back into next iteration  
✅ **Works for both delta and full modes** (unified task)  
✅ **Better PoV success rate** through runtime analysis  

## Verify It's Working

```bash
# Check configuration
kubectl logs -n crs deployment/seed-gen --tail=50 | grep "Use debug vuln discovery"
# Should show: Use debug vuln discovery: True

# Watch task selection
kubectl logs -n crs deployment/seed-gen -f | grep "Running seed-gen task"
# Should show: Running seed-gen task: vuln-discovery

# Watch debug sessions
kubectl logs -n crs deployment/seed-gen -f | grep "Starting debug session"
# Should show GDB debugging activity when PoVs fail
```

## Configuration Options

| Variable | Default | Set to | Effect |
|----------|---------|--------|--------|
| `BUTTERCUP_USE_DEBUG_VULN_DISCOVERY` | `false` | `true` | Enable debug task |
| `BUTTERCUP_SEED_INIT_PROB_*` | `0.05` | `0.0` | Disable seed-init |
| `BUTTERCUP_SEED_EXPLORE_PROB_*` | `0.5-0.6` | `0.0` | Disable seed-explore |
| `BUTTERCUP_VULN_DISCOVERY_PROB_*` | `0.35-0.45` | `1.0` | Only vuln-discovery |
| `BUTTERCUP_MIN_SEED_INIT_RUNS` | `3` | `0` | Skip forced seed-init |
| `BUTTERCUP_MIN_VULN_DISCOVERY_RUNS` | `1` | `0` | Skip forced vuln-discovery |

**Note:** `*` means both `_FULL` and `_DELTA` variants

## For More Details

See [VULN_DISCOVERY_DEBUG_CONFIGURATION.md](./VULN_DISCOVERY_DEBUG_CONFIGURATION.md) for:
- Complete environment variable reference
- Deployment methods (Kubernetes, Helm, local)
- Common configuration scenarios
- Troubleshooting guide
- Performance considerations

