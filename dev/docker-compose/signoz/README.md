# SigNoz Local Deployment

This directory contains the SigNoz configuration for local development monitoring of the Buttercup CRS system.

## What is SigNoz?

SigNoz is an open-source observability platform that provides:
- Application Performance Monitoring (APM)
- Distributed Tracing  
- Metrics and Logs collection
- Real-time monitoring dashboards

## Local Docker Compose Usage

SigNoz is automatically included when you start the development environment:

```bash
cd dev/docker-compose
docker-compose up -d
```

This will start:
- SigNoz frontend (accessible at http://localhost:3301)
- OpenTelemetry collector (receiving traces on port 4317)
- ClickHouse database for storage
- All supporting services

## Configuration

The system is pre-configured to send telemetry data to the local SigNoz instance:
- **Endpoint**: `http://signoz-otel-collector:4317`
- **Protocol**: gRPC
- **Authentication**: Basic auth with username/password

## Accessing SigNoz

Once running, access the SigNoz UI at:
- **URL**: http://localhost:3301
- **Username**: admin (default)
- **Password**: admin (default)

## Kubernetes Integration

For Kubernetes deployments, SigNoz can be enabled in the `values-upstream-minikube.template`:

```yaml
signoz:
  enabled: true
```

When enabled, all Buttercup services will automatically send telemetry to the SigNoz collector.