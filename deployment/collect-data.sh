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
kubectl exec -n crs -it buttercup-postgresql-0 -- env PGPASSWORD="litellm_password11" pg_dump -U litellm_user litellm -f /tmp/litellm_backup.sql
kubectl cp -n crs buttercup-postgresql-0:/tmp/litellm_backup.sql ./litellm_backup.sql

echo "Collecting logs from pods"
../collect-logs.sh

echo "Saving tasks_storage"
SCHEDULER_POD=$(kubectl get pod -n crs -l app=scheduler -o jsonpath='{.items[0].metadata.name}')
kubectl exec -n crs -it "$SCHEDULER_POD" -- tar -cf /tmp/tasks_storage.tar /tasks_storage
kubectl cp -n crs "$SCHEDULER_POD:/tmp/tasks_storage.tar" ./tasks_storage.tar

echo "Saving crs_scratch"
SCHEDULER_POD=$(kubectl get pod -n crs -l app=scheduler -o jsonpath='{.items[0].metadata.name}')
kubectl exec -n crs -it "$SCHEDULER_POD" -- tar -cf /tmp/crs_scratch.tar --exclude=*.tgz /crs_scratch
kubectl cp -n crs "$SCHEDULER_POD:/tmp/crs_scratch.tar" ./crs_scratch.tar

echo "Saving node_local_storage"
for node in $(kubectl get nodes -o jsonpath='{.items[*].metadata.name}'); do
    echo "Saving node_local_storage for node: $node"
    # Find a pod running on this node
    pod=$(kubectl get pods -n crs -o jsonpath="{.items[?(@.spec.nodeName=='$node')].metadata.name}" -l app=scratch-cleaner | cut -d' ' -f1)
    if [ -n "$pod" ]; then
        echo "Using pod $pod on node $node"
        kubectl exec -n crs -it "$pod" -- tar -zcf /tmp/node_local_storage.tar.gz --exclude-tag-all=task_meta.json /node_data
        kubectl cp -n crs "$pod:/tmp/node_local_storage.tar.gz" "./node_local_storage_${node}.tar.gz"
    else
        echo "No pod found running on node $node, skipping"
    fi
done


echo "All data collected in directory: ${RUN_DIR}"
