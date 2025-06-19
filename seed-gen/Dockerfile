ARG BASE_IMAGE=ubuntu:24.04

FROM $BASE_IMAGE AS python_base
ARG PYTHON_VERSION=3.12
RUN DEBIAN_FRONTEND=noninteractive apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y python$PYTHON_VERSION python$PYTHON_VERSION-dev

FROM python_base AS runtime-base
RUN apt-get update \
    && apt-get install -y curl ripgrep codequery
RUN curl -fsSL https://get.docker.com | sh
RUN curl -fsSLO https://github.com/vmware-labs/webassembly-language-runtimes/releases/download/python%2F3.12.0%2B20231211-040d5a6/python-3.12.0.wasm

RUN rm -rf /var/lib/apt/lists/*

FROM python_base AS builder

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

FROM runtime-base AS cscope-builder
COPY --from=ghcr.io/aixcc-finals/buttercup-cscope:main /cscope /cscope
RUN DEBIAN_FRONTEND=noninteractive apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y autoconf gcc make bison flex libncurses-dev
RUN cd /cscope && autoreconf -i -s && ./configure && make && make install

FROM runtime-base AS runtime
RUN DEBIAN_FRONTEND=noninteractive apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y rsync libncurses-dev git
ENV PYTHON_WASM_BUILD_PATH="/python-3.12.0.wasm"
COPY --from=cscope-builder /usr/local/bin/cscope /usr/local/bin/cscope
COPY --from=builder /app/seed-gen/.venv /app/seed-gen/.venv
COPY common/container-entrypoint.sh /container-entrypoint.sh

WORKDIR /app/seed-gen
ENV PATH=/app/seed-gen/.venv/bin:$PATH

ENTRYPOINT ["/container-entrypoint.sh"]
