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

# Install LiteLLM with all proxy dependencies
RUN pip install --no-cache-dir \
    "litellm[proxy]==1.57.8" \
    backoff \
    pyyaml \
    uvicorn \
    fastapi \
    python-multipart \
    apscheduler \
    pynacl \
    prisma \
    resend \
    python-dotenv

# Copy entrypoint if needed
# COPY --chmod=755 docker-entrypoint.sh /docker-entrypoint.sh

# Set the entrypoint and default command for proxy server
ENTRYPOINT ["litellm"]
CMD ["--port", "8080", "--host", "0.0.0.0"]