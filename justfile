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
