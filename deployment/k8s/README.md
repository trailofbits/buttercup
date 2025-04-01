# Buttercup: Kubernetes Deployment Guide

This guide explains how to set up and run the Buttercup system on Kubernetes.

## Prerequisites

- Kubernetes cluster (Minikube for local development or AKS for production)
- kubectl configured to communicate with your cluster
- Helm v3
- Access to container registries (ghcr.io)
- Access to required API keys (OpenAI, Azure, Anthropic)

## Environment Configuration

The Buttercup system can be deployed in two environments:
- `minikube`: Local development environment
- `aks`: Azure Kubernetes Service for production deployment

This is controlled via the `global.environment` setting in the values.yaml or values-override.yaml file.

## Quick Start

1. **Create a values-override.yaml file with your secrets:**
   ```yaml
   # Environment selection (minikube or aks)
   global:
     environment: "minikube"  # or "aks" for production

     # Langfuse configuration
     langfuse:
       enabled: true  # Set to true to enable Langfuse integration
       host: "https://cloud.langfuse.com"
       publicKey: "pk-lf-your-public-key"
       secretKey: "sk-lf-your-secret-key"

   # LiteLLM configuration
   litellm:
     masterKey: "your-secure-master-key"  # Generate with: openssl rand -hex 16
     azure:
       apiBase: "https://your-azure-endpoint.openai.azure.com/"
       apiKey: "your-azure-api-key"
     openai:
       apiKey: "your-openai-api-key"
     anthropic: 
       apiKey: "your-anthropic-api-key"

   crs:
      api_key_id: 515cc8a0-3019-4c9f-8c1c-72d0b54ae561
      api_key_token: VGuAC8axfOnFXKBB7irpNDOKcDjOlnyB
      api_key_token_hash: "$argon2id$v=19$m=65536,t=3,p=4$Dg1v6NPGTyXPoOPF4ozD5A$wa/85ttk17bBsIASSwdR/uGz5UKN/bZuu4wu+JIy1iA"
      # api_url: "https://ethereal-logic.tail7e9b4c.ts.net"
      competition_api_key_id: 11111111-1111-1111-1111-111111111111
      competition_api_key_token: secret
      # competition_api_url: "https://api.tail7e9b4c.ts.net"
   ```

2. **Install the Helm chart:**
   ```bash
   helm install buttercup ./ -f values-override.yaml
   ```

3. **Verify deployment:**
   ```bash
   kubectl get pods
   ```

## Required Secrets

The system requires several secrets for proper operation:

### 1. LiteLLM API Secrets

This secret contains API keys for LLM providers:

- **BUTTERCUP_LITELLM_KEY**: Master key for LiteLLM proxy authentication
- **AZURE_API_BASE**: Azure OpenAI endpoint
- **AZURE_API_KEY**: Azure OpenAI API key
- **OPENAI_API_KEY**: OpenAI API key
- **ANTHROPIC_API_KEY**: Anthropic API key

These are populated from the `values-override.yaml` file.

### 2. Langfuse Secrets (Optional)

If Langfuse integration is enabled:

- **LANGFUSE_HOST**: URL of the Langfuse service
- **LANGFUSE_PUBLIC_KEY**: Langfuse public key
- **LANGFUSE_SECRET_KEY**: Langfuse secret key

### 3. Container Registry Auth

For pulling private container images, create a Kubernetes secret named `ghcr-auth`:

```bash
kubectl create secret generic ghcr \
  --from-literal=pat=YOUR_GITHUB_PAT \
  --from-literal=username=USERNAME \
  --from-literal=scantron_github_pat=GITHUB_PAT_WITH_REPO_AND_GHCR_PERMISSIONS
```

## System Architecture

The Buttercup system consists of several microservices:

1. **Core Infrastructure**:
   - **Redis**: Message broker and task queue
   - **PostgreSQL**: Database for LiteLLM
   - **LiteLLM**: LLM proxy for all AI model interactions

2. **Task Management**:
   - **task-server**: API server for task management
   - **task-downloader**: Downloads tasks from the task server
   - **scheduler**: Orchestrates task execution

3. **Processing Components**:
   - **program-model**: Analyzes program structure
   - **build-bot**: Builds programs
   - **fuzzer-bot**: Performs fuzzing operations
   - **coverage-bot**: Analyzes code coverage
   - **tracer-bot**: Traces execution paths
   - **seed-gen**: Generates seed inputs
   - **patcher**: Creates patches for vulnerabilities

4. **External Integration**:
   - **competition-api**: API for competition integration

## Storage Configuration

The system uses two persistent volumes:

1. **tasks_storage**: For storing downloaded tasks
   - Default size: 5Gi
   - Access mode: ReadWriteMany

2. **crs_scratch**: Working directory for processing
   - Default size: 10Gi
   - Access mode: ReadWriteMany

For AKS deployment, specify an appropriate storage class that supports ReadWriteMany access mode (e.g., "azurefile" or "azurefile-premium").

## Task Server Authentication

The task server API is secured with authentication:
- API Key ID: 515cc8a0-3019-4c9f-8c1c-72d0b54ae561
- API Token: VGuAC8axfOnFXKBB7irpNDOKcDjOlnyB

These credentials are configured in the system by default.

## Customizing the Deployment

### Resource Allocation

Each component has configurable resource limits and requests in the values.yaml file. Adjust these based on your cluster capacity and workload requirements.

### Component Configuration

Individual components can be configured through their respective sections in values.yaml or values-override.yaml:

```yaml
# Example: Increasing build-bot replicas
build-bot:
  replicaCount: 8
  timer: 3000
```

## Updating the Deployment

To update your deployment after making changes:

```bash
helm upgrade buttercup ./ -f values-override.yaml
```

## Troubleshooting

### Checking Pod Status
```bash
kubectl get pods
```

### Viewing Pod Logs
```bash
kubectl logs <pod-name>
```

### Common Issues

1. **Image Pull Errors**: Verify your ghcr-auth secret is correctly configured
2. **Resource Constraints**: Adjust resource limits in values.yaml
3. **Storage Issues**: Ensure your storage class supports ReadWriteMany access mode
4. **API Key Errors**: Check that all required API keys are set in values-override.yaml

## LiteLLM Configuration

The system uses LiteLLM to proxy all LLM requests. The configuration includes models from:
- Azure OpenAI
- OpenAI
- Anthropic

To modify the available models, edit the `litellm-helm.proxy_config.model_list` section in values.yaml.

## Security Notes

- Never commit values-override.yaml with real credentials
- Rotate API keys regularly
- Use a dedicated service principal with minimal permissions for AKS deployments
- Consider network policies to restrict pod communication

## Support

For issues or questions, please file an issue in the project repository.
