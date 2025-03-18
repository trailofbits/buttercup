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
