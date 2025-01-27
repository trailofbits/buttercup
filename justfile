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
        curl -o program-model/scripts/gzs/kythe-v0.0.67.tar.gz https://github.com/trailofbits/aixcc-kythe/releases/download/v0.0.2/kythe-v0.0.67.tar.gz
    fi

build-indexer-image: 
    docker build -t indexer -f ./program-model/upload_worker.Dockerfile  .


run-indexer: download-kythe
    docker compose --profile=development up --build indexer-run
