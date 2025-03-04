ARG BASE_IMAGE=myorg/myapp:latest
FROM ${BASE_IMAGE}

ENV FUZZING_LANGUAGE=c++

COPY ./compile_and_extract /usr/local/bin/compile_and_extract
RUN chmod +x /usr/local/bin/compile_and_extract
COPY gzs/kythe/ ${SRC}/kythe
ENV KYTHE_RELEASE_DIR=${SRC}/kythe/
