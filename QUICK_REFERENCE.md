# Quick Reference Guide

## Setup Commands

### Local Development
```bash
# Automated setup
./scripts/setup-local.sh

# Manual setup
cp deployment/env.template deployment/env
# Edit deployment/env with your API keys
cd deployment && make up
```

### Production AKS
```bash
# Automated setup
./scripts/setup-azure.sh

# Manual setup
az login --tenant <your-tenant>
# Create service principal and configure deployment/env
cd deployment && make up
```

## Common Commands

### Kubernetes Management
```bash
# View all resources
kubectl get pods -A
kubectl get services -A
kubectl get ingress -A

# View specific namespace
kubectl get pods -n crs
kubectl get services -n crs

# Port forwarding
kubectl port-forward -n crs service/buttercup-competition-api 31323:1323

# View logs
kubectl logs -n crs <pod-name>
kubectl logs -n crs -l app=scheduler --tail=-1 --prefix

# Debug pods
kubectl exec -it -n crs <pod-name> -- /bin/bash
```

### Testing
```bash
# Send test task
./orchestrator/scripts/task_crs.sh

# Send SARIF message
./orchestrator/scripts/send_sarif.sh <TASK-ID>

# Run unscored challenges
./orchestrator/scripts/challenge.sh
```

### Development
```bash
# Lint Python code
make lint-python-all
make lint-python COMPONENT=<component>

# Docker development
docker-compose up -d
docker-compose --profile fuzzer-test up
```

### Minikube
```bash
# Start/stop
minikube start --driver=docker
minikube stop
minikube delete

# Status
minikube status
minikube dashboard
```

### Azure AKS
```bash
# Get credentials
az aks get-credentials --name <cluster-name> --resource-group <resource-group>

# Scale cluster
# Update TF_VAR_usr_node_count in deployment/env
cd deployment && make up

# View cluster info
az aks show --name <cluster-name> --resource-group <resource-group>
```

## Configuration

## Troubleshooting

### Common Issues

#### Minikube Issues
```bash
# Reset minikube
minikube delete
minikube start --driver=docker

# Check status
minikube status
kubectl cluster-info
```

#### Docker Issues
```bash
# Permission issues
sudo usermod -aG docker $USER
# Log out and back in

# Check Docker daemon
sudo systemctl status docker
sudo systemctl start docker
```

#### Helm Issues
```bash
# Update repositories
helm repo update
helm dependency update deployment/k8s/

# Check chart
helm lint deployment/k8s/
```

#### Azure Issues
```bash
# Authentication
az login --tenant <your-tenant-here>
az account set --subscription <subscription-id>

# Check service principal
az ad sp list --display-name "ButtercupCRS*"
```

#### Kubernetes Issues
```bash
# Check cluster connectivity
kubectl cluster-info
kubectl get nodes

# Check pods
kubectl describe pod <pod-name> -n crs
kubectl logs <pod-name> -n crs --previous

# Check events
kubectl get events -n crs --sort-by='.lastTimestamp'
```

### Log Analysis

#### Check Patch Submission
```bash
kubectl logs -n crs -l app=scheduler --tail=-1 --prefix | grep "WAIT_PATCH_PASS -> SUBMIT_BUNDLE"
```

#### Check Competition API
```bash
kubectl logs -n crs -l app=competition-api --tail=-1 --prefix
```

#### Check Fuzzer
```bash
kubectl logs -n crs -l app=fuzzer --tail=-1 --prefix
```

## File Locations

### Configuration
- `deployment/env` - Main configuration file
- `deployment/env.template` - Configuration template
- `deployment/k8s/values-*.template` - Kubernetes value templates

### Scripts
- `scripts/setup-local.sh` - Local development setup
- `scripts/setup-azure.sh` - Production AKS setup
- `orchestrator/scripts/` - Testing and task scripts

### Documentation
- `README.md` - Main documentation
- `deployment/README.md` - Detailed deployment guide

## Support

- Check logs: `kubectl logs -n crs <pod-name>`
- View events: `kubectl get events -n crs`
- Debug pods: `kubectl exec -it -n crs <pod-name> -- /bin/bash`
- Monitor resources: `kubectl top pods -A` 
