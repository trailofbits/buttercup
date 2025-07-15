#!/bin/bash
# Build script optimized for ARM64/Apple Silicon

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Configuration
REGISTRY="${REGISTRY:-localhost:5000}"
TAG="${TAG:-latest}"
PLATFORM="${PLATFORM:-linux/arm64}"
BUILDKIT_CACHE_DIR="${BUILDKIT_CACHE_DIR:-/tmp/.buildx-cache}"

# Enable BuildKit and optimizations
export DOCKER_BUILDKIT=1
export BUILDKIT_INLINE_CACHE=1
export COMPOSE_DOCKER_CLI_BUILD=1

echo -e "${GREEN}Buttercup CRS ARM64 Build Script${NC}"
echo -e "${GREEN}================================${NC}"
echo ""

# Check if running on ARM64
ARCH=$(uname -m)
if [[ "$ARCH" == "arm64" ]] || [[ "$ARCH" == "aarch64" ]]; then
    echo -e "${GREEN}✓ Running on ARM64 architecture${NC}"
else
    echo -e "${YELLOW}⚠ Running on $ARCH - builds may be slower due to emulation${NC}"
fi

# Check Docker version
echo -e "\n${YELLOW}Docker Information:${NC}"
docker version --format 'Client: {{.Client.Version}} | Server: {{.Server.Version}} | Arch: {{.Server.Arch}}'

# Create buildx builder if it doesn't exist
BUILDER_NAME="buttercup-arm64"
if ! docker buildx inspect $BUILDER_NAME &> /dev/null; then
    echo -e "\n${YELLOW}Creating buildx builder: $BUILDER_NAME${NC}"
    docker buildx create --name $BUILDER_NAME \
        --driver docker-container \
        --driver-opt env.BUILDKIT_CACHE_MOUNT_MODE=max \
        --driver-opt env.BUILDKIT_INLINE_CACHE=1 \
        --use
    docker buildx inspect --bootstrap
else
    echo -e "\n${GREEN}✓ Using existing buildx builder: $BUILDER_NAME${NC}"
    docker buildx use $BUILDER_NAME
fi

# Create cache directory
mkdir -p "$BUILDKIT_CACHE_DIR"

# Build function
build_service() {
    local service=$1
    local dockerfile=$2
    local context_dir=${3:-.}
    
    echo -e "\n${YELLOW}Building $service for $PLATFORM...${NC}"
    
    # Build with caching and optimizations
    docker buildx build \
        --platform "$PLATFORM" \
        --cache-from "type=local,src=$BUILDKIT_CACHE_DIR/$service" \
        --cache-to "type=local,dest=$BUILDKIT_CACHE_DIR/$service,mode=max" \
        --cache-from "$REGISTRY/buttercup/$service:cache" \
        --build-arg BUILDKIT_INLINE_CACHE=1 \
        --tag "$REGISTRY/buttercup/$service:$TAG" \
        --tag "$REGISTRY/buttercup/$service:$TAG-arm64" \
        --file "$dockerfile" \
        --load \
        "$context_dir"
    
    if [ $? -eq 0 ]; then
        echo -e "${GREEN}✓ Successfully built $service${NC}"
    else
        echo -e "${RED}✗ Failed to build $service${NC}"
        return 1
    fi
}

# Build all services
echo -e "\n${YELLOW}Starting ARM64 optimized builds...${NC}"

# Change to project root
cd "$(dirname "$0")/../.."

# Build services in dependency order
services=(
    "orchestrator:orchestrator/Dockerfile"
    "program-model:program-model/Dockerfile"
    "patcher:patcher/Dockerfile"
    "seed-gen:seed-gen/Dockerfile"
)

failed_builds=()

for service_def in "${services[@]}"; do
    IFS=':' read -r service dockerfile <<< "$service_def"
    if ! build_service "$service" "$dockerfile"; then
        failed_builds+=("$service")
    fi
done

# Summary
echo -e "\n${YELLOW}Build Summary:${NC}"
echo -e "${GREEN}Platform: $PLATFORM${NC}"
echo -e "${GREEN}Registry: $REGISTRY${NC}"
echo -e "${GREEN}Tag: $TAG${NC}"

if [ ${#failed_builds[@]} -eq 0 ]; then
    echo -e "\n${GREEN}✓ All builds completed successfully!${NC}"
    
    echo -e "\n${YELLOW}To push images to registry:${NC}"
    echo "docker push $REGISTRY/buttercup/{orchestrator,program-model,patcher,seed-gen}:$TAG"
    
    echo -e "\n${YELLOW}To run locally:${NC}"
    echo "docker run --rm $REGISTRY/buttercup/orchestrator:$TAG"
else
    echo -e "\n${RED}✗ Failed builds: ${failed_builds[*]}${NC}"
    exit 1
fi

# Show image sizes
echo -e "\n${YELLOW}Image sizes:${NC}"
docker images --filter "reference=$REGISTRY/buttercup/*:$TAG" --format "table {{.Repository}}\t{{.Tag}}\t{{.Size}}"

# Cache statistics
echo -e "\n${YELLOW}Build cache usage:${NC}"
du -sh "$BUILDKIT_CACHE_DIR"/* 2>/dev/null || echo "No cache data yet"

# Optional: Test images
if [[ "${RUN_TESTS:-false}" == "true" ]]; then
    echo -e "\n${YELLOW}Running architecture tests...${NC}"
    for service_def in "${services[@]}"; do
        IFS=':' read -r service _ <<< "$service_def"
        echo -n "Testing $service: "
        arch=$(docker run --rm "$REGISTRY/buttercup/$service:$TAG" uname -m)
        if [[ "$arch" == "aarch64" ]] || [[ "$arch" == "arm64" ]]; then
            echo -e "${GREEN}✓ ARM64${NC}"
        else
            echo -e "${RED}✗ $arch${NC}"
        fi
    done
fi

echo -e "\n${GREEN}Build script completed!${NC}"