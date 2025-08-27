# Production AKS Deployment Guide

> **⚠️ Notice:**
> The following production deployment instructions have **not been fully tested**.
> Please proceed with caution and verify each step in your environment.
> If you encounter issues, consult the script comments and configuration files for troubleshooting.

Full production deployment of the **Buttercup CRS** on Azure Kubernetes Service with proper networking, monitoring, and scaling for the DARPA AIxCC competition.

## Quick Setup (Recommended)

Use our automated setup script:

```bash
make setup-azure
```

This script will check prerequisites, help create service principals, configure the environment, and validate your setup.

## Manual Setup

If you prefer to set up manually, follow these steps:

### Prerequisites

- Azure CLI installed and configured
- Terraform installed
- Active Azure subscription
- Access to competition Tailscale tailnet

### Azure Setup

1. **Login to Azure:**

```bash
az login --tenant <your-tenant-here>
```

2. **Create Service Principal:**

```bash
# Get your subscription ID
az account show --query "{SubscriptionID:id}" --output table

# Create service principal (replace with your subscription ID)
az ad sp create-for-rbac --name "ButtercupCRS" --role Contributor --scopes /subscriptions/<YOUR-SUBSCRIPTION-ID>
```

### Production Configuration

1. **Configure environment file:**

```bash
cp deployment/env.template deployment/env
```

2. **Update `deployment/env` for production:**

Look at the comments in the `deployment/env.template` for how to set variables.
In particular, set `TF_VAR_*` variables, and `TAILSCALE_*` if used.

## Deploy to AKS

**Deploy the cluster and services:**

```bash
make deploy-azure
```

**Alternative manual command:**

```bash
cd deployment && make up
```

## Scaling and Management

- **Scale nodes:** Update `TF_VAR_usr_node_count` in your env file and run `make up`
- **View logs:** `kubectl logs -n crs <pod-name>`
- **Monitor resources:** `kubectl top pods -A`

## Additional Resources

For detailed deployment instructions and advanced configuration options, see the [deployment README](../deployment/README.md).

## Troubleshooting

### Azure Authentication Issues

```bash
az login --tenant <your-tenant>
az account set --subscription <your-subscription-id>
```

### Cluster Management

```bash
# Get cluster credentials
az aks get-credentials --name <cluster-name> --resource-group <resource-group>

# View cluster info
az aks show --name <cluster-name> --resource-group <resource-group>
```

For more troubleshooting information, see the main [Quick Reference Guide](QUICK_REFERENCE.md).
