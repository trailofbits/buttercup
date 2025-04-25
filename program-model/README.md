# Program Model

Indexes a program into a graph database.

## Requirements

`n2-highmem-8` [instance](https://cloud.google.com/compute/docs/general-purpose-machines#n2-high-mem).

```shell
sudo apt-get install -y codequery
```

## Setup

Set up working directory and tasks directory.

```shell
cd afc-crs-trail-of-bits/

cp env.template .env

sudo mkdir /crs_scratch/ && sudo chown `whoami`:`whoami` /crs_scratch && sudo mount --bind ./crs_scratch /crs_scratch

sudo mkdir /tasks_storage && sudo chown `whoami`:`whoami` /tasks_storage && sudo mount --bind ./tasks_storage /tasks_storage
```

Set up Github token.

```shell
gh auth login
GitHub.com
SSH
No
Paste the authentication token

gh auth token | docker login ghcr.io -u USERNAME --password-stdin
```

Build the [Kythe](https://github.com/trailofbits/aixcc-kythe) docker image and push to `aixcc-finals`.
Create your own personal PAT, and give it `write:packages` permissions -- do not configure SSO for any organization.
Log into `ghcr.io` like above.

```shell
git clone git@github.com:trailofbits/aixcc-kythe.git
cd aixcc-kythe/

# Takes roughly 70 minutes to build and 15 minutes to copy the .tar.gz file.
docker build -t aixcc-kythe -f aixcc.Dockerfile .
docker tag aixcc-kythe ghcr.io/aixcc-finals/buttercup-kythe:main
docker push ghcr.io/aixcc-finals/buttercup-kythe:main
```

You should see the `buttercup-kythe` package [here](https://github.com/orgs/aixcc-finals/packages?visibility=private).

Build [cscope](https://github.com/trailofbits/aixcc-cscope) docker image and push to `aixcc-finals`.

```shell
git clone git@github.com:trailofbits/aixcc-cscope.git
cd aixcc-cscope/
git checkout buttercup

docker build -t aixcc-cscope -f aixcc.Dockerfile .
docker tag aixcc-cscope ghcr.io/aixcc-finals/buttercup-cscope:main
docker push ghcr.io/aixcc-finals/buttercup-cscope:main
```

You should see the `buttercup-cscope` package [here](https://github.com/orgs/aixcc-finals/packages?visibility=private).

## Usage

Start up CRS.

```shell
cd afc-crs-trail-of-bits/

docker compose up -d --build --remove-orphans

docker compose logs -f program-model
```

Send task to CRS.

```shell
git clone git@github.com:aixcc-finals/generate-challenge-task.git

cd generate-challenge-task/

# Libpng Challenge (c language)
./generate-challenge-task.sh -p libpng -c 127.0.0.1:8000 -t "https://github.com/aixcc-finals/example-libpng.git" -b 0cc367aaeaac3f888f255cee5d394968996f736e -r 2c894c66108f0724331a9e5b4826e351bf2d094b
./task_crs.sh

# Antlr4 Challenge (java language)
./generate-challenge-task.sh -p antlr4-java -c 127.0.0.1:8000 -t "https://github.com/antlr/antlr4.git" -b master
./task_crs.sh
```

## API

See [api.md](api.md).

## Testing on Challenges

See [challenges.md](challenges.md).

## Development

Sync, reformat, lint, and test before committing changes to this directory:

```shell
just all
```

Note: To run tests locally, you may need to run this beforehand

```shell
sudo mount --bind ./crs_scratch /crs_scratch
just download-kythe
```

## JanusGraph Indexing References

* <https://user3141592.medium.com/single-vs-composite-indexes-in-relational-databases-58d0eb045cbe>
* <https://docs.janusgraph.org/schema/index-management/index-performance/>
* <https://docs.janusgraph.org/schema/schema-init-strategies/>
* <https://docs.janusgraph.org/configs/configuration-reference/#schema>
* <https://docs.janusgraph.org/v0.3/basics/schema/#:~:text=.util.UUID%20)-,Property%20Key%20Cardinality,all%20elements%20in%20the%20graph.>

## FAQs

* Why does this use a ubuntu base image?
  * Since Kythe uses OSS Fuzz to build and index the challenge source code, we have to use the same base image as ClusterFuzz.
* Why does this use Python 3.10?
  * ClusterFuzz uses Python 3.10.
