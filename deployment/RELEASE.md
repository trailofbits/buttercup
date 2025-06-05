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
   - Total Regional vCPUs: ~800
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
  - For production: Use actual CRS hostname
- CRS_URL: Update to match CRS_API_HOSTNAME (e.g., https://ethereal-logic-unscored-2.tail7e9b4c.ts.net)

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
- Check `/status` works well:
   ```bash
   curl -u $COMP_API_ID:$COMP_API_TOKEN https://<team-moniker>.tasker.aixcc.tech/crs/status/<team-moniker>-exhibition3
   ```

- Monitor deployment logs for any errors
- Verify all services are running correctly
- Test API endpoints and functionality
- Check resource utilization in Azure portal
