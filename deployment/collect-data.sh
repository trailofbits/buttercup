#!/bin/bash

# Create timestamped directory
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
RUN_DIR="run_data_${TIMESTAMP}"
mkdir -p "${RUN_DIR}"
cd "${RUN_DIR}"

echo "Collecting all data post-run"
# Get cluster info
echo "Current Kubernetes context:"
kubectl config current-context

echo -e "\nCluster nodes:"
kubectl get nodes

echo -e "\nNamespaces:"
kubectl get namespaces

echo -e "\nPods in crs namespace:"
kubectl get pods -n crs

# Ask for confirmation
read -p "Is this the correct cluster to collect run data from? (y/N) " confirm
if [[ $confirm != [yY] ]]; then
    echo "Aborting data collection"
    exit 1
fi

echo "Collecting data from redis"
kubectl exec -n crs -it buttercup-redis-master-0 -- redis-cli save
kubectl cp -n crs buttercup-redis-master-0:/data/dump.rdb ./redis-backup.rdb

echo "Collecting data from postgres"
kubectl exec -n crs -it buttercup-postgresql-0 -- pg_dump -U litellm litellm -f /tmp/litellm_backup.sql
kubectl cp -n crs buttercup-postgresql-0:/tmp/litellm_backup.sql ./litellm_backup.sql

echo "Collecting logs from pods"
../collect-logs.sh

echo "Saving crs_scratch"
SCHEDULER_POD=$(kubectl get pod -n crs -l app=scheduler -o jsonpath='{.items[0].metadata.name}')
kubectl exec -n crs -it $SCHEDULER_POD -- tar -cf /tmp/crs_scratch.tar /crs_scratch
kubectl cp -n crs $SCHEDULER_POD:/tmp/crs_scratch.tar ./crs_scratch.tar

echo "Saving tasks_storage"
SCHEDULER_POD=$(kubectl get pod -n crs -l app=scheduler -o jsonpath='{.items[0].metadata.name}')
kubectl exec -n crs -it $SCHEDULER_POD -- tar -cf /tmp/tasks_storage.tar /tasks_storage
kubectl cp -n crs $SCHEDULER_POD:/tmp/tasks_storage.tar ./tasks_storage.tar

echo "All data collected in directory: ${RUN_DIR}"
