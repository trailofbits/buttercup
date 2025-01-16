FROM gcr.io/oss-fuzz-base/base-runner AS builder

RUN apt-get update && apt-get install -y python3.9 

COPY --from=ghcr.io/astral-sh/uv:0.5.20 /uv /uvx /bin/

ENV UV_LINK_MODE=copy
ENV UV_COMPILE_BYTECODE=1
ENV UV_PYTHON_DOWNLOADS=never
ENV UV_PYTHON=/usr/local/bin/python3.10

WORKDIR /fuzzer

# Install dependencies
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=common/uv.lock,target=/common/uv.lock \
    --mount=type=bind,source=common/pyproject.toml,target=/common/pyproject.toml \
    --mount=type=bind,source=common/README.md,target=/common/README.md \
    --mount=type=bind,source=fuzzer/uv.lock,target=/fuzzer/uv.lock \
    --mount=type=bind,source=fuzzer/pyproject.toml,target=/fuzzer/pyproject.toml \
    cd /fuzzer && uv sync --frozen --no-install-project --no-editable

ADD ./common /common
ADD ./fuzzer /fuzzer


RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-editable

FROM gcr.io/oss-fuzz-base/base-runner AS runtime

COPY --from=builder --chown=app:app /fuzzer/.venv /fuzzer/.venv

ENTRYPOINT ["/fuzzer/.venv/bin/python"]