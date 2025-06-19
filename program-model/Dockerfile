ARG BASE_IMAGE=ubuntu:24.04@sha256:f8b860e4f9036f2694571770da292642eebcc4c2ea0c70a1a9244c2a1d436cd9

FROM $BASE_IMAGE AS base
RUN apt-get update && apt-get install -y software-properties-common
RUN add-apt-repository ppa:deadsnakes/ppa
RUN apt-get update && apt-get install -y python3.10 curl
RUN curl -fsSL https://get.docker.com | sh

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
    --mount=type=bind,source=program-model/uv.lock,target=/app/uv.lock \
    --mount=type=bind,source=program-model/pyproject.toml,target=/app/pyproject.toml \
    --mount=type=bind,source=program-model/README.md,target=/app/README.md \
    cd /app && uv sync --frozen --no-install-project --no-editable

COPY ./common /common
COPY ./program-model /app

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-editable

FROM base AS cscope-builder
COPY --from=ghcr.io/aixcc-finals/buttercup-cscope:main /cscope /cscope
RUN DEBIAN_FRONTEND=noninteractive apt-get update && apt-get install -y autoconf gcc make bison flex libncurses-dev
RUN cd /cscope && autoreconf -i -s && ./configure && make && make install

FROM base AS runtime
WORKDIR /app

RUN DEBIAN_FRONTEND=noninteractive apt-get update && \
    apt-get install -y codequery libncurses-dev git && \
    rm -rf /var/lib/apt/lists/*

COPY --from=cscope-builder /usr/local/bin/cscope /usr/local/bin/cscope
COPY --from=builder --chown=app:app /app/.venv /app/.venv
COPY common/container-entrypoint.sh /container-entrypoint.sh
ENV PATH=/app/.venv/bin:$PATH

ENTRYPOINT ["/container-entrypoint.sh"]
