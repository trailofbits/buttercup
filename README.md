# Buttercup Cyber Reasoning System (CRS)

**Buttercup** is a Cyber Reasoning System (CRS) developed by **Trail of Bits** for the **DARPA AIxCC (AI Cyber Challenge) competition**. It's a comprehensive automated vulnerability detection and patching system designed to compete in AI-driven cybersecurity challenges.

## Quick Start

Choose your deployment method:

- **[Local Development](#local-development)** - Quick setup for development and testing
- **[Production AKS Deployment](#production-aks-deployment)** - Full production deployment on Azure Kubernetes Service

## Local Development

The fastest way to get started with the **Buttercup CRS** system for development and testing.

### Quick Setup (Recommended)

Use our automated setup script:

```bash
./scripts/setup-local.sh
```

This script will install all dependencies, configure the environment, and guide you through the setup process.

### Manual Setup

If you prefer to set up manually, follow these steps:

```bash
# Docker
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
# Log out and back in for group changes to take effect

# kubectl
curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"
sudo install -o root -g root -m 0755 kubectl /usr/local/bin/kubectl

# Helm
curl https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash

# Minikube
curl -LO https://storage.googleapis.com/minikube/releases/latest/minikube-linux-amd64
sudo install minikube-linux-amd64 /usr/local/bin/minikube

# Git LFS (for some tests)
sudo apt-get install git-lfs
git lfs install
```

### Configuration

1. **Create configuration file:**
```bash
cp deployment/env.template deployment/env
```

2. **Configure the environment file** (`deployment/env`):

```bash
# Use minikube for local development
export BUTTERCUP_K8S_VALUES_TEMPLATE="k8s/values-minikube.template"
export CLUSTER_TYPE=minikube
export DEPLOY_CLUSTER=true

# Required API keys (get these from your providers)
export OPENAI_API_KEY="your-openai-api-key"
export ANTHROPIC_API_KEY="your-anthropic-api-key"

# GitHub Container Registry authentication
# Generate with: echo "username:your-github-pat" | base64
export GHCR_AUTH="base64-encoded-credentials"

# Docker Hub credentials
export DOCKER_USERNAME="your-docker-username"
export DOCKER_PAT="your-docker-pat"

# Test credentials (use these for local development)
export AZURE_ENABLED=false
export TAILSCALE_ENABLED=false
export COMPETITION_API_KEY_ID="11111111-1111-1111-1111-111111111111"
export COMPETITION_API_KEY_TOKEN="secret"
export CRS_KEY_ID="515cc8a0-3019-4c9f-8c1c-72d0b54ae561"
export CRS_KEY_TOKEN="VGuAC8axfOnFXKBB7irpNDOKcDjOlnyB"
export CRS_API_HOSTNAME="$(openssl rand -hex 16)"
export LITELLM_MASTER_KEY="$(openssl rand -hex 16)"

# Leave these empty for local development
export AZURE_API_BASE=""
export AZURE_API_KEY=""
```

### Start Local Development Environment

1. **Start the services:**
```bash
make deploy-local
```

2. **Verify deployment:**
```bash
kubectl get pods -n crs
kubectl get services -n crs
```

3. **Test with example task:**
```bash
make test
```

**Alternative manual commands:**
```bash
# Start services manually
cd deployment && make up

# Port forward manually
kubectl port-forward -n crs service/buttercup-competition-api 31323:1323

# Test manually
./orchestrator/scripts/task_crs.sh
```

### Stop Local Environment

```bash
make clean
```

**Alternative manual command:**
```bash
cd deployment && make down
```

## Production AKS Deployment

Full production deployment of the **Buttercup CRS** on Azure Kubernetes Service with proper networking, monitoring, and scaling for the DARPA AIxCC competition.

### Quick Setup (Recommended)

Use our automated setup script:

```bash
./scripts/setup-production.sh
```

This script will check prerequisites, help create service principals, configure the environment, and validate your setup.

### Manual Setup

If you prefer to set up manually, follow these steps:

### Prerequisites

- Azure CLI installed and configured
- Terraform installed
- Active Azure subscription
- Access to competition Tailscale tailnet

### Azure Setup

1. **Login to Azure:**
```bash
az login --tenant aixcc.tech
```

2. **Create Service Principal:**
```bash
# Get your subscription ID
az account show --query "{SubscriptionID:id}" --output table

# Create service principal (replace with your subscription ID)
az ad sp create-for-rbac --name "ButtercupCRS" --role Contributor --scopes /subscriptions/<YOUR-SUBSCRIPTION-ID>
```

3. **Set environment variables:**
```bash
export TF_ARM_TENANT_ID="<tenant-from-sp-output>"
export TF_ARM_CLIENT_ID="<appId-from-sp-output>"
export TF_ARM_CLIENT_SECRET="<password-from-sp-output>"
export TF_ARM_SUBSCRIPTION_ID="<your-subscription-id>"
```

### Production Configuration

1. **Configure environment file:**
```bash
cp deployment/env.template deployment/env
```

2. **Update `deployment/env` for production:**
```bash
# Use AKS for production
export BUTTERCUP_K8S_VALUES_TEMPLATE="k8s/values-aks.template"
export CLUSTER_TYPE=aks
export DEPLOY_CLUSTER=true

# Terraform variables
export TF_VAR_ARM_CLIENT_ID="<your-client-id>"
export TF_VAR_ARM_CLIENT_SECRET="<your-client-secret>"
export TF_VAR_ARM_TENANT_ID="<your-tenant-id>"
export TF_VAR_ARM_SUBSCRIPTION_ID="<your-subscription-id>"
export TF_VAR_usr_node_count=50
export TF_VAR_resource_group_name_prefix="buttercup-crs"

# Enable production features
export TAILSCALE_ENABLED=true
export TS_CLIENT_ID="<your-tailscale-oauth-client-id>"
export TS_CLIENT_SECRET="<your-tailscale-oauth-client-secret>"
export TS_OP_TAG="<your-tailscale-operator-tag>"

# Production API keys
export OPENAI_API_KEY="<your-openai-api-key>"
export ANTHROPIC_API_KEY="<your-anthropic-api-key>"
export AZURE_API_BASE="<your-azure-openai-base-url>"
export AZURE_API_KEY="<your-azure-openai-api-key>"

# GitHub Container Registry
export GHCR_AUTH="<base64-encoded-ghcr-credentials>"
export SCANTRON_GITHUB_PAT="<github-pat-with-repo-read+packages-read>"

# CRS credentials (generate secure ones)
export CRS_KEY_ID="$(python3 -c 'import uuid; print(str(uuid.uuid4()))')"
export CRS_KEY_TOKEN="$(python3 -c 'import secrets, string; print("".join(secrets.choice(string.ascii_uppercase + string.ascii_lowercase + string.digits) for _ in range(32)))')"
export CRS_KEY_TOKEN_HASH="<argon2-hash-for-crs-key-token>"

# Competition API
export COMPETITION_API_ENABLED=true
export COMPETITION_API_KEY_ID="<your-competitionapi-key-id>"
export COMPETITION_API_KEY_TOKEN="<your-competition-api-key-token>"

# Monitoring and observability
export LANGFUSE_ENABLED=true
export LANGFUSE_HOST="<your-langfuse-host-url>"
export LANGFUSE_PUBLIC_KEY="<your-langfuse-public-key>"
export LANGFUSE_SECRET_KEY="<your-langfuse-secret-key>"
export OTEL_ENDPOINT="<your-otel-endpoint>"
export OTEL_TOKEN="<your-otel-http-token>"
```

### Deploy to AKS

1. **Deploy the cluster and services:**
```bash
make deploy-production
```

2. **Get cluster credentials:**
```bash
az aks get-credentials --name <your-cluster-name> --resource-group <your-resource-group>
```

3. **Verify deployment:**
```bash
kubectl get pods -A
kubectl get services -A
```

**Alternative manual command:**
```bash
cd deployment && make up
```

### Production Access

1. **Get Tailscale ingress address:**
```bash
kubectl get -n crs-webservice ingress
```

2. **Access via Tailscale:**
The CRS API will be available through your Tailscale network at the ingress address.

### Scaling and Management

- **Scale nodes:** Update `TF_VAR_usr_node_count` in your env file and run `make up`
- **View logs:** `kubectl logs -n crs <pod-name>`
- **Monitor resources:** `kubectl top pods -A`

### Cleanup

```bash
make clean
```

**Alternative manual command:**
```bash
cd deployment && make down
```

## Development Workflow

### Using Makefile Shortcuts

The **Buttercup CRS** project includes a Makefile with convenient shortcuts for common tasks:

```bash
# View all available commands
make help

# Setup
make setup-local          # Automated local setup
make setup-production     # Automated production setup
make validate             # Validate current setup

# Deployment
make deploy               # Deploy to current environment
make deploy-local         # Deploy to local Minikube
make deploy-production    # Deploy to production AKS

# Testing
make test                 # Run test task

# Development
make lint                 # Lint all Python code
make lint-component COMPONENT=orchestrator  # Lint specific component

# Cleanup
make clean                # Clean up deployment
make clean-local          # Clean up local environment
```

### Running Tests

```bash
# Lint all Python code
make lint

# Lint specific component
make lint-component COMPONENT=orchestrator

# Run test task
make test
```

**Alternative manual commands:**
```bash
# Lint Python code
just lint-python-all

# Run specific component tests
just lint-python orchestrator

# Test manually
./orchestrator/scripts/task_crs.sh
./orchestrator/scripts/challenge.sh
```

### Docker Development

```bash
# Build and run with Docker Compose
docker-compose up -d

# Run specific services
docker-compose --profile fuzzer-test up
```

### Kubernetes Development

```bash
# Port forward for local access
kubectl port-forward -n crs service/buttercup-competition-api 31323:1323

# View logs
kubectl logs -n crs -l app=scheduler --tail=-1 --prefix

# Debug pods
kubectl exec -it -n crs <pod-name> -- /bin/bash
```

## Troubleshooting

### Common Issues

1. **Minikube won't start:**
```bash
minikube delete
minikube start --driver=docker
```

2. **Docker permission issues:**
```bash
sudo usermod -aG docker $USER
# Log out and back in
```

3. **Helm chart issues:**
```bash
helm repo update
helm dependency update deployment/k8s/
```

4. **Azure authentication:**
```bash
az login --tenant aixcc.tech
az account set --subscription <your-subscription-id>
```

### Getting Help

- **Validate your setup:** `./scripts/validate-setup.sh` - Check if your environment is ready
- Check the [Quick Reference Guide](docs/QUICK_REFERENCE.md) for common commands and troubleshooting
- Check the [deployment README](deployment/README.md) for detailed deployment information
- Check logs: `kubectl logs -n crs <pod-name>`

## Architecture

The **Buttercup CRS** system consists of several components designed to work together for automated vulnerability detection and patching:

- **Orchestrator**: Coordinates the overall repair process and manages the workflow
- **Fuzzer**: Discovers vulnerabilities through intelligent fuzzing techniques
- **Patcher**: Generates and applies security patches to fix vulnerabilities
- **Program Model**: Analyzes code structure and semantics for better understanding
- **Seed Generator**: Creates targeted test cases for vulnerability discovery
- **Competition API**: Interfaces with the DARPA AIxCC competition platform

For detailed architecture information, see the [deployment documentation](deployment/README.md).
