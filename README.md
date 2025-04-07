# Trail of Bits AIxCC Finals CRS

# Local Development (minikube, full system)
```shell
cd deployment
cp env.template env
# Modify `env` according to your needs
# Make sure BUTTERCUP_K8S_VALUES_TEMPLATE is set to `k8s/values-minikube.template`
# AZURE_ENABLED/TAILSCALE_ENABLED should be set to false for local development
make up
```

```shell
make down
```

## Send example-libpng task to the system
```shell
kubectl port-forward -n crs service/buttercup-competition-api 31323:1323
```

```shell
./orchestrator/scripts/task_crs.sh
```

# Local Development (docker compose)
We use `docker compose` to test CRS components locally during development.

Copy `env.template` to `.env` and set variables.
Modify `competition-server/scantron.yaml` to use your own `github.pat` (make sure to create it with `repo` and `package:read` permissions).

Start the services with
```
docker compose up -d
```

Stop the services with:
```
docker compose down
```

# Telemetry
By default, LLM OTel telemetry is enabled and will be sent to a local SigNoz deployment.

To disable the SigNoz deployment, comment out in `competition-server/compose.yaml`:
```
include:
 - ./signoz/compose.yaml
```
To disable sending OTel telemetry, remove these environment variables from `env.dev.compose`:
```
OTEL_EXPORTER_OTLP_ENDPOINT
OTEL_EXPORTER_OTLP_HEADERS
OTEL_EXPORTER_OTLP_PROTOCOL
```
You can also change the values for these environment variables if you want to send telemetry to a different OTel collector.
