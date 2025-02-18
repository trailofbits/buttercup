ARG BASE_IMAGE=myorg/myapp:latest
FROM ${BASE_IMAGE}

COPY ./ccwrapper.sh ${SRC}/ccwrapper.sh
COPY ./cxxwrapper.sh ${SRC}/cxxwrapper.sh
RUN chmod +x ${SRC}/ccwrapper.sh && chmod +x ${SRC}/cxxwrapper.sh

ENV FUZZING_LANGUAGE=c++

ENV ORIG_CXX=${CXX}
ENV ORIG_CC=${CC}
ENV CXX=${SRC}/cxxwrapper.sh
ENV CCC=${SRC}/cxxwrapper.sh
ENV CC=${SRC}/ccwrapper.sh

COPY gzs/kythe/ ${SRC}/kythe
ENV KYTHE_RELEASE_DIR=${SRC}/kythe/
