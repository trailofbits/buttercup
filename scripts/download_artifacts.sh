#!/bin/bash

# Download all artifacts from the buttercup-ui pod
BUTTERCUP_UI_POD=$(kubectl get pods -n ${BUTTERCUP_NAMESPACE:-crs} -l app=ui -o jsonpath='{.items[0].metadata.name}')
kubectl cp -n crs $BUTTERCUP_UI_POD:/tmp/buttercup-run-data /tmp/buttercup-run-data

echo "Artifacts downloaded to /tmp/buttercup-run-data"
