# Buttercup Cyber Reasoning System (CRS)

**Buttercup** is a Cyber Reasoning System (CRS) developed by **Trail of Bits** for the **DARPA AIxCC (AI Cyber Challenge) competition**. It's a comprehensive automated vulnerability detection and patching system designed to compete in AI-driven cybersecurity challenges.

## System Requirements

### Minimum Requirements

- **CPU:** 8 cores
- **Memory:** 16 GB RAM (10 GB for basic system)
- **Storage:** 50 GB available disk space
- **Network:** Stable internet connection for downloading dependencies

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

When deployment is successful, you should see all pods in "Running" status.

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
./orchestrator/scripts/challenge.sh
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