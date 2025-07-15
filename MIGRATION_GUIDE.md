# Buttercup CRS Migration Guide: Kubernetes to Docker Compose

This guide provides step-by-step instructions for migrating from the Kubernetes-based deployment to the simplified Docker Compose deployment for local development.

## Overview

The migration from Kubernetes to Docker Compose simplifies the deployment process and reduces infrastructure requirements while maintaining all core functionality. This is particularly beneficial for:
- Local development and testing
- Smaller teams without Kubernetes expertise
- Reduced infrastructure costs
- Faster iteration cycles

## Pre-Migration Checklist

Before starting the migration:

1. **Backup existing data**:
   - Export any critical challenge results
   - Save configuration files
   - Document any custom settings

2. **System requirements**:
   - macOS or Linux (Windows users should use WSL2)
   - Docker Desktop installed with at least 8GB RAM allocated
   - 50GB+ free disk space
   - Ports available: 6379, 8000, 8080, 1323, 31323

3. **API Keys ready**:
   - OpenAI API key
   - Anthropic API key (optional)
   - Any custom LLM provider keys

## Step 1: Backup Existing Data

### Export Kubernetes Data

```bash
# Export Redis data
kubectl exec -n crs redis-0 -- redis-cli BGSAVE
kubectl cp crs/redis-0:/data/dump.rdb ./backup/redis-dump.rdb

# Export task data
kubectl cp crs/scheduler-0:/crs_scratch ./backup/crs_scratch
kubectl cp crs/task-downloader-0:/tasks_storage ./backup/tasks_storage

# Export configurations
kubectl get configmap -n crs -o yaml > ./backup/configmaps.yaml
kubectl get secret -n crs -o yaml > ./backup/secrets.yaml
```

### Save Current Configuration

```bash
# Create backup directory
mkdir -p ./migration-backup

# Copy current environment configuration
cp deployment/env ./migration-backup/env.k8s

# Export Helm values
helm get values buttercup-crs -n crs > ./migration-backup/helm-values.yaml
```

## Step 2: Configuration Mapping

### Environment Variables

Map your Kubernetes configuration to Docker Compose format:

| Kubernetes (env/configmap) | Docker Compose (env.dev.compose) | Notes |
|---------------------------|----------------------------------|-------|
| `COMPETITION_API_URL` | `COMPETITION_API_URL` | Same format |
| `COMPETITION_AUTH_TOKEN` | `COMPETITION_AUTH_TOKEN` | Same format |
| `OPENAI_API_KEY` | `OPENAI_API_KEY` | Required for LLM operations |
| `ANTHROPIC_API_KEY` | `ANTHROPIC_API_KEY` | Optional, for Claude models |
| `REDIS_URL` | `REDIS_URL=redis://redis:6379` | Simplified for local |
| `TELEMETRY_ENABLED` | `TELEMETRY_ENABLED=false` | Disable for local dev |

### Service Mappings

| Kubernetes Service | Docker Compose Service | Changes |
|-------------------|------------------------|---------|
| redis-master/redis-replica | redis | Single Redis instance |
| task-server deployment | task-server | Same functionality |
| scheduler statefulset | scheduler | Converted to regular service |
| build-bot, fuzzer-bot, coverage-bot, tracer-bot | unified-fuzzer | Combined into single service |
| patcher deployment | patcher | Same functionality |
| program-model deployment | program-model | Same functionality |
| litellm deployment | litellm | Simplified configuration |

## Step 3: Stop Kubernetes Services

```bash
# Scale down all deployments
kubectl scale deployment --all --replicas=0 -n crs
kubectl scale statefulset --all --replicas=0 -n crs

# Or completely remove the namespace (if doing full migration)
kubectl delete namespace crs
```

## Step 4: Setup Docker Compose Environment

### 1. Configure Environment

```bash
# Copy the template
cp deployment/env.template env.dev.compose

# Edit the configuration
vim env.dev.compose
```

Key settings to configure:
```bash
# Core Services
REDIS_URL=redis://redis:6379
DOCKER_HOST=tcp://dind:2375

# LLM Configuration
OPENAI_API_KEY=your-openai-key
ANTHROPIC_API_KEY=your-anthropic-key

# Competition API (for local testing)
COMPETITION_API_URL=http://competition-api:31323
COMPETITION_AUTH_TOKEN=test_token

# Local paths
BUTTERCUP_DATA_PATH=./crs_scratch
BUTTERCUP_TASKS_PATH=./tasks_storage
```

### 2. Create Required Directories

```bash
# Create local data directories
mkdir -p ./crs_scratch
mkdir -p ./tasks_storage
mkdir -p ./node_data_storage

# Set proper permissions
chmod 755 ./crs_scratch ./tasks_storage ./node_data_storage
```

## Step 5: Restore Data

### Import Redis Data

```bash
# Start only Redis first
docker compose up -d redis

# Wait for Redis to be ready
sleep 5

# Import the backup
docker compose cp ./backup/redis-dump.rdb redis:/data/dump.rdb
docker compose exec redis redis-cli SHUTDOWN SAVE
docker compose restart redis
```

### Restore Task Data

```bash
# Copy backed up data
cp -r ./backup/crs_scratch/* ./crs_scratch/
cp -r ./backup/tasks_storage/* ./tasks_storage/
```

## Step 6: Start Docker Compose Services

```bash
# Start all services
docker compose up -d

# Or use the convenience script
./local-dev.sh up

# Check status
docker compose ps
docker compose logs --tail=50
```

## Step 7: Verify Migration

### Health Checks

```bash
# Check all services are running
./local-dev.sh status

# Test Redis connectivity
docker compose exec redis redis-cli ping

# Check API endpoints
curl http://localhost:8000/health
curl http://localhost:1323/
curl http://localhost:8080/health
```

### Run Test Task

```bash
# Submit a test task
./orchestrator/scripts/task_integration_test.sh

# Monitor logs
docker compose logs -f scheduler
```

## Troubleshooting

### Common Issues

1. **Port Conflicts**
   ```bash
   # Check what's using the ports
   lsof -i :6379
   lsof -i :8000
   lsof -i :8080
   
   # Solution: Stop conflicting services or change ports in compose.yaml
   ```

2. **Permission Issues**
   ```bash
   # Fix permissions on data directories
   sudo chown -R $(whoami):$(whoami) ./crs_scratch ./tasks_storage
   ```

3. **Service Dependencies**
   ```bash
   # If services fail to start in order
   docker compose down
   docker compose up -d redis litellm-db
   sleep 10
   docker compose up -d
   ```

4. **Memory Issues**
   - Increase Docker Desktop memory allocation
   - Reduce service replicas in compose.yaml
   - Disable unnecessary services

### Data Recovery

If data appears to be missing:

```bash
# Check volumes
docker volume ls
docker volume inspect buttercup_crs_scratch

# Manually restore from backup
docker compose down
cp -r ./migration-backup/crs_scratch/* ./crs_scratch/
docker compose up -d
```

## Rollback Procedure

If you need to rollback to Kubernetes:

1. **Stop Docker Compose**:
   ```bash
   docker compose down
   ```

2. **Restore Kubernetes deployment**:
   ```bash
   # Restore namespace
   kubectl create namespace crs
   
   # Apply saved configurations
   kubectl apply -f ./migration-backup/configmaps.yaml
   kubectl apply -f ./migration-backup/secrets.yaml
   
   # Deploy with Helm
   cd deployment
   make up
   ```

3. **Restore data to Kubernetes**:
   ```bash
   # Import Redis data
   kubectl cp ./backup/redis-dump.rdb crs/redis-0:/data/dump.rdb
   
   # Import task data
   kubectl cp ./crs_scratch crs/scheduler-0:/crs_scratch
   ```

## Post-Migration Optimization

### Performance Tuning

1. **Adjust Docker Resources**:
   - Open Docker Desktop settings
   - Increase CPU and Memory limits
   - Enable experimental features if needed

2. **Optimize compose.yaml**:
   ```yaml
   services:
     service-name:
       deploy:
         resources:
           limits:
             cpus: '2'
             memory: 4G
   ```

3. **Enable Docker BuildKit**:
   ```bash
   export DOCKER_BUILDKIT=1
   export COMPOSE_DOCKER_CLI_BUILD=1
   ```

### Development Workflow

1. **Use compose.override.yaml** for local customizations
2. **Mount source code** for live reloading during development
3. **Use profiles** to selectively start services

## Conclusion

The migration from Kubernetes to Docker Compose significantly simplifies the deployment while maintaining all core functionality. The new setup is ideal for:
- Local development
- Testing and debugging
- Small team deployments
- Resource-constrained environments

For production deployments requiring high availability and scaling, consider maintaining a Kubernetes option or using Docker Swarm as a middle ground.