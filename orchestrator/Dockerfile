ARG PYTHON_BASE=3.12-slim-bookworm

FROM python:${PYTHON_BASE} AS builder

COPY --from=ghcr.io/astral-sh/uv:0.5.20 /uv /uvx /bin/

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never \
    UV_PYTHON=python3.12

WORKDIR /app

RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-install-project --no-editable

ADD . /app

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-editable

FROM python:${PYTHON_BASE} AS runtime-base

COPY --from=builder --chown=app:app /app/.venv /app/.venv
WORKDIR /app

FROM runtime-base AS development
# Don't copy source code in dev - will be mounted as volume
CMD ["/app/.venv/bin/uvicorn", "buttercup.orchestrator.task_server.server:app", "--host", "0.0.0.0"]

EXPOSE 8000

FROM runtime-base AS production
SHELL ["/bin/bash", "-c"]
CMD ["/app/.venv/bin/uvicorn", "buttercup.orchestrator.task_server.server:app", "--host", "0.0.0.0"]

EXPOSE 8000
