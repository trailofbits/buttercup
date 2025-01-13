ARG PYTHON_BASE=3.12-slim

FROM python:${PYTHON_BASE} as builder

RUN apt-get update
RUN pip install -U poetry==2.0.1

ENV POETRY_NO_INTERACTION=1 \
    POETRY_VIRTUALENVS_IN_PROJECT=1 \
    POETRY_VIRTUALENVS_CREATE=1 \
    POETRY_CACHE_DIR=/tmp/poetry_cache

WORKDIR /app
COPY pyproject.toml poetry.lock /app/
RUN touch README.md

RUN poetry install --no-root && rm -rf $POETRY_CACHE_DIR


FROM python:${PYTHON_BASE} as runtime

ENV VIRTUAL_ENV=/app/.venv \
    PATH="/app/.venv/bin:$PATH"

COPY --from=builder ${VIRTUAL_ENV} ${VIRTUAL_ENV}

COPY crs_api ./crs_api

ENTRYPOINT ["uvicorn", "crs_api.server:app", "--host", "0.0.0.0"]
EXPOSE 8000
