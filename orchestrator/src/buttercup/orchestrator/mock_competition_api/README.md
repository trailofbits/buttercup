# Mock Competition API

A mock implementation of the competition API for testing and development purposes with CRS integration.

## Features

- Always returns `accepted`/`passed` status for all submissions
- Serves files from a provided `.tar.gz` file
- Schedules tasks based on control file timing
- Sends tasking to the CRS using the task server API
- Supports HTTP file uploads for Kubernetes deployment

## Quick Start

```bash
# Local development with tarball
python -m buttercup.orchestrator.mock_competition_api \
  --tarball ./my_files.tar.gz

# With CRS integration
python -m buttercup.orchestrator.mock_competition_api \
  --crs-url http://task-server:8000/v1/task/ \
  --crs-key-id your-key-id \
  --crs-token your-token \
  --crs-enabled \
  --base-url http://mock-api-hostname:8080
```

## Usage

### Running the API

```bash
# Basic usage (no initial tarball)
python -m buttercup.orchestrator.mock_competition_api

# Full options
python -m buttercup.orchestrator.mock_competition_api \
  --tarball /path/to/files.tar.gz \
  --host 0.0.0.0 \
  --port 8080 \
  --crs-url http://task-server:8000/v1/task/ \
  --crs-key-id your-key-id \
  --crs-token your-token \
  --crs-enabled \
  --base-url http://mock-api-hostname:8080
```

### Important Parameters

- `--base-url`: Set this to the externally accessible URL of the mock API service. The CRS will use this URL to download files referenced in tasks. In Kubernetes, this should be the service URL with the release name prefix (e.g., `http://release-name-mock-competition-api.namespace.svc.cluster.local:8080`).

### API Endpoints

- `GET /v1/ping/`: Health check
- `POST /upload-tarball/`: Upload files tarball
- `POST /control-file/`: Upload control file
- `POST /v1/task/{task_id}/bundle/`: Submit a bundle
- `GET /v1/task/{task_id}/bundle/{bundle_id}/`: Get bundle status
- `GET /v1/file/{file_hash}`: Download a file
- `GET /files-status/`: Check available files

### Example Workflow

1. Start the API server
2. Upload your tarball (if not provided at startup):
   ```bash
   curl -X POST "http://localhost:8080/upload-tarball/" \
     -F "file=@/path/to/files.tar.gz"
   ```
3. Check file status:
   ```bash
   curl "http://localhost:8080/files-status/"
   ```
4. Upload the control file:
   ```bash
   curl -X POST "http://localhost:8080/control-file/" \
     -F "file=@/path/to/control_file.json"
   ```

## Control File Format

The control file is a JSON array of task objects:

```json
[
  {
    "id": "0196a6de-f416-7b71-96df-c0f51a52298d",
    "type": "full",
    "deadline": "2025-05-07T18:32:31.505133+00:00",
    "source": [
      {
        "url": "03ebf5c6a2ad41392bb71b126baea78126f330537db55202b5f5690c3d5134f1",
        "type": "repo",
        "sha256": "03ebf5c6a2ad41392bb71b126baea78126f330537db55202b5f5690c3d5134f1"
      },
      {
        "url": "2eb947a162026c96fcfac9c1717081ae0b811b3d5f3cfa11059ea902173efeca",
        "type": "fuzz-tooling",
        "sha256": "2eb947a162026c96fcfac9c1717081ae0b811b3d5f3cfa11059ea902173efeca"
      }
    ],
    "round_id": "exhibition2",
    "created_at": "2025-05-06T18:32:31.507612+00:00",
    "updated_at": "2025-05-06T18:32:31.507612+00:00",
    "focus": "round-exhibition2-freerdp",
    "project_name": "freerdp",
    "commit": "102a6e57fa2417f128b65341cbe27d9b9208206d",
    "harnesses_included": true
  }
]
```

## Kubernetes Deployment

The mock API can be deployed in Kubernetes using the existing orchestrator container.

```bash
# Apply the Helm chart
kubectl apply -f deployments/k8s/charts/mock-competition-api

# Get the pod name
POD_NAME=$(kubectl get pods -l app=mock-competition-api -o jsonpath="{.items[0].metadata.name}")

# Port-forward to access the API
kubectl port-forward $POD_NAME 8080:8080
```

### Kubernetes Configuration

In your values.yaml:

```yaml
# Enable or disable the mock competition API
enabled: true

# Base URL for serving files - this should be the externally accessible URL of the mock API service
# Leave empty to auto-generate based on the release name and namespace
baseUrl: ""  # Will auto-generate: "http://<release-name>-mock-competition-api.<namespace>.svc.cluster.local:8080"

# Or specify explicitly if needed:
baseUrl: "http://afc-crs-mock-competition-api.default.svc.cluster.local:8080"
```

**Important:** The service name in Kubernetes includes the release name prefix. For example, if your Helm release is named "afc-crs", the service name will be "afc-crs-mock-competition-api", not just "mock-competition-api". Make sure the base URL reflects this naming pattern.

### CRS Credentials

The default credentials in development are:
- API Key ID: `515cc8a0-3019-4c9f-8c1c-72d0b54ae561` 
- API Token: `VGuAC8axfOnFXKBB7irpNDOKcDjOlnyB`

To update the credentials:

```bash
kubectl create secret generic crs-api-credentials \
  --from-literal=api-key-id=your-key-id \
  --from-literal=api-token=your-token \
  --dry-run=client -o yaml | kubectl apply -f -
```

## Troubleshooting

### URL Connection Issues

If you see errors like:
```
Failed to download http://mock-competition-api.default.svc.cluster.local:8080/v1/file/...
```

Make sure:
1. The service name in the URL includes the Helm release prefix (e.g., `afc-crs-mock-competition-api`)
2. The namespace is correct
3. No network policies are blocking access between the services

To verify the correct service name:
```bash
kubectl get services -n <namespace>
```

## Notes

- This is a testing/development tool and not intended for production use
- The mock API automatically authenticates with the CRS task server when enabled 