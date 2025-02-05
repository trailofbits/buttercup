#!/bin/bash

docker run \
    -v `pwd`/conf/janusgraph-server.yaml:/opt/janusgraph/conf/janusgraph-server.yaml \
    --network janusgraph-net \
    -d \
    -p "8182:8182" \
    -e janusgraph.storage.backend="cql" \
    -e janusgraph.storage.hostname="jg-cassandra" \
    -e janusgraph.storage.cql.keyspace="janusgraph" \
    -e _JAVA_OPTIONS="-Xms4g -Xmx6g" \
    -v `pwd`/data:/opt/janusgraph/data \
    --memory="6g" \
    --cpus="4" \
    janusgraph/janusgraph

#   -e janusgraph.storage.backend="cql" \
#   -e janusgraph.storage.hostname="localhost:9042" \

#   docker run \
#       -v `pwd`/conf/janusgraph-server.yaml:/opt/janusgraph/conf/janusgraph-server.yaml \
#       --network janusgraph-net \
#       -d \
#       -p "8182:8182" \
#       -e janusgraph.storage.backend="cql" \
#       -e janusgraph.storage.batch-loading="true" \
#       -e janusgraph.storage.hostname="jg-cassandra" \
#       -e janusgraph.storage.cql.keyspace="janusgraph" \
#       -e _JAVA_OPTIONS="-Xms4g -Xmx8g" \
#       --memory="8g" \
#       --cpus="4" \
#       janusgraph/janusgraph


#   docker run \
#       -v `pwd`/program-model/conf/janusgraph-server.yaml:/opt/janusgraph/conf/janusgraph-server.yaml \
#       -e janusgraph.schema.default="none" \
#       -e janusgraph.storage.backend="inmemory" \
#       -e janusgraph.storage.batch-loading="true" \
#       -e janusgraph.storage.buffer-size="2048" \
#       -e janusgraph.ids.block-size="15000000" \
#       -e janusgraph.cache.db-cache="true" \
#       -e janusgraph.cache.db-cache-size="0.5" \
#       -e janusgraph.cache.db-cache-time="180000" \
#       -e _JAVA_OPTIONS="-Xms4g -Xmx8g" \
#       --memory="8g" \
#       --cpus="4" \
#       janusgraph/janusgraph
