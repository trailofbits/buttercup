# CRS Deployment Instructions for Competition Rounds

## Prerequisites

### Azure Setup
1. Verify Azure subscription resource providers:
   - Navigate to: Subscriptions > Settings > Resource Providers
   - Ensure these providers are registered:
     - Microsoft.Compute
     - Microsoft.Storage
     - Microsoft.Network

2. Verify and adjust Azure quotas:
   - Total Regional vCPUs: ~2000
   - Specific VM type quotas (e.g., Standard LS family vCPUs)
   - Note: If deployment fails, incrementally increase quotas in small steps

## Pre-deployment Configuration

### Version Updates
1. Update image tags in `values-prod.template` with new release version
2. Update version number in `orchestrator/pyproject.toml` to match image tags
3. Create a new release with the version as tag name

### Environment Configuration
Create a production environment file with the following variables:

#### Azure Configuration (TF_VAR_*)
- Ensure you're in the round subscription (not dev)
- For Principal Service Provider:
  - Use a unique name to prevent azcli from patching existing SP

#### Competition Configuration
- TS_* variables: Enable as required
- COMPETITION_API_* variables: Set according to competition requirements
- CRS_* variables: Configure as needed
- CRS_API_HOSTNAME: Set to competition-specific value (e.g., ethereal-logic-unscored-2)
  - For pre-competition testing: Append suffix (e.g., `-dev1`) to avoid LetsEncrypt rate limits
  - For production: Set it to something like `-pre-final-test1`, then follow the "Post deployment" steps to rename the Tailscale hostname once you have tested things work.

#### Service Configuration
- LLM keys: Use organization-provided keys
- LANGFUSE: Disable for production
- OTEL endpoint: Use organization-provided endpoint

## Deployment Steps

1. Clean up deployment artifacts:
   ```bash
   git clean -dxff deployment/k8s/charts
   ```

2. Delete old terraform directory:
   ```bash
   rm -rf deployment/.terraform
   ```

3. Update storage configuration:
   - Modify `storage_account_name` in `deployment/backend.tf` to point to production storage

4. Ensure `deployment/env` points to the right environment file
   ```bash
   ls -lah deployment/env
   ```

5. Deploy:
   ```bash
   cd deployment
   make up
   ```

## Post-deployment Verification
- Make sure all pods are up and running:
   ```bash
   kubectl get pods -n crs
   ```
- Check the tailscale hostname is correct:
   ```bash
   curl -u $COMPETITION_API_KEY_ID:$COMPETITION_API_KEY_TOKEN https://ethereal-logic.tasker.aixcc.tech/tailscale/device/
   ```
- Check `/status` works well:
   ```bash
   curl -u $COMPETITION_API_KEY_ID:$COMPETITION_API_KEY_TOKEN https://ethereal-logic.tasker.aixcc.tech/crs/status/ethereal-logic-pre-final
   ```
- Rename Tailscale hostname if necessary:
   ```bash
   curl -u $COMPETITION_API_KEY_ID:$COMPETITION_API_KEY_TOKEN -X PATCH https://ethereal-logic.tasker.aixcc.tech/tailscale/device/ethereal-logic-internal-1806 -H 'Content-Type: application/json' -d '{"hostname":"ethereal-logic-final"}'
   ```
   Where `ethereal-logic-internal-1806` is the current hostname of your device (you can get it from the command `curl -u $COMPETITION_API_KEY_ID:$COMPETITION_API_KEY_TOKEN https://ethereal-logic.tasker.aixcc.tech/tailscale/device/`) and `ethereal-logic-final` is the new hostname you want to test (e.g. the hostname the organizers want to see up and running for the round)
- Task a simple challenge for testing:
   ```bash
   curl -u $COMPETITION_API_KEY_ID:$COMPETITION_API_KEY_TOKEN -X POST 'https://api.aixcc.tech/v1/request/ex3-lp-delta-01' --json '{"duration_secs":900}'
   ```

- List available challenges for testing:
   ```bash
   curl -u $COMPETITION_API_KEY_ID:$COMPETITION_API_KEY_TOKEN -X 'GET' 'https://api.aixcc.tech/v1/request/list/'
   ```

- Monitor deployment logs for any errors
- Verify all services are running correctly
- Test API endpoints and functionality
- Check resource utilization in Azure portal
