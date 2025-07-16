# OSS-Fuzz Dockerfile for crashy project
FROM gcr.io/oss-fuzz-base/base-builder

# Install any needed dependencies
RUN apt-get update && apt-get install -y make

# Copy source code
COPY src $SRC/crashy

# Copy build script
COPY projects/crashy/build.sh $SRC/

WORKDIR $SRC/crashy