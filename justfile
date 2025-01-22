BUILDER_IMAGE_NAME := "kythe_builder"

build-kythe-builder:
    docker build -t {{BUILDER_IMAGE_NAME}} -f ./program-model/kythe_builder/Dockerfile .

build-kythe-tar-gz: build-kythe-builder
    docker run -v {{justfile_directory()}}/program-model/scripts/gzs/:/out {{BUILDER_IMAGE_NAME}}