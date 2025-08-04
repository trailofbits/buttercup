# Buttercup Cyber Reasoning System (CRS)

**Buttercup** is a Cyber Reasoning System (CRS) developed by **Trail of Bits** for the **DARPA AIxCC (AI Cyber Challenge) competition**. It's a comprehensive automated vulnerability detection and patching system designed to compete in AI-driven cybersecurity challenges.

## System Requirements

### Minimum Requirements

- **CPU:** 8 cores
- **Memory:** 16 GB RAM (10 GB for basic system)
- **Storage:** 50 GB available disk space
- **Network:** Stable internet connection for downloading dependencies

Note: Buttercup uses hosted LLMs, which cost money. Limit your per-deployment spend with the built-in LLM budget.

## Local Development

### Supported Systems
- **Linux x86_64** (fully supported)
- **ARM64** (only for upstream Google OSS-Fuzz projects, not for AIxCC challenges)

### Required System Packages

Before setup, ensure you have these packages installed:

```bash
# Ubuntu/Debian
sudo apt-get update
sudo apt-get install -y make curl git

# RHEL/CentOS/Fedora  
sudo yum install -y make curl git
# or
sudo dnf install -y make curl git
```

## Supported Targets

Buttercup CRS works with:

- **C source code repositories** that are OSS-Fuzz compatible
- **Java source code repositories** that are OSS-Fuzz compatible
- Projects that build successfully and have existing fuzzing harnesses

## Quick Start

Clone the repository with submodules:

```bash
git clone --recurse-submodules <repository-url>
cd buttercup
```

Choose your setup method:

### Automated Setup (Recommended)

```bash
make setup-local
```

This script will install all dependencies, configure the environment, and guide you through the setup process.

### Manual Setup

If you prefer manual setup, see the [Manual Setup Guide](MANUAL_SETUP.md).

## Starting the System

1. **Deploy locally:**

```bash
make deploy-local
```

2. **Verify deployment:**

```bash
make status
```

When deployment is successful, you should see all pods in "Running" status:

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
All CRS pods up and running.
```

3. **Send a simple challenge to the system:**

```bash
make send-libpng-task
```

## Production AKS Deployment

> **⚠️ Notice:**  
> The following production deployment instructions have **not been fully tested**.  
> Please proceed with caution and verify each step in your environment.  
> If you encounter issues, consult the script comments and configuration files for troubleshooting.

Full production deployment of the **Buttercup CRS** on Azure Kubernetes Service with proper networking, monitoring, and scaling for the DARPA AIxCC competition.

3. **Test the system:**

```bash
make send-libpng-task
```

## Using the GUI

The Buttercup CRS includes a web-based user interface for monitoring and managing the system.

### Accessing the GUI

1. **Start port forwarding:**

```bash
kubectl port-forward -n crs service/buttercup-ui 31323:1323 &
```

2. **Open in browser:**

Navigate to `http://localhost:31323` in your web browser.

### GUI Features

- **System Status:** View the status of all system components
- **Task Management:** Monitor active vulnerability discovery and patching tasks

## Creating and Running Challenges

### Running Challenges

To run challenges against the CRS:

```bash
# Start the UI port forwarding (if not already running)
kubectl port-forward -n crs service/buttercup-ui 31323:1323 &


# Run the challenge script
./orchestrator/scripts/challenge.py
```

### Pre-defined Challenges

Use the available pre-defined challenges:

```bash
make send-libpng-task
```

## Common Operations

### Viewing System Status

```bash
make status
```

### Accessing Logs

For system logs and monitoring, use SigNoz if configured, otherwise you can use kubectl:
=======
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
make send-libpng-task          # Run libpng test task

# Development
make lint                 # Lint all Python code
make lint-component COMPONENT=orchestrator  # Lint specific component

# Cleanup
make undeploy             # Remove deployment and clean up resources
make clean-local          # Delete Minikube cluster and remove local config
```

### Accessing Logs

For system logs and monitoring, use SigNoz if configured, otherwise you can use kubectl:

```bash
# View all pods
kubectl get pods -n crs

# View specific pod logs
kubectl logs -n crs <pod-name>

# Follow logs in real-time
kubectl logs -n crs <pod-name> -f
```

### Stopping the System

```bash
make undeploy
```

## Advanced Usage

### Production Deployment

For production deployment on Azure Kubernetes Service, see the [AKS Deployment Guide](AKS_DEPLOYMENT.md).

### Development

For development workflows and contributing guidelines, see [CONTRIBUTING.md](CONTRIBUTING.md).

### Troubleshooting

For troubleshooting help and common commands, see the [Quick Reference Guide](QUICK_REFERENCE.md).

## Architecture

The **Buttercup CRS** system consists of several components designed to work together for automated vulnerability detection and patching:

- **Orchestrator**: Coordinates the overall repair process and manages the workflow
- **Fuzzer**: Discovers vulnerabilities through intelligent fuzzing techniques
- **Patcher**: Generates and applies security patches to fix vulnerabilities
- **Program Model**: Analyzes code structure and semantics for better understanding
- **Seed Generator**: Creates targeted test cases for vulnerability discovery

## Additional Resources

- [Quick Reference Guide](QUICK_REFERENCE.md) - Common commands and troubleshooting
- [Manual Setup Guide](MANUAL_SETUP.md) - Detailed manual installation steps
- [AKS Deployment Guide](AKS_DEPLOYMENT.md) - Production deployment on Azure
- [Contributing Guidelines](CONTRIBUTING.md) - Development workflow and standards
- [Deployment Documentation](deployment/README.md) - Advanced deployment configuration