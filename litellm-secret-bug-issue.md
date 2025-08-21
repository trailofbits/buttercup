# Helm Deployment Fails: litellm-api-user Secret Not Created, Blocking Patcher and Seed-gen Pods

## Summary
The Buttercup Helm deployment has a critical bug where the `patcher` and `seed-gen` pods fail to start because they depend on a secret (`litellm-api-user`) that is not reliably created. This causes the deployment to timeout and fail, even though all other components start successfully.

## Environment
- **Platform**: Ubuntu 22.04 ARM64 (via Multipass on macOS)
- **Kubernetes**: Minikube v1.36.0
- **Deployment Method**: `make deploy-local`
- **Affected Components**: patcher, seed-gen

## Problem Description

### 1. Root Cause
The `litellm-user-keys-setup` post-install job is responsible for creating the `litellm-api-user` secret, but it frequently fails due to:
- Race condition with LiteLLM service startup
- Insufficient retry/timeout configuration
- No fallback mechanism when the job fails

### 2. Symptoms
```bash
$ kubectl get pods -n crs
NAME                                    READY   STATUS      RESTARTS   AGE
buttercup-patcher-7d6646f85d-cv7ht     0/1     Init:0/3    0          24m
buttercup-seed-gen-57985f475f-fsz6v    0/1     Init:0/3    0          24m
```

Both pods are stuck in `Init:0/3` state with the error:
```
Warning  FailedMount  MountVolume.SetUp failed for volume "api-key-secret" : secret "litellm-api-user" not found
```

### 3. Investigation Results

The job that should create the secret fails:
```bash
$ kubectl get jobs -n crs
NAME                      STATUS     COMPLETIONS   DURATION   AGE
litellm-user-keys-setup   Failed     0/1           33m        33m
```

The job reaches its backoff limit trying to connect to LiteLLM and create a user API key.

## Current Workaround

Users can manually create the missing secret:
```bash
kubectl create secret generic litellm-api-user -n crs \
  --from-literal=API_KEY=$(kubectl get secret buttercup-litellm-api-secrets -n crs \
  -o jsonpath='{.data.BUTTERCUP_LITELLM_KEY}' | base64 -d)
```

Then restart the affected pods:
```bash
kubectl delete pod -l app=patcher -n crs
kubectl delete pod -l app=seed-gen -n crs
```

## Proposed Solutions

### Option 1: Improve Job Robustness (Recommended)
Modify `deployment/k8s/templates/litellm-user-keys-job.yaml`:

```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: litellm-user-keys-setup
  annotations:
    "helm.sh/hook": post-install,post-upgrade
    "helm.sh/hook-weight": "10"  # Ensure it runs after LiteLLM
spec:
  backoffLimit: 10  # Increase from default 6
  activeDeadlineSeconds: 1800  # 30 minutes instead of default
  template:
    spec:
      serviceAccountName: litellm-user-keys-setup
      restartPolicy: OnFailure
      initContainers:
        - name: wait-for-litellm
          image: curlimages/curl:8.6.0
          command:
            - sh
            - -c
            - |
              until curl -f http://{{ .Release.Name }}-litellm:4000/health/readiness; do
                echo "Waiting for LiteLLM to be ready..."
                sleep 5
              done
      containers:
        # ... rest of the job spec
```

### Option 2: Create Fallback Secret
Add a new template `deployment/k8s/templates/litellm-api-user-fallback.yaml`:

```yaml
# Only create if the job didn't create it
{{- if not (lookup "v1" "Secret" .Release.Namespace "litellm-api-user") }}
apiVersion: v1
kind: Secret
metadata:
  name: litellm-api-user
  annotations:
    "helm.sh/hook": post-install
    "helm.sh/hook-weight": "20"  # Run after the job
type: Opaque
data:
  # Use the master key as fallback
  API_KEY: {{ (lookup "v1" "Secret" .Release.Namespace (printf "%s-litellm-api-secrets" .Release.Name)).data.BUTTERCUP_LITELLM_KEY }}
{{- end }}
```

### Option 3: Use Existing Secret
Modify `patcher` and `seed-gen` deployments to use the existing `buttercup-litellm-api-secrets` directly:

In `deployment/k8s/charts/patcher/templates/deployment.yaml` and `deployment/k8s/charts/seed-gen/templates/deployment.yaml`:

```yaml
# Change from:
{{- include "buttercup.env.llm" (merge (dict "secretName" "litellm-api-user" "secretKey" "API_KEY") .) | nindent 8 }}

# To:
{{- include "buttercup.env.llm" (merge (dict "secretName" (printf "%s-litellm-api-secrets" .Release.Name) "secretKey" "BUTTERCUP_LITELLM_KEY") .) | nindent 8 }}
```

### Option 4: Make Secret Creation Synchronous
Instead of using a post-install hook, make the secret creation part of the regular deployment:

1. Create a Kubernetes Job (not a Hook) that runs before patcher/seed-gen
2. Add init containers to patcher/seed-gen that wait for the secret to exist
3. Use a ConfigMap to track job completion status

## Impact
- **High severity**: Prevents successful deployment without manual intervention
- **Affects**: All new deployments, especially in resource-constrained environments
- **Frequency**: Appears to be more common in nested virtualization or ARM64 environments

## Additional Context

The issue is exacerbated by:
1. No clear error message to users about what failed
2. Helm reports timeout without indicating which specific component failed
3. The post-install hook failure is silent unless users know to check jobs

## Recommended Fix Priority
**Option 1** (Improve Job Robustness) is recommended as it:
- Maintains the intended architecture
- Provides better reliability without changing the security model
- Is backward compatible
- Gives clear failure indication if it still fails

## Testing Requirements
After implementing the fix, test:
1. Fresh deployment on resource-constrained systems
2. Deployment with slow LiteLLM startup
3. Upgrade scenarios from existing deployments
4. Rollback scenarios

## Related Files
- `deployment/k8s/templates/litellm-user-keys-job.yaml`
- `deployment/k8s/templates/litellm-user-keys-setup-script.yaml`
- `deployment/k8s/charts/patcher/templates/deployment.yaml`
- `deployment/k8s/charts/seed-gen/templates/deployment.yaml`
- `deployment/k8s/templates/_helpers.tpl`