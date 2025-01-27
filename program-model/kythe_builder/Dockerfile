FROM gcr.io/oss-fuzz-base/base-clang

ENV KYTHE_VERSION=v0.0.67
RUN apt update && apt -y install bison flex uuid-dev asciidoc graphviz source-highlight
RUN apt -y install git
COPY program-model/aixcc-kythe /kythe
RUN apt install apt-transport-https curl gnupg -y
RUN curl -fsSL https://bazel.build/bazel-release.pub.gpg | gpg --dearmor >bazel-archive-keyring.gpg
RUN mv bazel-archive-keyring.gpg /usr/share/keyrings
RUN echo "deb [arch=amd64 signed-by=/usr/share/keyrings/bazel-archive-keyring.gpg] https://storage.googleapis.com/bazel-apt stable jdk1.8" | tee /etc/apt/sources.list.d/bazel.list
RUN apt update && apt -y install bazel-7.1.0 build-essential

COPY program-model/kythe_builder/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
WORKDIR /kythe

ENTRYPOINT ["/entrypoint.sh"]