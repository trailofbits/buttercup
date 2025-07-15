# Buttercup Local Deployment Plan for macOS

## Executive Summary

This plan outlines the conversion of Buttercup from a Kubernetes-based cloud deployment to a simplified Docker Compose setup that can run on a single MacBook Pro. The goal is to maintain full functionality while reducing complexity and resource requirements.

## Key Technical Decisions

### 1. Infrastructure Simplification
- **Remove all Kubernetes components** (Helm charts, operators, storage classes)
- **Keep Docker Compose** as the primary orchestration tool
- **Eliminate cloud-specific services** (Azure storage, Tailscale, registry cache)
- **Use local volumes** instead of persistent volume claims

### 2. Component Consolidation

#### Merge Fuzzer Components
Combine all fuzzing bots into a single service:
- build-bot, fuzzer-bot, coverage-bot, tracer-bot → **unified-fuzzer-service**
- Benefits: Reduced inter-service communication, shared resources, simplified deployment

#### Merge Utility Services
- scratch-cleaner + merger-bot → Background tasks in scheduler
- pov-reproducer → Integrate into scheduler workflow

#### Final Component List
1. **redis** - Message broker (unchanged)
2. **litellm + postgres** - LLM proxy (unchanged)
3. **orchestrator** - Already bundles task-server, downloader, scheduler, ui
4. **unified-fuzzer** - All fuzzing capabilities
5. **program-model** - Code analysis
6. **patcher** - Automated patching
7. **seed-gen** - Test generation
8. **dind** - Docker-in-Docker for isolated execution
9. **mock-competition-api** - Local testing endpoint

### 3. Resource Optimization

#### Memory Requirements (Estimated Total: 16-20GB)
- Redis: 1GB
- LiteLLM + PostgreSQL: 3GB
- Orchestrator: 2GB
- Unified Fuzzer: 4-6GB
- Program Model: 1GB
- Patcher: 1GB
- Seed-gen: 1GB
- DinD: 2GB
- Buffer: 1-3GB

#### Storage Requirements (50GB total)
- Docker images: 20GB
- crs_scratch: 10GB
- tasks_storage: 5GB
- Database storage: 5GB
- OS and buffer: 10GB

### 4. External Dependencies

#### Required (Keep)
- One LLM API key (OpenAI/Anthropic/Azure)
- Internet for LLM API calls
- Docker Desktop for Mac with increased resources

#### Optional (Remove/Disable)
- Langfuse monitoring
- OpenTelemetry export
- JanusGraph/Cassandra (GraphDB)
- External container registries (use local builds)

## Implementation Steps

### Phase 1: Environment Preparation
1. Clean up deployment directory
   - Remove all k8s/ subdirectory
   - Remove Terraform files (*.tf)
   - Remove Azure/cloud-specific scripts
   - Keep only compose.yaml and environment templates

2. Simplify Docker Compose
   - Remove service profiles not needed for local dev
   - Set all replica counts to 1
   - Remove resource limits (let Docker manage)
   - Use host networking where beneficial

3. Create local-specific configuration
   - Create env.local based on env.dev.compose
   - Disable telemetry exports
   - Set local paths for volumes
   - Configure minimal LLM endpoints

### Phase 2: Component Consolidation

1. Create unified fuzzer service
   - Merge fuzzer bot implementations into single Python package
   - Use threading/multiprocessing instead of separate containers
   - Maintain Redis interface for external communication
   - Internal communication via queues/channels

2. Integrate utility services
   - Add scratch cleaning to scheduler as periodic task
   - Move POV reproduction into scheduler workflow
   - Remove separate service definitions

3. Update Docker images
   - Create new Dockerfile for unified-fuzzer
   - Remove individual fuzzer Dockerfiles
   - Optimize base images for macOS/ARM64

### Phase 3: Dependency Simplification

1. Make external services optional
   - Add feature flags for GraphDB
   - Mock LLM responses for testing
   - Provide offline mode with cached data

2. Optimize storage
   - Use Docker volumes instead of bind mounts where possible
   - Implement aggressive cleanup policies
   - Share build caches between services

3. Network simplification
   - Use single Docker network
   - Remove ingress/load balancer configs
   - Direct port mappings for UI access

### Phase 4: Developer Experience

1. Create helper scripts
   - `start.sh` - Start all services with proper order
   - `stop.sh` - Clean shutdown
   - `reset.sh` - Clean all data and restart
   - `logs.sh` - Aggregate logs from all services

2. Add development modes
   - Fast startup with minimal services
   - Debug mode with verbose logging
   - Test mode with mocked dependencies

3. Documentation
   - Quick start guide for macOS
   - Troubleshooting common issues
   - Performance tuning guide

## Technical Considerations

### macOS-Specific Optimizations
1. Use native ARM64 images where available
2. Configure Docker Desktop with:
   - CPUs: 8+ cores
   - Memory: 20GB+
   - Disk: 60GB+
   - Enable VirtioFS for better I/O

### Security Considerations
1. DinD requires privileged mode - ensure Docker Desktop security settings allow this
2. Store API keys in .env file (git-ignored)
3. Use local-only network bindings (127.0.0.1)

### Performance Optimizations
1. Disable unnecessary logging in production mode
2. Use Redis persistence only for critical data
3. Implement local caching for LLM responses
4. Batch operations where possible

## Migration Path

### From Kubernetes to Docker Compose
1. Export any critical data from cloud deployment
2. Stop Kubernetes services
3. Deploy locally with Docker Compose
4. Validate functionality with test challenges
5. Remove cloud resources

### Rollback Plan
- Keep original k8s/ directory in separate branch
- Document any schema/data changes
- Test backups of critical data

## Success Metrics
- All components start successfully on MacBook Pro (M1/M2/M3)
- Memory usage stays under 20GB during normal operation
- Can process simple challenges end-to-end
- Development iteration time improved
- No dependency on cloud services for basic operation

## Future Enhancements
1. Add Kubernetes manifests generated from Docker Compose for hybrid deployments
2. Create development VM/container for non-macOS users
3. Implement distributed mode for scaling beyond single machine
4. Add resource monitoring dashboard