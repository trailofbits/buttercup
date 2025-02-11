# Program Model

A program model is a graph database that indexes a challenge project's source code.

Utility:
* The seed generator can query the program model to find unexplored program paths.
* The patcher can query the program model for information about functions, classes, and structures.

## Generate Program Model

* Indexes a challenge project's source code -- this is done once per challenge project.
* Stores the indexed source code in a graph database -- this is done once per challenge project.
* It provides a Python API for continuously querying and modifying the program graph.

## Usage Example

Create a [PAT](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry#authenticating-with-a-personal-access-token-classic). Authenticate it with `docker login ghcr.io` (see documentation).

Download Kythe release.

```shell
mkdir -p program-model/scripts/gzs/
cd program-model/scripts/gzs/

gh release download v0.0.2 -R github.com/trailofbits/aixcc-kythe
```

Prepare example challenge project.

```shell
mkdir -p crs_scratch/
mkdir -p tasks_storage/example-libpng/src/
mkdir -p tasks_storage/example-libpng/fuzz-tooling/

git clone --branch aixcc-exemplar-challenge-01 git@github.com:aixcc-finals/example-libpng.git tasks_storage/example-libpng/src/example-libpng

git clone --branch master git@github.com:aixcc-finals/oss-fuzz-aixcc.git tasks_storage/example-libpng/fuzz-tooling/fuzz-tooling

cp env.template .env

docker compose up --build
```

Send task to orchestrator for end-to-end test of the CRS.

```shell
cd common/

uv run src/buttercup/common/msg_publisher.py send tasks_ready_queue ../program-model/example/ready_msg.json
```

Or test just the Program Model.

```shell
cd program-model/

$ uv run buttercup-program-model --help
usage: buttercup-program-model [-h] [--log_level str] {serve,process} ...

options:
  -h, --help       show this help message and exit
  --log_level str  Log level (default: info)

subcommands:
  {serve,process}
    serve
    process

$ uv run buttercup-program-model --log_level debug process --task_id example-libpng
```

## Testing on Challenges

See [challenges.md](challenges.md).

## Development

Create a new virtual environment and enter it:

```shell
cd program-model/

uv venv
source .venv/bin/activate
uv sync --all-extras
```

Run tests:

```shell
pytest
```

Lock, reformat, and lint before committing changes:

```shell
just lock
just reformat
just lint
```

## FAQs

* Why does this use a ubuntu base image?
  * Since Kythe uses OSS Fuzz to build and index the challenge source code, we have to use the same base image as ClusterFuzz.
* Why does this use Python 3.10?
  * ClusterFuzz uses Python 3.10.
* How do I build Kythe?
  * Follow the instructions in [dev.md](dev.md).


## TODO

* [ ] Configure Dockerfiles
* [ ] Create getter/setter APIs
* [ ] Verify graph creation correctness
* [ ] Create unit and regression tests
* [ ] Integrate Program Model with other CRS components
  * [ ] Coverage Tracker
  * [ ] Seed Generator
  * [ ] Patcher
* Download Kythe `.tar.gz` file automatically
