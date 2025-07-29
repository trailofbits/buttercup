# Buttercup Cyber Reasoning System (CRS)

**Buttercup** is a Cyber Reasoning System (CRS) developed by **Trail of Bits** for the **DARPA AIxCC (AI Cyber Challenge) competition**. It's a comprehensive automated vulnerability detection and patching system designed to compete in AI-driven cybersecurity challenges.

## Quick Start

Clone the repo with `--recurse-submodules` as some dependencies are submodules.

Choose your deployment method:

- **[Local Development](#local-development)** - Quick setup for development and testing
- **[Production AKS Deployment](#production-aks-deployment)** - Full production deployment on Azure Kubernetes Service

## Local Development

The fastest way to get started with the **Buttercup CRS** system for development and testing.

### Quick Setup (Recommended)

Use our automated setup script:

```bash
make setup-local
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

#### Manual Configuration

1. **Create configuration file:**

```bash
cp deployment/env.template deployment/env
```

2. **Configure the environment file** (`deployment/env`):

Look at the comments in the `deployment/env.template` for how to set variables.

### Start Local Development Environment

1. **Start the services:**

```bash
make deploy-local
```

2. **Verify deployment:**

```bash
make status
```

When the deployment is succesful, you should see something like

```shell
$ make status
----------PODS------------
NAME                                         READY   STATUS      RESTARTS   AGE
buttercup-build-bot-845f5b96d9-7t8bz         1/1     Running     0          5m58s
buttercup-build-bot-845f5b96d9-bfsq9         1/1     Running     0          5m58s
buttercup-build-bot-845f5b96d9-npns4         1/1     Running     0          5m58s
buttercup-build-bot-845f5b96d9-sv5fr         1/1     Running     0          5m58s
buttercup-coverage-bot-6749f57b9d-4gzfd      1/1     Running     0          5m58s
buttercup-dind-452s6                         1/1     Running     0          5m58s
buttercup-fuzzer-bot-74bc9b849d-2zkt6        1/1     Running     0          5m58s
buttercup-image-preloader-97nfb              0/1     Completed   0          5m58s
buttercup-litellm-5f87df944-2mq7z            1/1     Running     0          5m58s
buttercup-litellm-migrations-ljjcl           0/1     Completed   0          5m58s
buttercup-merger-bot-fz87v                   1/1     Running     0          5m58s
buttercup-patcher-7597c965b8-6968s           1/1     Running     0          5m58s
buttercup-postgresql-0                       1/1     Running     0          5m58s
buttercup-pov-reproducer-5f948bd7cc-45rgp    1/1     Running     0          5m58s
buttercup-program-model-67446b5cfc-24zfh     1/1     Running     0          5m58s
buttercup-redis-master-0                     1/1     Running     0          5m58s
buttercup-registry-cache-5787f86896-czt9b    1/1     Running     0          5m58s
buttercup-scheduler-7c49bf75c5-swqkb         1/1     Running     0          5m58s
buttercup-scratch-cleaner-hdt6z              1/1     Running     0          5m58s
buttercup-seed-gen-6fdb9c94c9-4xmrp          1/1     Running     0          5m57s
buttercup-task-downloader-54cd9fb577-g4lbg   1/1     Running     0          5m58s
buttercup-task-server-7d8cd7cf49-zkt69       1/1     Running     0          5m58s
buttercup-tracer-bot-5b9fb6c8b5-zcmxd        1/1     Running     0          5m58s
buttercup-ui-5dcf7dfb8-njglh                 1/1     Running     0          5m58s
----------SERVICES--------
NAME                       TYPE        CLUSTER-IP       EXTERNAL-IP   PORT(S)    AGE
buttercup-litellm          ClusterIP   10.96.88.226     <none>        4000/TCP   5m58s
buttercup-postgresql       ClusterIP   10.111.161.207   <none>        5432/TCP   5m58s
buttercup-postgresql-hl    ClusterIP   None             <none>        5432/TCP   5m58s
buttercup-redis-headless   ClusterIP   None             <none>        6379/TCP   5m58s
buttercup-redis-master     ClusterIP   10.108.61.77     <none>        6379/TCP   5m58s
buttercup-registry-cache   ClusterIP   10.103.80.241    <none>        443/TCP    5m58s
buttercup-task-server      ClusterIP   10.104.206.197   <none>        8000/TCP   5m58s
buttercup-ui               ClusterIP   10.106.49.166    <none>        1323/TCP   5m58s
```

3. **Submit the integration-test challenge to the CRS (for 30mins):**

```bash
make send-integration-task
```

**Alternative manual commands:**

```bash
# Start services manually
cd deployment && make up

# Port forward manually
kubectl port-forward -n crs service/buttercup-ui 31323:1323

# Test manually
./orchestrator/scripts/task_integration_test.sh
```

## Production AKS Deployment

> **⚠️ Notice:**  
> The following production deployment instructions have **not been fully tested**.  
> Please proceed with caution and verify each step in your environment.  
> If you encounter issues, consult the script comments and configuration files for troubleshooting.

Full production deployment of the **Buttercup CRS** on Azure Kubernetes Service with proper networking, monitoring, and scaling for the DARPA AIxCC competition.

### Quick Setup (Recommended)

Use our automated setup script:

```bash
make setup-azure
```

This script will check prerequisites, help create service principals, configure the environment, and validate your setup.

#### Manual Setup

If you prefer to set up manually, follow these steps:

##### Prerequisites

- Azure CLI installed and configured
- Terraform installed
- Active Azure subscription
- Access to competition Tailscale tailnet

##### Azure Setup

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

##### Production Configuration

1. **Configure environment file:**

```bash
cp deployment/env.template deployment/env
```

2. **Update `deployment/env` for production:**

Look at the comments in the `deployment/env.template` for how to set variables.
In particular, set `TF_VAR_*` variables, and `TAILSCALE_*` if used.

### Deploy to AKS

**Deploy the cluster and services:**

```bash
make deploy-azure
```

**Alternative manual command:**

```bash
cd deployment && make up
```

### Scaling and Management

- **Scale nodes:** Update `TF_VAR_usr_node_count` in your env file and run `make up`
- **View logs:** `kubectl logs -n crs <pod-name>`
- **Monitor resources:** `kubectl top pods -A`

## Run Challenges

```bash
kubectl port-forward -n crs service/buttercup-ui 31323:1323 &

./orchestrator/scripts/challenge.sh
```

## Cleanup

```bash
make undeploy
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
make setup-local          # Automated local development setup
make setup-azure          # Automated production AKS setup
make validate             # Validate current setup and configuration

# Deployment
make deploy               # Deploy to current environment (local or azure)
make deploy-local         # Deploy to local Minikube environment
make deploy-azure         # Deploy to production AKS environment

# Status
make status               # Check the status of the deployment

# Testing
make integration-task     # Run integration test task

# Development
make lint                 # Lint all Python code
make lint-component COMPONENT=orchestrator  # Lint specific component

# Cleanup
make undeploy             # Remove deployment and clean up resources
make clean-local          # Delete Minikube cluster and remove local config
```

### Running Tests

```bash
# Lint all Python code
make lint

# Lint specific component
make lint-component COMPONENT=orchestrator

# Run test task
make integration-task
```

**Alternative manual commands:**

```bash
# Lint Python code
just lint-python-all

# Run specific component tests
just lint-python orchestrator

# Test manually
./orchestrator/scripts/task_upstream_libpng.sh
./orchestrator/scripts/challenge.sh
```

### Docker Development

```bash
# Build and run with Docker Compose (only for local development and quick testing)
docker-compose up -d
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

- **Validate your setup:** `make validate` - Check if your environment is ready
- Check the [Quick Reference Guide](QUICK_REFERENCE.md) for common commands and troubleshooting
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
