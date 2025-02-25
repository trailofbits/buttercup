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

Set up a GitHub token.

```shell
gh auth login
GitHub.com
SSH
No
Paste the authentication token

gh auth token
```

Put GitHub token in `.env`.

See [REST API](https://docs.github.com/en/rest/releases/releases?apiVersion=2022-11-28#list-releases-assets) if you need to find the asset ID of a new release.

## Usage

Prepare example challenge project.

```shell
cd afc-crs-trail-of-bits/

./orchestrator/scripts/task_crs.sh
```

Start up CRS.

```shell
cd afc-crs-trail-of-bits/

docker compose up -d --build --remove-orphans
```

Send task to Program Model via Redis queue.

```shell
docker compose logs -f program-model
```

```shell
cd afc-crs-trail-of-bits/program-model/

uv run mock/trigger_pm.py \
  --build_type full \
  --package_name libpng \
  --sanitizer AddressSanitizer \
  --task_dir ../tasks_storage/5cea8f59-a7ab-4c77-97a9-f92fcfeb33d8 \
  --task_id libpng
```

## API

See [api.md](api.md).

## Testing on Challenges

See [challenges.md](challenges.md).

## Development

Sync, reformat, lint, and test before committing changes:

```shell
just all
```

## FAQs

* Why does this use a ubuntu base image?
  * Since Kythe uses OSS Fuzz to build and index the challenge source code, we have to use the same base image as ClusterFuzz.
* Why does this use Python 3.10?
  * ClusterFuzz uses Python 3.10.
* How do I build Kythe?
  * Follow the instructions in [dev.md](dev.md).
