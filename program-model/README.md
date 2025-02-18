# Program Model

Indexes a program into a graph database.

## Requirements

`n2-highmem-8` [instance](https://cloud.google.com/compute/docs/general-purpose-machines#n2-high-mem).

## Setup

Set up working directory and tasks directory.

```shell
cd afc-crs-trail-of-bits/

cp env.template .env

sudo mkdir /crs_scratch/ && sudo chown `whoami`:`whoami` /crs_scratch && sudo mount --bind ./crs_scratch /crs_scratch

sudo mkdir /tasks_storage && sudo chown `whoami`:`whoami` /tasks_storage && sudo mount --bind ./tasks_storage /tasks_storage
```

Set up GitHub token.

```shell
gh auth login
GitHub.com
SSH
No
Paste an authentication token

echo <token> | docker login ghcr.io -u <username> --password-stdin
```

Download Kythe.

```shell
cd afc-crs-trail-of-bits/

mkdir -p program-model/scripts/gzs/kythe/

gh release download v0.0.2 -R github.com/trailofbits/aixcc-kythe -D program-model/scripts/gzs/

tar -xvzf program-model/scripts/gzs/kythe-v0.0.67.tar.gz -C program-model/scripts/gzs/kythe/ --strip-components=1
```

## Usage

Prepare example challenge project.

```shell
cd afc-crs-trail-of-bits/

mkdir -p tasks_storage/example-libpng/src/ && mkdir -p tasks_storage/example-libpng/fuzz-tooling/

git clone --branch aixcc-exemplar-challenge-01 git@github.com:aixcc-finals/example-libpng.git tasks_storage/example-libpng/src/example-libpng

git clone --branch master git@github.com:aixcc-finals/oss-fuzz-aixcc.git tasks_storage/example-libpng/fuzz-tooling/fuzz-tooling
```

Start up CRS.

```shell
cd afc-crs-trail-of-bits/

docker compose up -d --build

# cd common/
# uv run src/buttercup/common/msg_publisher.py send tasks_ready_queue ../program-model/mock_data/ready_msg.json
```

Send task to Program Model via Redis queue.

```shell
docker compose logs -f program-model
```

```shell
cd afc-crs-trail-of-bits/program-model/

uv run mock/trigger_pm.py \
  --package_name libpng \
  --sanitizer AddressSanitizer \
  --source_path ../tasks_storage/example-libpng/src/example-libpng/ \
  --ossfuzz ../tasks_storage/example-libpng/fuzz-tooling/fuzz-tooling/ \
  --task_id example-libpng \
  --build_type full
```

Send task to Program Model via cli.

```shell
cd afc-crs-trail-of-bits/program-model/

uv run buttercup-program-model \
  --log_level debug \
  process \
  --wdir ../crs_scratch/ \
  --script_dir scripts/ \
  --kythe_dir scripts/gzs/kythe/ \
  --package_name libpng \
  --sanitizer AddressSanitizer \
  --source_path ../tasks_storage/example-libpng/src/example-libpng/ \
  --ossfuzz ../tasks_storage/example-libpng/fuzz-tooling/fuzz-tooling/ \
  --task_id example-libpng \
  --build_type full
```

## Testing on Challenges

See [challenges.md](challenges.md).

## Development

Create a new virtual environment and enter it:

```shell
cd afc-crs-trail-of-bits/program-model/

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

* [x] Configure Dockerfiles
* [x] Modify `cxxwrapper.sh` to match `ccwrapper.sh`
* [x] Untruncate graph (see `graph.py`)
* [x] Speed up graph creation (see `program_model.py`)
* [ ] Create getter/setter APIs
* [ ] Create unit and regression tests
* [ ] Create one graph per task id
* [ ] Integrate Program Model with other CRS components
  * [ ] Coverage Tracker
  * [ ] Seed Generator
  * [ ] Patcher
* [ ] Verify graph creation correctness
* [ ] Implement more error handling, especially for subprocess runs
* [ ] Download Kythe `.tar.gz` file automatically from github releases
* [ ] Debug issue in `oss_fuzz_indexer.py:index_target()` -- outputted `kzip` files contain critical errors
* [ ] Ensure challenge project is being built and not the oss-fuzz project
* [ ] Periodically backup the graph database into a graphml file
* [ ] Figure out how to make `ccwrapper.sh` not break LD detection
* [ ] Consider periodically removing indexing images for disk space
* [ ] Add support for `java`
* [ ] Consider corner cases
