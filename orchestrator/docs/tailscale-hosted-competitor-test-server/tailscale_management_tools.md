# Tailscale Management Tools

Each team has access to a set of APIs to manage their Tailscale devices. You can use this tool to list devices, delete devices, and update hostnames of tailscale devices. Each endpoint uses the Competition API
credentials for your team.

List Devices

Lists devices on the tailnet for your team.

```bash
curl -u 11111111-1111-1111-1111-111111111111:pY8rLk7FvQ2hZm9GwUx3Ej5BnTcV4So0  https://<team-moniker>.tasker.aixcc.tech/tailscale/device/
```

Show Device

Shows information about a single device by name

```bash
curl -u 11111111-1111-1111-1111-111111111111:pY8rLk7FvQ2hZm9GwUx3Ej5BnTcV4So0  https://<team-moniker>.tasker.aixcc.tech/tailscale/device/team-moniker-foo
```

Rename Device

Change the hostname of a device on the tailnet

```bash
curl -u 11111111-1111-1111-1111-111111111111:pY8rLk7FvQ2hZm9GwUx3Ej5BnTcV4So0 -X PATCH  https://<team-moniker>.tasker.aixcc.tech/tailscale/device/team-moniker-foo -H 'Content-Type: application/json' -d '{"hostname":"team-moniker-exhibition2"}'
```

Delete Device

Deletes a specific device on the tailnet

```bash
curl -u 11111111-1111-1111-1111-111111111111:pY8rLk7FvQ2hZm9GwUx3Ej5BnTcV4So0 -X DELETE  https://<team-moniker>.tasker.aixcc.tech/tailscale/device/team-moniker-foo
```

Delete all Devices

**WARNING** This deletes all devices on your team’s tailnet.

```bash
curl -u 11111111-1111-1111-1111-111111111111:pY8rLk7FvQ2hZm9GwUx3Ej5BnTcV4So0 -X DELETE  https://<team-moniker>.tasker.aixcc.tech/tailscale/device/
```
