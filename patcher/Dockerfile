ARG BASE_IMAGE=ubuntu:24.04

FROM $BASE_IMAGE AS python_base
ARG PYTHON_VERSION=3.12
RUN DEBIAN_FRONTEND=noninteractive apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y python$PYTHON_VERSION python$PYTHON_VERSION-dev

FROM python_base AS runtime-base
RUN DEBIAN_FRONTEND=noninteractive apt-get update && apt-get install -y \
    curl \
    patch \
    codequery \
    rsync \
    libncurses-dev \
    && rm -rf /var/lib/apt/lists/*

RUN for pkg in docker.io docker-doc docker-compose docker-compose-v2 podman-docker containerd runc; do DEBIAN_FRONTEND=noninteractive apt-get remove $pkg; done || true
RUN curl -fsSL https://get.docker.com -o get-docker.sh && sh get-docker.sh --version 29.0


FROM python_base AS builder

COPY --from=ghcr.io/astral-sh/uv:0.5.20 /uv /uvx /bin/

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never \
    UV_PYTHON=python${PYTHON_VERSION}

WORKDIR /app

# hadolint ignore=DL3003
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=common/uv.lock,target=common/uv.lock \
    --mount=type=bind,source=common/pyproject.toml,target=common/pyproject.toml \
    --mount=type=bind,source=program-model/uv.lock,target=program-model/uv.lock \
    --mount=type=bind,source=program-model/pyproject.toml,target=program-model/pyproject.toml \
    --mount=type=bind,source=program-model/README.md,target=program-model/README.md \
    --mount=type=bind,source=patcher/uv.lock,target=patcher/uv.lock \
    --mount=type=bind,source=patcher/pyproject.toml,target=patcher/pyproject.toml \
    cd patcher && uv sync --frozen --no-install-project --no-editable

COPY common /app/common
COPY program-model /app/program-model
COPY patcher /app/patcher

# hadolint ignore=DL3003
RUN --mount=type=cache,target=/root/.cache/uv \
    cd patcher && uv sync --frozen --no-editable


FROM runtime-base AS cscope-builder
RUN DEBIAN_FRONTEND=noninteractive apt-get update && apt-get install -y autoconf gcc make bison flex libncurses-dev
COPY external/buttercup-cscope /cscope
# hadolint ignore=DL3003
RUN cd /cscope && autoreconf -i -s && ./configure && make && make install

FROM runtime-base AS runtime

RUN DEBIAN_FRONTEND=noninteractive apt-get update && \
    apt-get install -y codequery rsync git && \
    rm -rf /var/lib/apt/lists/*

COPY --from=builder --chown=app:app /app/patcher/.venv /app/patcher/.venv
COPY --from=cscope-builder /usr/local/bin/cscope /usr/local/bin/cscope
COPY common/container-entrypoint.sh /container-entrypoint.sh

WORKDIR /app/patcher
ENV PATH=/app/patcher/.venv/bin:$PATH

ENTRYPOINT ["/container-entrypoint.sh"]
