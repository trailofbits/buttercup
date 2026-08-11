---
name: submit-oss-fuzz-task
description: Submit a task against an OSS-Fuzz project to a running local Buttercup CRS via scripts/task_oss_fuzz.sh. Use when the user wants to run / submit / kick off / smoke-test a task on an oss-fuzz project (e.g. "run libpng", "submit an oss-fuzz task for libucl"). Assumes the system is already up; if it is not, start it first with the `start-buttercup-compose` skill.
allowed-tools:
  - Bash
  - AskUserQuestion
---

# Submit an OSS-Fuzz task to a running Buttercup

Submit a task to an already-running CRS through `scripts/task_oss_fuzz.sh`. Run
commands **from the repository root**.

If the system is not running yet, bring it up first with the
`start-buttercup-compose` skill, then come back here.

## Step 0 — Confirm the CRS is up

The script posts to the `buttercup-ui` webhook on `127.0.0.1:31323`. Verify it
responds first:

```bash
curl -fsS -o /dev/null http://127.0.0.1:31323/ && echo "CRS up" || echo "CRS not reachable"
```

If it is not reachable, tell the user to start the system with the
`start-buttercup-compose` skill (or, if they remapped the port, pass `-u <url>`
or set `BUTTERCUP_API_URL`).

## Inputs to gather

Parse from the user's request; ask only if a required one is missing.

- **project** (required): the OSS-Fuzz project name (directory under `projects/`
  in oss-fuzz), e.g. `libpng`, `libucl`.
- **source repo / refs** (optional): `--repo-url` + `--head-ref`, and
  `--base-ref` for delta mode. Omit for a minimal task (the oss-fuzz Dockerfile
  fetches the source).
- **duration** (optional): seconds, default 1800.

## Step 1 — Submit the task

The script defaults the fuzzing tooling to upstream `google/oss-fuzz @ master`,
so only `-p` is required:

```bash
# minimal
./scripts/task_oss_fuzz.sh -p <project>

# full mode with explicit source
./scripts/task_oss_fuzz.sh -p <project> -r <repo-url> -b <head-ref> [-d <seconds>]

# delta mode (analyze base..head)
./scripts/task_oss_fuzz.sh -p <project> -r <repo-url> -B <base-ref> -b <head-ref>
```

Show the user the exact command and the JSON the server accepts. To preview
without submitting, add `--dry-run`. Report the webhook response (a task id /
message id) verbatim.

## Step 2 — Report next steps

Tell the user how to observe progress and where results land:

```bash
# follow the pipeline
docker compose -f dev/docker-compose/compose.yaml logs -f scheduler

# dashboard
open http://127.0.0.1:31323/
```

Submitted artifacts (PoVs/patches/bundles) land under `tasks_storage/` in the
repo root and are downloadable from the dashboard.

## Notes & gotchas

- `harnesses_included` is **not** a field on the server's `Challenge` model — the
  script intentionally omits it. Required fields are `fuzz_tooling_url`,
  `fuzz_tooling_ref`, `fuzz_tooling_project_name`, `duration`; supplying
  `challenge_repo_base_ref` switches the task to delta mode and then requires the
  repo url + head ref.
- The script's default API URL (`http://127.0.0.1:31323`) already matches the
  compose port mapping — no `kubectl port-forward` needed (that is for the k8s
  deployment). Override with `-u <url>` or `BUTTERCUP_API_URL`.
