# Trail of Bits AIxCC Finals CRS

## Dependencies

Follow the install instructions for the required dependencies:

* [Docker install guide](https://docs.docker.com/engine/install/ubuntu/)
* [kubectl install guide](https://kubernetes.io/docs/tasks/tools/install-kubectl-linux/)
* [helm install guide](https://helm.sh/docs/intro/install/):
* [minikube install guide](https://minikube.sigs.k8s.io/docs/start/?arch=%2Flinux%2Fx86-64%2Fstable%2Fdebian+package)
* Git LFS for some tests

## Configuration

Create a new configuration file, starting from the default template:

```shell
cp \
  deployment/env.template \
  deployment/env
```

Next, configure the following options. Follow the instructions in the comments when setting the `GHCR_AUTH` value.

```shell
SCANTRON_GITHUB_PAT
GHCR_AUTH
OPENAI_API_KEY
ANTHROPIC_API_KEY
DOCKER_USERNAME
DOCKER_PAT
```

### Settings specific to local development and testing

Use the hardcoded test credentials found in the comments:

```shell
AZURE_ENABLED=false
TAILSCALE_ENABLED=false
COMPETITION_API_KEY_ID: `11111111-1111-1111-1111-111111111111`
COMPETITION_API_KEY_TOKEN: `secret`
CRS_KEY_ID="515cc8a0-3019-4c9f-8c1c-72d0b54ae561"
CRS_KEY_TOKEN="VGuAC8axfOnFXKBB7irpNDOKcDjOlnyB"
CRS_API_HOSTNAME="<generated with: openssl rand -hex 16>"
BUTTERCUP_K8S_VALUES_TEMPLATE="k8s/values-minikube.template"
OTEL_ENDPOINT="<insert endpoint url from aixcc vault, is pseudo secret>"
OTEL_PROTOCOL="http"
```

Keep empty:

```shell
AZURE_API_BASE=""
AZURE_API_KEY=""
```

Commented out:

```shell
CRS_URL
CRS_API_HOSTNAME
LANGFUSE_HOST
LANGFUSE_PUBLIC_KEY
LANGFUSE_SECRET_KEY
OTEL_TOKEN
```

When [re-running unscored rounds](orchestrator/src/buttercup/orchestrator/mock_competition_api/README.md), set this to `true`:

```shell
MOCK_COMPETITION_API_ENABLED
```

## Authentication

### Docker

Log into ghcr.io:

```shell
docker login ghcr.io -u <username>
```

## Running the CRS

### Starting the services

```shell
cd deployment && make up
```

### Stopping the services

```shell
cd deployment && make down
```

### Sending the example-libpng task to the system

```shell
kubectl port-forward -n crs service/buttercup-competition-api 31323:1323
```

```shell
./orchestrator/scripts/task_crs.sh
```

Send a SARIF message

```shell
./orchestrator/scripts/send_sarif.sh <TASK-ID-FROM-TASK-CRS>
```

### Simulating Unscored Round 2

```shell
kubectl port-forward -n crs service/buttercup-competition-api 31323:1323
```

```shell
./orchestrator/scripts/challenge.sh
```

Check that patches get submitted to the bundler.

```shell
kubectl logs -n crs -l app=scheduler --tail=-1 --prefix | grep "WAIT_PATCH_PASS -> SUBMIT_BUNDLE"
```

If needing to debug, run the following to log into the pod.

```shell
kubectl get pods -n crs

kubectl exec -it -n crs <pod-name> -- /bin/bash
```

## Run Unscored Challenges

See [UNSCORED.md](UNSCORED.md)
