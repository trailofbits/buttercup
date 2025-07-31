ARG BASE_IMAGE=gcr.io/oss-fuzz-base/base-runner

FROM $BASE_IMAGE AS base-image

COPY --from=ghcr.io/astral-sh/uv:0.5.20 /uv /uvx /bin/

ENV UV_LINK_MODE=copy
ENV UV_COMPILE_BYTECODE=1
ENV UV_PYTHON_DOWNLOADS=manual

RUN uv python install python3.10

FROM base-image AS runner-base
RUN apt-get update
# TODO(Ian): maybe we should have a different base image for the builder
RUN apt-get install ca-certificates curl
RUN install -m 0755 -d /etc/apt/keyrings
RUN curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
RUN chmod a+r /etc/apt/keyrings/docker.asc

# Add the repository to Apt sources:
RUN echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo "${UBUNTU_CODENAME:-$VERSION_CODENAME}") stable" | \
  tee /etc/apt/sources.list.d/docker.list > /dev/null
RUN apt-get update
RUN apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

FROM base-image AS builder

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

FROM runner-base AS runtime

RUN DEBIAN_FRONTEND=noninteractive apt-get update && \
    apt-get install -y git \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder --chown=app:app /fuzzer/.venv /fuzzer/.venv
COPY common/container-entrypoint.sh /container-entrypoint.sh
ENV PATH=/fuzzer/.venv/bin:$PATH

ENTRYPOINT ["/container-entrypoint.sh"]
