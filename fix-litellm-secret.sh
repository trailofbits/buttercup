#!/bin/bash
# Workaround script for litellm-api-user secret issue
# This creates the missing secret that patcher and seed-gen need

echo "Waiting for litellm secrets to be created..."
while ! kubectl get secret buttercup-litellm-api-secrets -n crs &>/dev/null; do
  sleep 2
done

echo "Creating litellm-api-user secret..."
LITELLM_KEY=$(kubectl get secret buttercup-litellm-api-secrets -n crs -o jsonpath='{.data.BUTTERCUP_LITELLM_KEY}' | base64 -d)
kubectl create secret generic litellm-api-user -n crs --from-literal=API_KEY="$LITELLM_KEY"

echo "Secret created successfully!"
kubectl get secret litellm-api-user -n crs