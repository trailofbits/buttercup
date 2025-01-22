ARG BASE_IMAGE=ubuntu:20.04@sha256:4a45212e9518f35983a976eead0de5eecc555a2f047134e9dd2cfc589076a00d

FROM $BASE_IMAGE AS base
RUN apt-get update && apt-get install -y software-properties-common
RUN add-apt-repository ppa:deadsnakes/ppa
RUN apt-get update && apt-get install -y python3.10

FROM base AS builder
COPY --from=ghcr.io/astral-sh/uv:0.5.20 /uv /uvx /bin/

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never \
    UV_PYTHON=python3.10

WORKDIR /app

RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=common/uv.lock,target=/common/uv.lock \
    --mount=type=bind,source=common/pyproject.toml,target=/common/pyproject.toml \
    --mount=type=bind,source=common/README.md,target=/common/README.md \    
    --mount=type=bind,source=program-model/uv.lock,target=uv.lock \
    --mount=type=bind,source=program-model/pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-install-project --no-editable

ADD ./common /common

COPY program-model/src /app/src
COPY program-model/pyproject.toml /app/pyproject.toml
COPY program-model/uv.lock /app/uv.lock
COPY program-model/scripts /app/scripts

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-editable


FROM base AS runtime
COPY --from=builder --chown=app:app /app/scripts /app/scripts
RUN tar -xvf /app/scripts/gzs/kythe-v0.0.67.tar.gz
COPY --from=builder --chown=app:app /app/.venv /app/.venv
WORKDIR /app

ENTRYPOINT ["/app/.venv/bin/python"]