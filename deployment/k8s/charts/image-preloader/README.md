# Image Preloader

A Helm chart for preloading Docker images from ghcr.io in a Kubernetes cluster using Docker-in-Docker (DinD) sidecar.

## Purpose

This chart creates a Kubernetes job that pulls Docker images from ghcr.io and stores them on the node's Docker daemon. This is useful for:

- Preloading images to improve pod startup times
- Ensuring critical images are available even if ghcr.io is temporarily unavailable
- Reducing bandwidth usage by prefetching images once per node

## Configuration

The main configuration is done via the `values.yaml` file:

```yaml
enabled: true  # Set to false to disable the job

# Job configuration
backoffLimit: 3  # Number of retries before job is considered failed
restartPolicy: OnFailure  # Job restart policy

# Resources for the main container
resources:
  requests:
    cpu: 250m
    memory: 256Mi
  limits:
    cpu: 500m
    memory: 512Mi

# Resources for the DinD sidecar
dind:
  resources:
    requests:
      cpu: 500m
      memory: 1Gi
    limits:
      cpu: 1000m
      memory: 2Gi

# List of images to pull
imagesToPull:
  - ghcr.io/organization/image1:tag
  - ghcr.io/organization/image2:tag
```

## Usage

```bash
# Install the chart
helm install image-preloader ./image-preloader

# Upgrade with custom values
helm upgrade image-preloader ./image-preloader --values custom-values.yaml

# Check job status
kubectl get job -l app=image-preloader

# Check job logs
kubectl logs -l app=image-preloader
```

## Notes

- Images are pulled in sequence, and the job will fail if any image pull fails
- After all images are pulled, a Docker system prune is executed to clean up 