# Tailnet-accessible hosted Competitor Test Server

The organizers have set up a test competition API server for each team that is reachable from the internet, but tasks your CRS hosted on the tailnet. Telemetry from these runs get forwarded to your team’s telemetry
server.

It is intended that competitors may use this to task their CRS with challenges from prior rounds that are available in the aixcc-finals org. There are three changes to your CRS deployment that are required in order for
you to use this server.

1. Change the URL of the Competition API to `https://test-<team-moniker>-api.tail7e9b4c.ts.net`
2. If you are using Kubernetes Tailscale Operator, add another Service for this test URL so that it can be accessible from your cluster. See
   [proxies.yaml](https://github.com/aixcc-finals/example-crs-architecture/blob/main/example-crs-architecture/k8s/base/tailscale-connections/proxies.yaml) for context.
3. Append `-testing` to your CRS hostname, for example `team-moniker-testing`. This is the URL that is configured by default.

If you want to use a different CRS URL **for the tailscale-hosted competitor test server**, use the following:

Update CRS hostname used by the hosted competitor testing server

```bash
curl -u 11111111-1111-1111-1111-111111111111:pY8rLk7FvQ2hZm9GwUx3Ej5BnTcV4So0 -X PATCH  https://<team-moniker>.tasker.aixcc.tech/crs/url/ -H 'Content-Type: application/json' -d '{"hostname":"team-moniker-testing-1"}'
```

Get CRS hostname used by the hosted competitor testing server

```bash
curl -u 11111111-1111-1111-1111-111111111111:pY8rLk7FvQ2hZm9GwUx3Ej5BnTcV4So0 https://<team-moniker>.tasker.aixcc.tech/crs/url/
```

Kick off tasks with the server

```bash
# Integration Test
curl -u 11111111-1111-1111-1111-111111111111:pY8rLk7FvQ2hZm9GwUx3Ej5BnTcV4So0 -X 'POST' 'https://<team-moniker>.tasker.aixcc.tech/v1/request/delta/'
# LibPNG
curl -u 11111111-1111-1111-1111-111111111111:pY8rLk7FvQ2hZm9GwUx3Ej5BnTcV4So0 -X 'POST' 'https://<team-moniker>.tasker.aixcc.tech/webhook/trigger_task' -H 'Content-Type: application/json' -d '{
    "challenge_repo_url": "git@github.com:aixcc-finals/example-libpng.git",
    "challenge_repo_base_ref": "0cc367aaeaac3f888f255cee5d394968996f736e",
    "challenge_repo_head_ref": "fdacd5a1dcff42175117d674b0fda9f8a005ae88",
    "fuzz_tooling_url": "https://github.com/aixcc-finals/oss-fuzz-aixcc.git",
    "fuzz_tooling_ref": "d5fbd68fca66e6fa4f05899170d24e572b01853d",
    "fuzz_tooling_project_name": "libpng",
    "duration": 3600
}'
# Zookeeper
curl -u 11111111-1111-1111-1111-111111111111:pY8rLk7FvQ2hZm9GwUx3Ej5BnTcV4So0 -X 'POST' 'https://<team-moniker>.tasker.aixcc.tech/webhook/trigger_task' -H 'Content-Type: application/json' -d '{
    "challenge_repo_url": "git@github.com:aixcc-finals/afc-zookeeper.git",
    "challenge_repo_base_ref": "d19cef9ca254a4c1461490ed8b82ffccfa57461d",
    "challenge_repo_head_ref": "5ee4f185d0431cc88f365ce779aa04a87fe7690f",
    "fuzz_tooling_url": "https://github.com/aixcc-finals/oss-fuzz-aixcc.git",
    "fuzz_tooling_ref": "challenge-state/zk-ex1-delta-01",
    "fuzz_tooling_project_name": "zookeeper",
    "duration": 3600
}'
# Libxml2
curl -u 11111111-1111-1111-1111-111111111111:pY8rLk7FvQ2hZm9GwUx3Ej5BnTcV4So0 -X 'POST' 'https://<team-moniker>.tasker.aixcc.tech/webhook/trigger_task' -H 'Content-Type: application/json' -d '{
    "challenge_repo_url": "git@github.com:aixcc-finals/afc-libxml2.git",
    "challenge_repo_base_ref": "792cc4a1462d4a969d9d38bd80a52d2e4f7bd137",
    "challenge_repo_head_ref": "9d1cb67c31933ee5ae3ee458940f7dbeb2fde8b8",
    "fuzz_tooling_url": "https://github.com/aixcc-finals/oss-fuzz-aixcc.git",
    "fuzz_tooling_ref": "challenge-state/lx-ex1-delta-01",
    "fuzz_tooling_project_name": "libxml2",
    "duration": 3600
}'

```

## IMPORTANT NOTE

If you are using this test server, don’t forget to change your Competition API URL back to `https://api.tail7e9b4c.ts.net` prior to the start of the round.
