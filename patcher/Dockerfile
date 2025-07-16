ARG BASE_IMAGE=ubuntu:24.04
ARG TARGETPLATFORM
ARG BUILDPLATFORM

# Use target platform for base image
FROM --platform=$TARGETPLATFORM $BASE_IMAGE AS python_base
ARG PYTHON_VERSION=3.12
RUN DEBIAN_FRONTEND=noninteractive apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y python$PYTHON_VERSION python$PYTHON_VERSION-dev

FROM python_base AS runtime-base
# Combine apt operations with cache mounts for better performance
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    DEBIAN_FRONTEND=noninteractive apt-get update && \
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    curl \
    patch \
    codequery \
    rsync \
    cscope \
    libncurses-dev \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN curl -fsSL https://get.docker.com | sh


# Use build platform for faster compilation
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
    --mount=type=bind,source=patcher/uv.lock,target=patcher/uv.lock \
    --mount=type=bind,source=patcher/pyproject.toml,target=patcher/pyproject.toml \
    cd patcher && uv sync --frozen --no-install-project --no-editable

ADD common /app/common
ADD program-model /app/program-model
ADD patcher /app/patcher

RUN --mount=type=cache,target=/root/.cache/uv \
    cd patcher && uv sync --frozen --no-editable


# Build cscope for target architecture
FROM --platform=$TARGETPLATFORM runtime-base AS cscope-builder
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
# Custom cscope build removed - using standard package instead
# COPY external/aixcc-cscope /cscope
# Custom cscope build removed - using standard package instead
# # Optimize compilation for ARM64 if applicable
# RUN cd /cscope && \
#     autoreconf -i -s && \
#     ./configure && \
#     make -j$(nproc) && \
#     make install

FROM --platform=$TARGETPLATFORM runtime-base AS runtime

# Install runtime dependencies with cache
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    DEBIAN_FRONTEND=noninteractive apt-get update && \
    apt-get install -y --no-install-recommends \
    codequery \
    rsync \
    git && \
    rm -rf /var/lib/apt/lists/*

COPY --from=builder --chown=app:app /app/patcher/.venv /app/patcher/.venv
# Custom cscope build removed - using standard package instead
# COPY --from=cscope-builder /usr/local/bin/cscope /usr/local/bin/cscope
# COPY common/container-entrypoint.sh /container-entrypoint.sh  # File doesn't exist

WORKDIR /app/patcher

# Python optimizations
ENV PATH=/app/patcher/.venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONOPTIMIZE=1

# ENTRYPOINT ["/container-entrypoint.sh"]  # File doesn't exist
