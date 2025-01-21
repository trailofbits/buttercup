# Program Model

This is a demo project that shows how to index an oss-fuzz project (reliablyish) with kythe and upload the results in a graph db

The components are listed and discussed below:

## kythe_builder

This is a docker image responsible for building kythe within the base-clang image. This should be built first and produces a tar.gz of kythe that can be injected in oss-fuzz docker images.

## scripts

These scripts are used to create a Docker image that is dervived from a project builder e.g. gcr.io/oss-fuzz/libpng.

The Dockerfile is parameterized over the base image used. So one can build an oss-fuzz project with kythe as follows:
* use oss-fuzz helper.py to build the project 
* build the scripts/Dockerfile with the project as the base 

`cd scripts && docker build --build-arg BASE_IMAGE=gcr.io/oss-fuzz/libpng .` 
Then you should be able to run compile as normal for an oss-fuzz image and generate kzips (indexed versions of the object files).

## kythe

Once you have a kzip for each compilation action then you need to merge these to a global kzip using 
`kythe/tools/kzip merge --output $KYTHE_OUTPUT_DIRECTORY/merged.kzip $KYTHE_OUTPUT_DIRECTORY/*.kzip`

Once you have a bunch of kzips you need to index these with the cxx_indexer in kythe. 

e.g.

`kythe/indexers/cxx_indexer --ignore_unimplemented <merged.kzip>`

This produces a stream of protobuf on stdout. Specifically each protobuf record is an entry described in this spec [text](https://kythe.io/docs/kythe-storage.html#_entry)

## program_model

This pyhon script specifically program_model/indexer/entries_into_db.py reads the protobuf entries from kythe and uploads them to JanusGraph. 

This is invoked (after entering poetry shell) with 
`python program_model/indexer/entries_into_db --url <janus_graph_url>`

janus graph can be run via docker with 

`docker run janusgraph/janusgraph`

The url can be determined with  

```
docker inspect \
  -f '{{range.NetworkSettings.Networks}}{{.IPAddress}}{{end}}' <janus container>
```

this will get you the ip, then the url is `ws://<IP address>:8182/gremlin`