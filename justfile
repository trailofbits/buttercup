BUILDER_IMAGE_NAME := "kythe_builder"

build-kythe-builder:
    docker build -t {{BUILDER_IMAGE_NAME}} -f ./program-model/kythe_builder/Dockerfile .

build-kythe-tar-gz: build-kythe-builder
    docker run -v {{justfile_directory()}}/program-model/scripts/gzs/:/out {{BUILDER_IMAGE_NAME}}

download-kythe:
    #!/usr/bin/env bash
    set -euxo pipefail
    if [[ ! -f "program-model/scripts/gzs/kythe-v0.0.67.tar.gz" ]] 
    then
        mkdir -p program-model/scripts/gzs/
        gh release download v0.0.2 -R github.com/trailofbits/aixcc-kythe -D program-model/scripts/gzs/
    fi

install-gh:
    (type -p wget >/dev/null || (sudo apt update && sudo apt-get install wget -y)) \
    && sudo mkdir -p -m 755 /etc/apt/keyrings \
    && out=$(mktemp) && wget -nv -O$out https://cli.github.com/packages/githubcli-archive-keyring.gpg \
    && cat $out | sudo tee /etc/apt/keyrings/githubcli-archive-keyring.gpg > /dev/null \
    && sudo chmod go+r /etc/apt/keyrings/githubcli-archive-keyring.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" | sudo tee /etc/apt/sources.list.d/github-cli.list > /dev/null \
    && sudo apt update \
    && sudo apt install gh -y

download-cscope:
    mkdir -p cscope/
    docker pull ghcr.io/aixcc-finals/buttercup-cscope:main
    docker create --name temp-cscope ghcr.io/aixcc-finals/buttercup-cscope:main
    docker cp temp-cscope:/cscope cscope/
    docker rm temp-cscope

install-cscope:
    cd cscope/cscope/ && autoreconf -i -s && ./configure && make && sudo make install

build-indexer-image: 
    docker build -t indexer -f ./program-model/upload_worker.Dockerfile  .

run-indexer: download-kythe
    docker compose --profile=development up --build indexer-run

lint-python COMPONENT:
    cd {{ COMPONENT }} && uv sync --all-extras && uv run ruff format && uv run ruff check --fix && uv run mypy

lint-python-all:
    just lint-python common
    just lint-python fuzzer
    just lint-python orchestrator
    just lint-python patcher
    just lint-python program-model
    just lint-python seed-gen
