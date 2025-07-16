ARG PYTHON_BASE=3.12-slim-bookworm
ARG TARGETPLATFORM
ARG BUILDPLATFORM

# Use buildplatform for builder stage for faster builds
FROM --platform=$BUILDPLATFORM python:${PYTHON_BASE} AS builder

# UV supports multi-arch out of the box
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

# First install dependencies only (without the project itself)
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=common/uv.lock,target=common/uv.lock \
    --mount=type=bind,source=common/pyproject.toml,target=common/pyproject.toml \
    --mount=type=bind,source=orchestrator/uv.lock,target=orchestrator/uv.lock \
    --mount=type=bind,source=orchestrator/pyproject.toml,target=orchestrator/pyproject.toml \
    cd orchestrator && uv sync --frozen --no-install-project --no-editable

ADD common /app/common
ADD orchestrator /app/orchestrator

RUN --mount=type=cache,target=/root/.cache/uv \
    cd orchestrator && uv sync --frozen --no-editable


# Use target platform for runtime stage
FROM --platform=$TARGETPLATFORM python:${PYTHON_BASE} AS runtime

# Install dependencies with cache cleanup
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    DEBIAN_FRONTEND=noninteractive apt-get update && \
    apt-get install -y --no-install-recommends \
    git \
    curl \
    ca-certificates && \
    rm -rf /var/lib/apt/lists/*

# Docker installation with architecture detection
RUN curl -fsSL https://get.docker.com | sh

COPY --from=builder --chown=app:app /app/orchestrator/.venv /app/orchestrator/.venv
WORKDIR /app/orchestrator

# Python optimizations for better performance
ENV PATH=/app/orchestrator/.venv/bin:$PATH \
    PYTHONPATH=/app/orchestrator/src:/app/common/src:$PYTHONPATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONOPTIMIZE=1

