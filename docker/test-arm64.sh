#!/bin/bash
# Test script to verify ARM64 optimizations

set -euo pipefail

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${GREEN}Testing ARM64 Docker Optimizations${NC}"
echo -e "${GREEN}===================================${NC}\n"

# Test 1: Check Docker architecture
echo -e "${YELLOW}Test 1: Docker Architecture${NC}"
DOCKER_ARCH=$(docker version --format '{{.Server.Arch}}')
echo "Docker Server Architecture: $DOCKER_ARCH"
if [[ "$DOCKER_ARCH" == "arm64" ]] || [[ "$DOCKER_ARCH" == "aarch64" ]]; then
    echo -e "${GREEN}✓ Docker is running on ARM64${NC}\n"
else
    echo -e "${YELLOW}⚠ Docker is running on $DOCKER_ARCH${NC}\n"
fi

# Test 2: Check BuildKit
echo -e "${YELLOW}Test 2: BuildKit Status${NC}"
if [[ "${DOCKER_BUILDKIT:-0}" == "1" ]]; then
    echo -e "${GREEN}✓ BuildKit is enabled${NC}\n"
else
    echo -e "${RED}✗ BuildKit is not enabled${NC}"
    echo -e "  Run: export DOCKER_BUILDKIT=1\n"
fi

# Test 3: Check buildx
echo -e "${YELLOW}Test 3: Docker Buildx${NC}"
if docker buildx version &>/dev/null; then
    echo -e "${GREEN}✓ Docker buildx is available${NC}"
    docker buildx version
    echo ""
else
    echo -e "${RED}✗ Docker buildx not found${NC}\n"
fi

# Test 4: Test multi-platform build
echo -e "${YELLOW}Test 4: Multi-platform Build Test${NC}"
TMP_DIR=$(mktemp -d)
cat > "$TMP_DIR/Dockerfile" << EOF
FROM --platform=\$TARGETPLATFORM alpine:latest
ARG TARGETPLATFORM
ARG BUILDPLATFORM
RUN echo "Built on \$BUILDPLATFORM for \$TARGETPLATFORM"
CMD ["uname", "-m"]
EOF

if docker buildx build --platform linux/arm64 -t test-arm64:latest "$TMP_DIR" &>/dev/null; then
    echo -e "${GREEN}✓ Multi-platform build successful${NC}"
    
    # Test the image
    ARCH=$(docker run --rm test-arm64:latest 2>/dev/null)
    if [[ "$ARCH" == "aarch64" ]] || [[ "$ARCH" == "arm64" ]]; then
        echo -e "${GREEN}✓ Image runs as ARM64: $ARCH${NC}\n"
    else
        echo -e "${RED}✗ Image architecture mismatch: $ARCH${NC}\n"
    fi
    
    docker rmi test-arm64:latest &>/dev/null
else
    echo -e "${RED}✗ Multi-platform build failed${NC}\n"
fi
rm -rf "$TMP_DIR"

# Test 5: Check for Rosetta
echo -e "${YELLOW}Test 5: Rosetta 2 Support${NC}"
if docker run --rm --platform linux/amd64 alpine:latest echo "x86_64 emulation works" &>/dev/null; then
    echo -e "${GREEN}✓ Rosetta 2 emulation is working${NC}\n"
else
    echo -e "${YELLOW}⚠ Rosetta 2 may not be enabled${NC}"
    echo -e "  Enable in Docker Desktop settings\n"
fi

# Test 6: Check Docker Desktop resources
echo -e "${YELLOW}Test 6: Docker Resources${NC}"
if [[ "$OSTYPE" == "darwin"* ]]; then
    DOCKER_MEM=$(docker system info 2>/dev/null | grep "Total Memory" | awk '{print $3}')
    DOCKER_CPUS=$(docker system info 2>/dev/null | grep "CPUs:" | awk '{print $2}')
    
    echo "Docker Memory: ${DOCKER_MEM:-Unknown}"
    echo "Docker CPUs: ${DOCKER_CPUS:-Unknown}"
    
    if [[ -n "$DOCKER_MEM" ]]; then
        MEM_GB=$(echo "$DOCKER_MEM" | sed 's/GiB//')
        if (( $(echo "$MEM_GB >= 6" | bc -l) )); then
            echo -e "${GREEN}✓ Sufficient memory allocated${NC}\n"
        else
            echo -e "${YELLOW}⚠ Consider increasing Docker memory${NC}\n"
        fi
    fi
else
    echo -e "Not running on macOS, skipping resource check\n"
fi

# Test 7: Test optimized Dockerfile features
echo -e "${YELLOW}Test 7: Dockerfile Optimization Features${NC}"

# Check if Dockerfiles have platform support
DOCKERFILES=(
    "orchestrator/Dockerfile"
    "patcher/Dockerfile"
    "program-model/Dockerfile"
    "seed-gen/Dockerfile"
)

cd "$(dirname "$0")/.."

for dockerfile in "${DOCKERFILES[@]}"; do
    if [[ -f "$dockerfile" ]]; then
        echo -n "Checking $dockerfile: "
        
        has_platform=$(grep -c "platform=" "$dockerfile" || true)
        has_buildkit=$(grep -c "mount=type=cache" "$dockerfile" || true)
        has_args=$(grep -c "ARG.*PLATFORM" "$dockerfile" || true)
        
        if [[ $has_platform -gt 0 ]] && [[ $has_buildkit -gt 0 ]] && [[ $has_args -gt 0 ]]; then
            echo -e "${GREEN}✓ Fully optimized${NC}"
        elif [[ $has_platform -gt 0 ]] || [[ $has_buildkit -gt 0 ]] || [[ $has_args -gt 0 ]]; then
            echo -e "${YELLOW}⚠ Partially optimized${NC}"
        else
            echo -e "${RED}✗ Not optimized${NC}"
        fi
    else
        echo -e "$dockerfile: ${RED}Not found${NC}"
    fi
done

echo -e "\n${GREEN}Test Summary${NC}"
echo -e "${GREEN}============${NC}"
echo "• Docker Architecture: $DOCKER_ARCH"
echo "• BuildKit: ${DOCKER_BUILDKIT:-Not set}"
echo "• Platform: $(uname -m)"
echo "• OS: $(uname -s)"

echo -e "\n${YELLOW}Recommendations:${NC}"
echo "1. Use ./docker/build-arm64.sh for optimized builds"
echo "2. Enable BuildKit: export DOCKER_BUILDKIT=1"
echo "3. Configure Docker Desktop with ./docker/optimization/macos-docker-config.md"
echo "4. Use docker-compose.arm64.yml for running services"

echo -e "\n${GREEN}Testing complete!${NC}"