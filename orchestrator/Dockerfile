ARG PYTHON_BASE=3.12-slim

FROM python:${PYTHON_BASE} as builder

RUN apt-get update
RUN pip install -U poetry==2.0.1

ENV POETRY_NO_INTERACTION=1 \
    POETRY_VIRTUALENVS_IN_PROJECT=0 \
    POETRY_VIRTUALENVS_CREATE=1 \
    POETRY_VIRTUALENVS_PATH=/opt/venv \
    POETRY_VIRTUALENVS_OPTIONS_ALWAYS_COPY=true \
    POETRY_CACHE_DIR=/tmp/poetry_cache

WORKDIR /app
COPY pyproject.toml poetry.lock /app/
RUN touch README.md

RUN poetry install --no-root && rm -rf $POETRY_CACHE_DIR
RUN poetry env info --path > /venv-path


FROM python:${PYTHON_BASE} as runtime-base

COPY --from=builder /venv-path /venv-path
COPY --from=builder /opt/venv /opt/venv

RUN echo '#!/bin/bash' > /env-setup.sh && \
    echo 'export PATH="/opt/venv/$(basename $(cat /venv-path))/bin:$PATH"' >> /env-setup.sh && \
    chmod +x /env-setup.sh

WORKDIR /app

FROM runtime-base as development
# Don't copy source code in dev - will be mounted as volume
SHELL ["/bin/bash", "-c"]
CMD ["/bin/bash", "-c", ". /env-setup.sh && exec uvicorn orchestrator.task_server.server:app --host 0.0.0.0 --reload --reload-dir /app"]

EXPOSE 8000

FROM runtime-base as production
SHELL ["/bin/bash", "-c"]
COPY orchestrator ./orchestrator
CMD ["/bin/bash", "-c", ". /env-setup.sh && exec uvicorn orchestrator.task_server.server:app --host 0.0.0.0"]

EXPOSE 8000
