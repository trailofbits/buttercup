ARG BASE_IMAGE=gcr.io/oss-fuzz-base/base-runner

FROM $BASE_IMAGE AS base-image

COPY --from=ghcr.io/astral-sh/uv:0.5.20 /uv /uvx /bin/

ENV UV_LINK_MODE=copy
ENV UV_COMPILE_BYTECODE=1
ENV UV_PYTHON_DOWNLOADS=manual

RUN uv python install python3.12

FROM base-image AS runner-base
RUN apt-get update

FROM base-image AS builder

WORKDIR /fuzzer_runner

# Install dependencies
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=common/uv.lock,target=/common/uv.lock \
    --mount=type=bind,source=common/pyproject.toml,target=/common/pyproject.toml \
    --mount=type=bind,source=common/README.md,target=/common/README.md \
    --mount=type=bind,source=fuzzer_runner/uv.lock,target=/fuzzer_runner/uv.lock \
    --mount=type=bind,source=fuzzer_runner/pyproject.toml,target=/fuzzer_runner/pyproject.toml \
    cd /fuzzer_runner && uv sync --frozen --no-install-project --no-editable

ADD ./common /common
ADD ./fuzzer_runner /fuzzer_runner


RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-editable

FROM runner-base AS runtime

RUN DEBIAN_FRONTEND=noninteractive apt-get update && \
    apt-get install -y git \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder --chown=app:app /fuzzer_runner/.venv /fuzzer_runner/.venv
ENV PATH=/fuzzer_runner/.venv/bin:$PATH
