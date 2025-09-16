# Production AKS Deployment Guide

Full production deployment of the **Buttercup CRS** on Azure Kubernetes Service with proper networking, monitoring.

## Quick Setup (Recommended)

Use our automated setup script:

```bash
make setup-azure
```

This script will check prerequisites, help create service principals, configure the environment, and validate your setup.
You probably need at least `Contributor` role in your Azure subscription to deploy Buttercup.

### Production Configuration

The setup-azure make target will help you configure a simple production-ready
cluster, however each deployment is different based on requirements: cost,
number of tasks that you want to solve at the same time, size of projects, etc.

For more fine-grained adjustments that are not configurable during the automated setup script, modify `deployment/env` and `deployment/values-upstream-aks.template`. In particular you may want to change the number of nodes in the k8s cluster, the type of nodes, the number of pods for different kind of services, the storage, etc.

We *strongly suggest* you also enable Tailscale, so that your cluster is accessible only through the Tailscale network. Moreover, for a real production environment, you may want to generate and set secrets for all services, including redis, postgresql, etc.

## Deploy to AKS

**Deploy the cluster and services:**

```bash
make deploy
```

## Access the cluster

To access the CRS Web interface:
```bash
make web-ui
```


## Scaling and Management

- **Scale nodes:** Update `TF_VAR_usr_node_count` in your env file and run `make deploy` again
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
