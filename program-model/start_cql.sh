#!/bin/bash

docker stop jg-cassandra
docker rm jg-cassandra

docker run \
    --name jg-cassandra \
    --network janusgraph-net \
    -d \
    -e CASSANDRA_START_RPC="true" \
    -p "9160:9160" \
    -p "9042:9042" \
    -p "7199:7199" \
    -p "7001:7001" \
    -p "7000:7000" \
    --memory="6g" \
    --cpus="2" \
    cassandra:4.0.6
