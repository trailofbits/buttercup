ARG PYTHON_BASE=3.12-slim-bookworm

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
    --mount=type=bind,source=seed-gen/uv.lock,target=seed-gen/uv.lock \
    --mount=type=bind,source=seed-gen/pyproject.toml,target=seed-gen/pyproject.toml \
    cd seed-gen && uv sync --frozen --no-install-project --no-editable

ADD common /app/common
ADD seed-gen /app/seed-gen

RUN --mount=type=cache,target=/root/.cache/uv \
    cd seed-gen && uv sync --frozen --no-editable


FROM python:${PYTHON_BASE} AS runtime

COPY --from=builder /app/seed-gen/.venv /app/seed-gen/.venv
WORKDIR /app/seed-gen
ENV PATH=/app/seed-gen/.venv/bin:$PATH

