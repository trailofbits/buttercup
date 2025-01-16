FROM gcr.io/oss-fuzz-base/base-runner

RUN curl -sSL https://install.python-poetry.org | python3 -
COPY ./common /common
COPY ./fuzzer /fuzzer

RUN cd /fuzzer && /root/.local/bin/poetry install