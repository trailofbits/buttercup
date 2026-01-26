ARG PYTHON_BASE=3.12-slim-bookworm

FROM python:${PYTHON_BASE} AS builder

COPY --from=ghcr.io/astral-sh/uv:0.5.20 /uv /uvx /bin/

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never \
    UV_PYTHON=python3.12

WORKDIR /app

# hadolint ignore=DL3003
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=common/uv.lock,target=common/uv.lock \
    --mount=type=bind,source=common/pyproject.toml,target=common/pyproject.toml \
    --mount=type=bind,source=orchestrator/uv.lock,target=orchestrator/uv.lock \
    --mount=type=bind,source=orchestrator/pyproject.toml,target=orchestrator/pyproject.toml \
    cd orchestrator && uv sync --frozen --no-install-project --no-editable

COPY common /app/common
COPY orchestrator /app/orchestrator

# hadolint ignore=DL3003
RUN --mount=type=cache,target=/root/.cache/uv \
    cd orchestrator && uv sync --frozen --no-editable


FROM python:${PYTHON_BASE} AS runtime

RUN DEBIAN_FRONTEND=noninteractive apt-get update && \
    apt-get install -y git git-lfs curl && \
    git lfs install && \
    rm -rf /var/lib/apt/lists/*

RUN for pkg in docker.io docker-doc docker-compose docker-compose-v2 podman-docker containerd runc; do DEBIAN_FRONTEND=noninteractive apt-get remove $pkg; done || true
RUN curl -fsSL https://get.docker.com -o get-docker.sh && sh get-docker.sh --version 29.0

COPY --from=builder --chown=app:app /app/orchestrator/.venv /app/orchestrator/.venv
WORKDIR /app/orchestrator
ENV PATH=/app/orchestrator/.venv/bin:$PATH

