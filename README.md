# Buttercup Cyber Reasoning System (CRS)

**Buttercup** is a Cyber Reasoning System (CRS) developed by **Trail of Bits** for the **DARPA AIxCC (AI Cyber Challenge)**. Buttercup finds and patches software vulnerabilities in open-source code repositories like [example-libpng](https://github.com/tob-challenges/example-libpng). It starts by running an AI/ML-assisted fuzzing campaign (built on oss-fuzz) for the program. When vulnerabilities are found, Buttercup analyzes them and uses a multi-agent AI-driven patcher to repair the vulnerability.

## System Requirements

### Minimum Requirements

- **CPU:** 8 cores
- **Memory:** 16 GB RAM
- **Storage:** 50 GB available disk space
- **Network:** Stable internet connection for downloading dependencies

**Note:** Buttercup uses third-party AI providers (LLMs from companies like OpenAI, Anthropic and Google), which cost money. Please ensure that you manage per-deployment costs by using the built-in LLM budget setting.

### Supported Systems
- **Linux x86_64** (fully supported)
- **ARM64** (partial support for upstream Google OSS-Fuzz projects)

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

# MacOS
brew install make curl git
```

### Supported Targets

Buttercup CRS works with:

- **C source code repositories** that are OSS-Fuzz compatible
- **Java source code repositories** that are OSS-Fuzz compatible
- Projects that build successfully and have existing fuzzing harnesses

## Quick Start

1. Clone the repository with submodules:

```bash
git clone --recurse-submodules <repository-url>
cd buttercup
```

2. Run automated setup (Recommended)

```bash
make setup-local
```

This script will install all dependencies, configure the environment, and guide you through the setup process.

**Note:** If you prefer manual setup, see the [Manual Setup Guide](MANUAL_SETUP.md).

3. Start Buttercup locally

```bash
make deploy-local
```

4. Verify local deployment:

```bash
make status
```

When a deployment is successful, you should see all pods in "Running" or "Completed" status.


5. Send Buttercup a simple task

**Note:** When tasked, Buttercup will start consuming third-party AI resources. 

This command will make Buttercup pull down an example repo [example-libpng](https://github.com/tob-challenges/example-libpng) with a known vulnerability. Buttercup will start fuzzing it to find and patch vulnerabilities. 

```bash
make send-libpng-task
```

6. Access Buttercup's web-based GUI

Run:

```bash
make web-ui
```

Then navigate to `http://localhost:31323` in your web browser.

In the GUI you can monitor active tasks and see when Buttercup finds bugs and generates patches for them.


7. Stop Buttercup

**Note:** This is an important step to ensure Buttercup shuts down and stops consuming third-party AI resources.

```bash
make undeploy
```

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