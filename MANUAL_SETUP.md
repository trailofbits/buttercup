# Manual Setup Guide

This guide provides detailed manual setup instructions for the Buttercup CRS system. If you prefer automated setup, use `make setup-local` instead.

## Prerequisites

Before starting manual setup, ensure you have the following dependencies installed:

### System Packages

```bash
# Ubuntu/Debian
sudo apt-get update
sudo apt-get install -y make curl git

# RHEL/CentOS/Fedora  
sudo yum install -y make curl git
# or
sudo dnf install -y make curl git

# MacOS
brew install make curl git
```

### Docker

```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
# Log out and back in for group changes to take effect
```

### kubectl

```bash
curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"
sudo install -o root -g root -m 0755 kubectl /usr/local/bin/kubectl
```

### Helm

```bash
curl https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash
```

### Minikube

```bash
curl -LO https://storage.googleapis.com/minikube/releases/latest/minikube-linux-amd64
sudo install minikube-linux-amd64 /usr/local/bin/minikube
```

### Git LFS (for some tests)

```bash
sudo apt-get install git-lfs
git lfs install
```

## Manual Configuration

1. **Create configuration file:**

```bash
cp deployment/env.template deployment/env
```

2. **Configure the environment file** (`deployment/env`):

Look at the comments in the `deployment/env.template` for how to set variables.

## Start Services Manually

```bash
# Start services manually
cd deployment && make up

# Port forward manually
kubectl port-forward -n crs service/buttercup-ui 31323:1323

# Test manually
./orchestrator/scripts/task_crs.sh
```

## Verification

After setup, verify your installation by running:

```bash
make status
```

## Troubleshooting

### Common Manual Setup Issues

1. **Docker permission issues:**

```bash
sudo usermod -aG docker $USER
# Log out and back in
```

2. **Minikube won't start:**

```bash
minikube delete
minikube start --driver=docker
```

3. **Helm chart issues:**

```bash
helm repo update
helm dependency update deployment/k8s/
```

For additional troubleshooting, see the [Quick Reference Guide](QUICK_REFERENCE.md).