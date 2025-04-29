#!/bin/bash

# Script to extract logs from all containers in pods in the crs namespace
# Optionally filter pods by name with a command line argument
# Saves current and previous logs to individual files

# Check if filter argument is provided
pod_filter=""
if [ $# -eq 1 ]; then
  pod_filter="$1"
  echo "Filtering pods containing: $pod_filter"
fi

# Create logs directory if it doesn't exist
LOG_DIR="crs_pod_logs_$(date +%Y%m%d_%H%M%S)"
mkdir -p "$LOG_DIR"
echo "Creating log directory: $LOG_DIR"

# Set namespace to crs
namespace="${BUTTERCUP_NAMESPACE:-crs}"
echo "Processing namespace: $namespace"

# Get all pods in the crs namespace
all_pods=$(kubectl get pods -n "$namespace" -o jsonpath='{.items[*].metadata.name}')

# Filter pods if a filter is specified
if [ -n "$pod_filter" ]; then
  pods=""
  for pod in $all_pods; do
    if [[ "$pod" == *"$pod_filter"* ]]; then
      pods="$pods $pod"
    fi
  done
  pods=$(echo "$pods" | xargs)  # Trim leading/trailing whitespace
  echo "Found $(echo "$pods" | wc -w) pods matching filter"
else
  pods=$all_pods
  echo "Processing all pods in namespace"
fi

# Check if any pods were found
if [ -z "$pods" ]; then
  echo "No pods found matching the filter. Exiting."
  exit 1
fi

# Loop through each pod
for pod in $pods; do
  echo "  Processing pod: $pod"
  
  # Get all containers in the pod (including init containers)
  init_containers=$(kubectl get pod "$pod" -n "$namespace" -o jsonpath='{.spec.initContainers[*].name}' 2>/dev/null)
  containers=$(kubectl get pod "$pod" -n "$namespace" -o jsonpath='{.spec.containers[*].name}')
  
  # Process init containers if any
  for container in $init_containers; do
    echo "    Getting logs for init container: $container"
    
    # Current logs
    log_file="$LOG_DIR/${pod}-${container}.log"
    kubectl logs "$pod" --tail -1 -c "$container" -n "$namespace" > "$log_file" 2>/dev/null
    echo "      Current logs saved to: $log_file"
    
    # Previous logs (if container has restarted)
    prev_log_file="$LOG_DIR/${pod}-${container}.previous.log"
    kubectl logs "$pod" --tail -1 -c "$container" -n "$namespace" -p > "$prev_log_file" 2>/dev/null
    
    # Check if previous logs exist
    if [ -s "$prev_log_file" ]; then
      echo "      Previous logs saved to: $prev_log_file"
    else
      echo "      No previous logs found for this container"
      rm "$prev_log_file"
    fi
  done
  
  # Process regular containers
  for container in $containers; do
    echo "    Getting logs for container: $container"
    
    # Current logs
    log_file="$LOG_DIR/${pod}-${container}.log"
    kubectl logs "$pod" --tail -1 -c "$container" -n "$namespace" > "$log_file" 2>/dev/null
    echo "      Current logs saved to: $log_file"
    
    # Previous logs (if container has restarted)
    prev_log_file="$LOG_DIR/${pod}-${container}.previous.log"
    kubectl logs "$pod" --tail -1 -c "$container" -n "$namespace" -p > "$prev_log_file" 2>/dev/null
    
    # Check if previous logs exist
    if [ -s "$prev_log_file" ]; then
      echo "      Previous logs saved to: $prev_log_file"
    else
      echo "      No previous logs found for this container"
      rm "$prev_log_file"
    fi
  done
done

echo "Log extraction complete. All logs saved to $LOG_DIR"
