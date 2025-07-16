ARG BASE_IMAGE=ubuntu:24.04
ARG TARGETPLATFORM
ARG BUILDPLATFORM
ARG TARGETARCH

FROM --platform=$TARGETPLATFORM $BASE_IMAGE AS python_base
ARG PYTHON_VERSION=3.12
RUN DEBIAN_FRONTEND=noninteractive apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y python$PYTHON_VERSION python$PYTHON_VERSION-dev

FROM python_base AS runtime-base
# Install dependencies with cache optimization
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && \
    apt-get install -y --no-install-recommends \
    curl \
    ripgrep \
    codequery \
    ca-certificates && \
    rm -rf /var/lib/apt/lists/*

# Install Docker
RUN curl -fsSL https://get.docker.com | sh

# Download architecture-specific WASM runtime
RUN ARCH=$(dpkg --print-architecture) && \
    echo "Detected architecture: $ARCH" && \
    if [ "$ARCH" = "arm64" ] || [ "$ARCH" = "aarch64" ]; then \
        echo "Note: ARM64 WASM runtime may need different URL"; \
    fi && \
    curl -fsSLO https://github.com/vmware-labs/webassembly-language-runtimes/releases/download/python%2F3.12.0%2B20231211-040d5a6/python-3.12.0.wasm

# Use build platform for faster builds
FROM --platform=$BUILDPLATFORM python_base AS builder

# Install uv locally instead of copying from ghcr.io
RUN apt-get update && apt-get install -y curl && \
    curl -LsSf https://astral.sh/uv/0.5.20/install.sh | sh && \
    mv /root/.local/bin/uv /bin/uv && \
    mv /root/.local/bin/uvx /bin/uvx && \
    apt-get remove -y curl && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never \
    UV_PYTHON=python3.12

WORKDIR /app

RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=common/uv.lock,target=common/uv.lock \
    --mount=type=bind,source=common/pyproject.toml,target=common/pyproject.toml \
    --mount=type=bind,source=program-model/uv.lock,target=program-model/uv.lock \
    --mount=type=bind,source=program-model/pyproject.toml,target=program-model/pyproject.toml \
    --mount=type=bind,source=seed-gen/uv.lock,target=seed-gen/uv.lock \
    --mount=type=bind,source=seed-gen/pyproject.toml,target=seed-gen/pyproject.toml \
    cd seed-gen && uv sync --frozen --no-install-project --no-editable

ADD common /app/common
ADD program-model /app/program-model
ADD seed-gen /app/seed-gen

RUN --mount=type=cache,target=/root/.cache/uv \
    cd seed-gen && uv sync --frozen --no-editable

# Build cscope for target architecture
FROM --platform=$TARGETPLATFORM runtime-base AS cscope-builder
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    DEBIAN_FRONTEND=noninteractive apt-get update && \
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    autoconf \
    gcc \
    g++ \
    make \
    bison \
    flex \
    libncurses-dev \
    cscope && \
    rm -rf /var/lib/apt/lists/*
# Custom cscope build removed - using standard package instead
# COPY external/aixcc-cscope /cscope
# RUN cd /cscope && \
#     autoreconf -i -s && \
#     ./configure && \
#     make -j$(nproc) && \
#     make install

FROM --platform=$TARGETPLATFORM runtime-base AS runtime
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    DEBIAN_FRONTEND=noninteractive apt-get update && \
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    rsync \
    libncurses-dev \
    git \
    cscope && \
    rm -rf /var/lib/apt/lists/*
ENV PYTHON_WASM_BUILD_PATH="/python-3.12.0.wasm"
# COPY --from=cscope-builder /usr/local/bin/cscope /usr/local/bin/cscope # Using system package instead
COPY --from=builder /app/seed-gen/.venv /app/seed-gen/.venv
# COPY common/container-entrypoint.sh /container-entrypoint.sh # File doesn't exist

WORKDIR /app/seed-gen

# Python optimizations
ENV PATH=/app/seed-gen/.venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONOPTIMIZE=1

# ENTRYPOINT ["/container-entrypoint.sh"] # File doesn't exist
