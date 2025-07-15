# LiteLLM local build Dockerfile
ARG LITELLM_VERSION=v1.57.8-stable

# Use the official Python base image
FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    git \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Install LiteLLM
RUN pip install --no-cache-dir litellm==${LITELLM_VERSION#v}

# Copy entrypoint if needed
COPY --chmod=755 docker-entrypoint.sh /docker-entrypoint.sh 2>/dev/null || true

# Set the entrypoint
ENTRYPOINT ["litellm"]
CMD ["--help"]