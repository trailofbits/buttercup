---
name: start-buttercup-compose
description: Start the Buttercup CRS locally with docker compose and wait until the task webhook is up. Use when the user wants to bring up / spin up / start the system locally with docker compose (e.g. "start buttercup", "bring the system up with compose", "spin up the CRS locally"). Defaults to prebuilt GHCR images; build-local on request. To submit a task afterwards, use the `submit-oss-fuzz-task` skill. Not for the Kubernetes/Helm deployment (that is `make deploy`).
allowed-tools:
  - Bash
  - Read
  - Edit
  - AskUserQuestion
---

# Start Buttercup locally with docker compose

Bring the CRS up with docker compose and confirm it is ready to accept tasks.
Run every command **from the repository root** — the compose file lives in
`dev/docker-compose/`, but docker compose resolves its relative `env_file`/build
paths against the compose file's own directory, so passing
`-f dev/docker-compose/compose.yaml` from the root works and avoids `cd`.

After this skill finishes, submit a task with the `submit-oss-fuzz-task` skill.

## Inputs to gather

- **build mode** (optional): default is **prebuilt GHCR images** (fast, no local
  build). Use **build-local** only if the user wants their local code changes
  reflected — it is much slower.
- **image tag** (optional, prebuilt only): defaults to `main`.

## Step 1 — Require LLM keys in the compose `.env` (hard gate)

The stack reads `dev/docker-compose/.env` for LLM keys and interpolated vars.
Buttercup cannot do useful work (seed-gen, patcher) without at least one working
LLM provider key, so **this is a precondition: if none is configured, STOP here
and do not start the stack.**

First resolve the file. Prefer the `.env` in the current checkout. If it is
missing and we are in a git worktree, fall back to the **main worktree's** copy —
`.env` is gitignored, so it usually exists only in the primary checkout — and
copy it in. Only if neither exists, fall back to the template (placeholders,
which will fail the gate below):

```bash
ENV=dev/docker-compose/.env
if [ ! -f "$ENV" ]; then
  main_root=$(git worktree list --porcelain 2>/dev/null | awk '/^worktree /{print $2; exit}')
  if [ -n "$main_root" ] && [ "$main_root" != "$PWD" ] && [ -f "$main_root/$ENV" ]; then
    echo "Using .env from main worktree: $main_root/$ENV"
    cp "$main_root/$ENV" "$ENV"
  fi
fi
test -f "$ENV" || cp dev/docker-compose/env.template "$ENV"
```

(Copying — rather than symlinking — keeps the running stack pinned to the keys
that were present at start time; re-run this skill to pick up later changes to
the main `.env`.)

Then require at least one real provider key — a line whose value is neither empty
nor an `<INSERT...>` placeholder:

```bash
configured=$(grep -E '^(ANTHROPIC_API_KEY|OPENAI_API_KEY|GEMINI_API_KEY|AZURE_API_KEY)=' \
  dev/docker-compose/.env | grep -cvE '=\s*(<INSERT[^>]*>)?\s*$')
if [ "${configured:-0}" -eq 0 ]; then
  echo "ERROR: no LLM provider key set in dev/docker-compose/.env (all placeholders)." >&2
  echo "Set at least one of ANTHROPIC_API_KEY / OPENAI_API_KEY / GEMINI_API_KEY / AZURE_API_KEY, then re-run." >&2
  exit 1
fi
```

If the gate fails, do **not** proceed to Step 2. Tell the user exactly which
file to edit (`dev/docker-compose/.env`) and which keys to set, and stop. Only
continue once at least one real key is present.

## Step 2 — Start the stack

**Prebuilt (default):**

```bash
BUTTERCUP_IMAGE_TAG=main docker compose \
  -f dev/docker-compose/compose.yaml \
  -f dev/docker-compose/compose.prebuilt.yaml up -d
```

Substitute the requested tag for `main` if the user specified one.

**Build-local (only if requested):**

```bash
docker compose -f dev/docker-compose/compose.yaml up -d --build
```

The local build compiles every component and can take many minutes. If a build
fails on a missing `external/buttercup-cscope`, run
`git submodule update --init external/buttercup-cscope` and retry.

## Step 3 — Wait until the task webhook is up

`buttercup-ui` serves `/webhook/trigger_task` on `127.0.0.1:31323` and has no
compose healthcheck, so poll it. Allow more time on first run (image pulls or a
local build):

```bash
for i in $(seq 1 60); do
  if curl -fsS -o /dev/null http://127.0.0.1:31323/ ; then echo "UI ready"; break; fi
  sleep 5
done
```

If it never comes up, show recent logs and stop:
`docker compose -f dev/docker-compose/compose.yaml logs --tail=50 buttercup-ui`.

## Step 4 — Report status

Confirm the stack is up and tell the user what to do next:

```bash
# service status
docker compose -f dev/docker-compose/compose.yaml ps

# dashboard
open http://127.0.0.1:31323/

# follow the pipeline
docker compose -f dev/docker-compose/compose.yaml logs -f scheduler

# tear down
docker compose -f dev/docker-compose/compose.yaml down
```

State that a task can now be submitted with the `submit-oss-fuzz-task` skill.
