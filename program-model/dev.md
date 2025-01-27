# Dev

Documentation to get started on developing Program Model APIs.

## Requirements

`n2-standard-4` [instance](https://cloud.google.com/compute/docs/general-purpose-machines#n2_machine_types).

## New

```shell
sudo apt install just

cd afc-crs-trail-of-bits/
cp env.template .env

mkdir crs_scratch/
git clone --recursive git@github.com:aixcc-finals/example-libpng.git crs_scratch/libpng

just run-indexer
```

## Setup

```shell
mkdir crs_scratch/
```

### Download libpng

```shell
git clone git@github.com:pnggroup/libpng.git crs_scratch/libpng
```

### Install Bazel

Follow [instructions](https://bazel.build/install/ubuntu#install-on-ubuntu). You will need to install a specific version of Bazel depending on what the `build` output below outputs.

### Install Dependencies

```shell
sudo apt install flex bison asciidoc graphviz source-highlight clang
```

### Download and build Kythe

From [documentation](https://kythe.io/getting-started/#build-a-release-of-kythe-using-bazel-and-unpack-it-in-optkythe)

Takes about 3 hours to build.

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
# If it errors about "could not load cache" just remove CMakeCache.txt and try again.


#TODO: testing:
cd ../
export KYTHE_RELEASE_DIR=`pwd`/opt/kythe-v0.0.67
export KYTHE_OUTPUT_DIRECTORY=`pwd`/kythe_output2
mkdir -p "kythe_output2"
export CXX="cxx_wrapper.sh"
export CCC="cxx_wrapper.sh"
export CC="cc_wrapper.sh"

cd libpng/
cmake .
make
```

### Merge kzip files

```shell
cd crs_scratch/
./opt/kythe-v0.0.67/tools/kzip merge --output $KYTHE_OUTPUT_DIRECTORY/merged.kzip $KYTHE_OUTPUT_DIRECTORY/*.kzip

./opt/kythe-v0.0.67/tools/kzip info --input $KYTHE_OUTPUT_DIRECTORY/merged.kzip | jq .
```

### Upload to JanusGraph

Start JanusGraph container

```shell
docker run janusgraph/janusgraph
```

Get IP address of JanusGraph container

```shell
docker ps | grep janusgraph
docker inspect -f '{{range.NetworkSettings.Networks}}{{.IPAddress}}{{end}}' <container_id>
```

Run graph creation

```shell
cd program-model/src/buttercup
../../../crs_scratch/opt/kythe-v0.0.67/indexers/cxx_indexer ../../../crs_scratch/kythe_output/merged.kzip | uv run program_model/indexer/entries_into_db.py --url ws://<ip_address>:8182/gremlin
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
```

## TODO

* `org.janusgraph.graphdb.transaction.StandardJanusGraphTx$3.execute - Query requires iterating over all vertices [[~label = x]]. For better performance, use indexes`
