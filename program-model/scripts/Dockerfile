ARG BASE_IMAGE=myorg/myapp:latest
FROM $BASE_IMAGE
ARG KYTHE_VERSION=v0.0.67
ARG KYTHE_TAR=gzs/kythe-v0.0.67.tar.gz

COPY ./ccwrapper.sh $SRC/ccwrapper.sh
COPY ./cxxwrapper.sh $SRC/cxxwrapper.sh
RUN chmod +x $SRC/ccwrapper.sh &&  chmod +x $SRC/cxxwrapper.sh

ENV FUZZING_LANGUAGE=c++

ENV ORIG_CXX=$CXX
ENV ORIG_CC=$CC
ENV CXX=$SRC/cxxwrapper.sh
ENV CCC=$SRC/cxxwrapper.sh
ENV CC=$SRC/ccwrapper.sh

ADD $KYTHE_TAR $SRC/kythe
#RUN tar -xvf $SRC/kythe-release.tar.gz -C $SRC 
ENV KYTHE_RELEASE_DIR=$SRC/kythe/kythe-$KYTHE_VERSION
