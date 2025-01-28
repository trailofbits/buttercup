# Dev

Documentation to get started on developing Program Model APIs.

## Requirements

`n2-standard-4` [instance](https://cloud.google.com/compute/docs/general-purpose-machines#n2_machine_types).

## Docker (WIP)

```shell
(type -p wget >/dev/null || (sudo apt update && sudo apt-get install wget -y)) \
	&& sudo mkdir -p -m 755 /etc/apt/keyrings \
        && out=$(mktemp) && wget -nv -O$out https://cli.github.com/packages/githubcli-archive-keyring.gpg \
        && cat $out | sudo tee /etc/apt/keyrings/githubcli-archive-keyring.gpg > /dev/null \
	&& sudo chmod go+r /etc/apt/keyrings/githubcli-archive-keyring.gpg \
	&& echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" | sudo tee /etc/apt/sources.list.d/github-cli.list > /dev/null \
	&& sudo apt update \
	&& sudo apt install gh -y
sudo apt update
sudo apt install gh

github.com -> settings -> developer settings -> personal access tokens -> tokens (classic) -> generate new token
select "repo" scope
select "read:org" scope

gh auth login
GitHub.com
SSH
No
Paste an authentication token

gh release download v0.0.2 -R github.com/trailofbits/aixcc-kythe
<authenticate URL in browser for the first time>
rm kythe-v0.0.67.tar.gz

sudo apt install just

cd afc-crs-trail-of-bits/
cp env.template .env

mkdir crs_scratch/
git clone --recursive git@github.com:aixcc-finals/example-libpng.git crs_scratch/libpng

just run-indexer

<todo>

docker compose down
```

## Local

### Setup

```shell
cd afc-crs-trail-of-bits/
cd program-model/
mkdir crs_scratch/
```

### Download libpng

```shell
git clone git@github.com:aixcc-finals/example-libpng.git crs_scratch/libpng
```

### Download Kythe

```shell
mkdir -p scripts/gzs/
gh release download v0.0.2 -R github.com/trailofbits/aixcc-kythe -D scripts/gzs/
mkdir crs_scratch/opt/
tar -zxf scripts/gzs/kythe-v0.0.67.tar.gz --directory crs_scratch/opt/
```

### If no download available, build Kythe

Takes about 3 hours to build.

#### Install Bazel

Follow [instructions](https://bazel.build/install/ubuntu#install-on-ubuntu). You will need to install a specific version of Bazel depending on what the `build` output below outputs.

#### Install Dependencies

```shell
sudo apt install flex bison asciidoc graphviz source-highlight clang
```

#### Download and build Kythe

From [documentation](https://kythe.io/getting-started/#build-a-release-of-kythe-using-bazel-and-unpack-it-in-optkythe)

```shell
git clone git@github.com:trailofbits/aixcc-kythe.git crs_scratch/aixcc-kythe
cd crs_scratch/aixcc-kythe
git checkout a301676c20db9849a06878fa9cc017907eb64d72
bazel build //kythe/release
mkdir ../opt/
tar -zxf bazel-bin/kythe/release/kythe-v0.0.67.tar.gz --directory ../opt/
cd ../
```

## Usage

### Run indexer with Kythe

From [documentation](https://kythe.io/examples/#extracting-cmake-based-repositories)

```shell
sudo apt install cmake

cd crs_scratch/
export KYTHE_ROOT_DIRECTORY=`pwd`/libpng
export KYTHE_CORPUS="myrepo"
export KYTHE_OUTPUT_DIRECTORY=`pwd`/kythe_output
mkdir -p "$KYTHE_OUTPUT_DIRECTORY"
export CMAKE_ROOT_DIRECTORY=`pwd`/libpng

cd libpng/
../opt/kythe-v0.0.67/tools/runextractor cmake -extractor=../opt/kythe-v0.0.67/extractors/cxx_extractor -sourcedir=$CMAKE_ROOT_DIRECTORY
```

### Merge kzip files

```shell
cd crs_scratch/
./opt/kythe-v0.0.67/tools/kzip merge --output $KYTHE_OUTPUT_DIRECTORY/merged.kzip $KYTHE_OUTPUT_DIRECTORY/*.kzip

./opt/kythe-v0.0.67/tools/kzip info --input $KYTHE_OUTPUT_DIRECTORY/merged.kzip | jq .
./opt/kythe-v0.0.67/tools/kzip view $KYTHE_OUTPUT_DIRECTORY/merged.kzip | jq .
```

### Upload to JanusGraph

Start JanusGraph container with custom configuration file.

```shell
docker run -v `pwd`/program-model/conf/janusgraph-server.yaml:/opt/janusgraph/conf/janusgraph-server.yaml janusgraph/janusgraph
```

To modify the JanusGraph `yaml` file, make sure to understand the default values first.

```shell
docker run -it janusgraph/janusgraph /bin/bash

$ cat /opt/janusgraph/conf/janusgraph-server.yaml
```

Get IP address of JanusGraph container.

```shell
docker ps | grep janusgraph
docker inspect -f '{{range.NetworkSettings.Networks}}{{.IPAddress}}{{end}}' <container_id>
```

Run graph creation.

```shell
cd program-model/src/buttercup
../../crs_scratch/opt/kythe-v0.0.67/indexers/cxx_indexer --ignore_unimplemented ../../crs_scratch/kythe_output/merged.kzip | uv run program_model/indexer/entries_into_db.py --url ws://<ip_address>:8182/gremlin
```

Verify graph creation. From [documentation](https://docs.janusgraph.org/getting-started/installation/).

```shell
docker ps | grep janusgraph
docker run --rm --link <container_name>:janusgraph -e GREMLIN_REMOTE_HOSTS=janusgraph -it janusgraph/janusgraph ./bin/gremlin.sh
```

```shell
gremlin> :remote connect tinkerpop.server conf/remote.yaml
gremlin> :remote console
gremlin> g.V().count()
gremlin> g.E().count()
```

Remove all docker containers to continue testing from scratch

```shell
CTRL-C janusgraph/janusgraph

docker system prune -a
docker system df
```

## Contributing

Before committing code, run the following to ensure that the code is formatted correctly.

```shell
just reformat
just lint
```

## TODO

* `org.janusgraph.graphdb.transaction.StandardJanusGraphTx$3.execute - Query requires iterating over all vertices [[~label = x]]. For better performance, use indexes`
