#!/bin/bash -eux
# Build OSS-Fuzz base images locally for the CRS

# Change to the OSS-Fuzz directory
cd "$(dirname "$0")/../../../oss-fuzz" || exit 1

echo "Building OSS-Fuzz base images locally..."

# Build base-image first (no dependencies)
echo "Building base-image..."
docker build --platform linux/amd64 --pull -t local/oss-fuzz/base-image infra/base-images/base-image

# Build base-clang (depends on base-image)
echo "Building base-clang..."
# Create a temporary Dockerfile with local image reference and ARM64 arch
sed 's|gcr.io/oss-fuzz-base/base-image|local/oss-fuzz/base-image|g' \
    infra/base-images/base-clang/Dockerfile > infra/base-images/base-clang/Dockerfile.local
docker build --platform linux/amd64 --build-arg arch=x86_64 -t local/oss-fuzz/base-clang -f infra/base-images/base-clang/Dockerfile.local infra/base-images/base-clang
rm infra/base-images/base-clang/Dockerfile.local

# Build base-builder (depends on base-clang)
echo "Building base-builder..."
sed 's|gcr.io/oss-fuzz-base/base-clang|local/oss-fuzz/base-clang|g' \
    infra/base-images/base-builder/Dockerfile > infra/base-images/base-builder/Dockerfile.local
docker build --platform linux/amd64 -t local/oss-fuzz/base-builder -f infra/base-images/base-builder/Dockerfile.local infra/base-images/base-builder
rm infra/base-images/base-builder/Dockerfile.local

# Build base-runner (depends on base-image)
echo "Building base-runner..."
sed 's|gcr.io/oss-fuzz-base/base-image|local/oss-fuzz/base-image|g' \
    infra/base-images/base-runner/Dockerfile > infra/base-images/base-runner/Dockerfile.local
docker build --platform linux/amd64 -t local/oss-fuzz/base-runner -f infra/base-images/base-runner/Dockerfile.local infra/base-images/base-runner
rm infra/base-images/base-runner/Dockerfile.local

echo "✅ OSS-Fuzz base images built successfully!"
echo ""
echo "Built images:"
docker images | grep "local/oss-fuzz" | awk '{print "  - " $1 ":" $2}'