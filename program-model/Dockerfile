ARG BASE_IMAGE=ubuntu:24.04@sha256:f8b860e4f9036f2694571770da292642eebcc4c2ea0c70a1a9244c2a1d436cd9
ARG TARGETPLATFORM
ARG BUILDPLATFORM

FROM --platform=$TARGETPLATFORM $BASE_IMAGE AS base
# Optimize apt operations with cache mounts
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && \
    apt-get install -y --no-install-recommends \
    software-properties-common \
    ca-certificates && \
    add-apt-repository ppa:deadsnakes/ppa && \
    apt-get update && \
    apt-get install -y --no-install-recommends \
    python3.10 \
    python3.10-dev \
    python3.10-distutils \
    curl && \
    rm -rf /var/lib/apt/lists/*

# Install Docker with architecture support
RUN curl -fsSL https://get.docker.com | sh

# Use build platform for compilation
FROM --platform=$BUILDPLATFORM base AS builder
# Install uv locally instead of copying from ghcr.io
RUN apt-get update && apt-get install -y curl && \
    curl -LsSf https://astral.sh/uv/0.5.20/install.sh | sh && \
    mv /root/.local/bin/uv /bin/uv && \
    mv /root/.local/bin/uvx /bin/uvx && \
    apt-get remove -y curl && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never \
    UV_PYTHON=python3.10

WORKDIR /app

RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=common/uv.lock,target=/common/uv.lock \
    --mount=type=bind,source=common/pyproject.toml,target=/common/pyproject.toml \
    --mount=type=bind,source=common/README.md,target=/common/README.md \
    --mount=type=bind,source=program-model/uv.lock,target=/app/uv.lock \
    --mount=type=bind,source=program-model/pyproject.toml,target=/app/pyproject.toml \
    --mount=type=bind,source=program-model/README.md,target=/app/README.md \
    cd /app && uv sync --frozen --no-install-project --no-editable

COPY ./common /common
COPY ./program-model /app

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-editable

# Build cscope for target architecture
FROM --platform=$TARGETPLATFORM base AS cscope-builder
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    DEBIAN_FRONTEND=noninteractive apt-get update && \
    apt-get install -y --no-install-recommends \
    autoconf \
    gcc \
    g++ \
    make \
    bison \
    flex \
    libncurses-dev && \
    rm -rf /var/lib/apt/lists/*
COPY external/aixcc-cscope /cscope
RUN cd /cscope && \
    autoreconf -i -s && \
    ./configure && \
    make -j$(nproc) && \
    make install

FROM --platform=$TARGETPLATFORM base AS runtime
WORKDIR /app

# Install runtime dependencies
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    DEBIAN_FRONTEND=noninteractive apt-get update && \
    apt-get install -y --no-install-recommends \
    codequery \
    libncurses-dev \
    git && \
    rm -rf /var/lib/apt/lists/*

COPY --from=cscope-builder /usr/local/bin/cscope /usr/local/bin/cscope
COPY --from=builder --chown=app:app /app/.venv /app/.venv
COPY common/container-entrypoint.sh /container-entrypoint.sh

# Python optimizations
ENV PATH=/app/.venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONOPTIMIZE=1

ENTRYPOINT ["/container-entrypoint.sh"]
