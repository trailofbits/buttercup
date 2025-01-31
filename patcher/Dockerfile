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
    --mount=type=bind,source=patcher/uv.lock,target=patcher/uv.lock \
    --mount=type=bind,source=patcher/pyproject.toml,target=patcher/pyproject.toml \
    cd patcher && uv sync --frozen --no-install-project --no-editable

ADD common /app/common
ADD patcher /app/patcher

RUN --mount=type=cache,target=/root/.cache/uv \
    cd patcher && uv sync --frozen --no-editable


FROM python:${PYTHON_BASE} AS runtime

COPY --from=builder --chown=app:app /app/patcher/.venv /app/patcher/.venv
WORKDIR /app/patcher
ENV PATH=/app/patcher/.venv/bin:$PATH

