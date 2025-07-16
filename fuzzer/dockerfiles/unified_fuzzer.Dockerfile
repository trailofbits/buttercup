FROM ubuntu:24.04 AS base-image

# Install basic dependencies
RUN apt-get update && apt-get install -y \
    curl \
    ca-certificates \
    git \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install uv locally instead of copying from ghcr.io
RUN curl -LsSf https://astral.sh/uv/0.5.20/install.sh | sh

# Add uv to PATH
ENV PATH="/root/.local/bin:$PATH"
ENV UV_LINK_MODE=copy
ENV UV_COMPILE_BYTECODE=1
ENV UV_PYTHON_DOWNLOADS=manual

# Install Python 3.10
RUN uv python install python3.10

FROM base-image AS runner-base
RUN apt-get update
# Skip Docker installation since we're not using dind
# Services that need Docker access should mount the host socket

FROM base-image AS builder

# Ensure PATH is set correctly
ENV PATH="/root/.local/bin:$PATH"

WORKDIR /app

# Copy common and fuzzer code
COPY ./common /common
COPY ./fuzzer /fuzzer

# Install dependencies
WORKDIR /fuzzer
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen

FROM runner-base AS runtime

# Ensure PATH is set correctly
ENV PATH="/root/.local/bin:$PATH"

RUN DEBIAN_FRONTEND=noninteractive apt-get update && \
    apt-get install -y git \
    && rm -rf /var/lib/apt/lists/*

# Create working directories for all components
RUN mkdir -p /tmp/builder /tmp/fuzzer /tmp/coverage /tmp/tracer /crs_scratch

# Copy the virtual environment from builder
COPY --from=builder /fuzzer/.venv /fuzzer/.venv

# Copy the source code
COPY ./common /common
COPY ./fuzzer /fuzzer

# Set Python path to find the modules
ENV PYTHONPATH=/fuzzer/src:/common/src:$PYTHONPATH
ENV PATH=/fuzzer/.venv/bin:$PATH

# Set the working directory
WORKDIR /fuzzer

# Set the unified fuzzer as the default command
CMD ["python", "-m", "buttercup.unified_fuzzer"]