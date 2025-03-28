# Trail of Bits AIxCC Finals CRS

# Local Development
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
