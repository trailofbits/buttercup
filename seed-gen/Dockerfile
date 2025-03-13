ARG PYTHON_BASE=3.12-slim-bookworm

FROM python:${PYTHON_BASE} AS runtime-base
RUN apt-get update \
    && apt-get install -y curl ripgrep codequery
RUN curl -fsSL https://get.docker.com | sh
RUN curl -fsSLO https://github.com/vmware-labs/webassembly-language-runtimes/releases/download/python%2F3.12.0%2B20231211-040d5a6/python-3.12.0.wasm

RUN rm -rf /var/lib/apt/lists/*

FROM python:${PYTHON_BASE} AS builder

COPY --from=ghcr.io/astral-sh/uv:0.5.20 /uv /uvx /bin/

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
    --mount=type=bind,source=program-model/README.md,target=program-model/README.md \
    --mount=type=bind,source=seed-gen/uv.lock,target=seed-gen/uv.lock \
    --mount=type=bind,source=seed-gen/pyproject.toml,target=seed-gen/pyproject.toml \
    cd seed-gen && uv sync --frozen --no-install-project --no-editable

ADD common /app/common
ADD program-model /app/program-model
ADD seed-gen /app/seed-gen

RUN --mount=type=cache,target=/root/.cache/uv \
    cd seed-gen && uv sync --frozen --no-editable

FROM runtime-base AS runtime
ENV PYTHON_WASM_BUILD_PATH="/python-3.12.0.wasm"
COPY --from=builder /app/seed-gen/.venv /app/seed-gen/.venv
WORKDIR /app/seed-gen
ENV PATH=/app/seed-gen/.venv/bin:$PATH

