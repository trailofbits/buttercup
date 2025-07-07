download-cscope:
    mkdir -p cscope/
    docker pull ghcr.io/trailofbits/buttercup-cscope:main
    docker create --name temp-cscope ghcr.io/trailofbits/buttercup-cscope:main
    docker cp temp-cscope:/cscope cscope/
    docker rm temp-cscope

install-cscope:
    cd cscope/cscope/ && autoreconf -i -s && ./configure && make && sudo make install

lint-python COMPONENT:
    cd {{ COMPONENT }} && uv sync --all-extras && uv run ruff format && uv run ruff check --fix && uv run mypy

lint-python-all:
    just lint-python common
    just lint-python fuzzer
    just lint-python orchestrator
    just lint-python patcher
    just lint-python program-model
    just lint-python seed-gen
