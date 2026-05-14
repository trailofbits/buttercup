---
description: Run a Docker-only end-to-end smoke test of Buttercup against example-libpng with a low LLM budget, and monitor the pipeline.
argument-hint: "[--budget N] [--task-duration SEC] [--keep-up] [--no-build] [--skip-wait] [--sarif]"
allowed-tools: Bash(./scripts/e2e.sh:*), Bash(make e2e*), Bash(docker compose:*), Bash(cd dev/docker-compose && docker compose:*), Read
---

# /e2e — Docker-only end-to-end Buttercup run (example-libpng)

This command exercises the full Buttercup pipeline on the [example-libpng](https://github.com/tob-challenges/example-libpng) challenge **using Docker only — no Kubernetes/minikube**. It uses the `dev/docker-compose/` stack and a low LiteLLM budget (default **$3**), so an accidental run is cheap.

> **Host requirement:** x86_64. The fuzzer / patcher / seed-gen images build on `gcr.io/oss-fuzz-base/base-runner`, which is amd64-only. On aarch64 the build will fail with `exec format error` unless you install `qemu-user-static` + `binfmt` and set `DOCKER_DEFAULT_PLATFORM=linux/amd64` (and even then everything runs ~10× slower under emulation).

Mirrors the milestones in `.github/workflows/system-integration.yml`, but tails `docker compose logs` instead of `kubectl logs`.

## What it does

1. Checks for `docker`, `docker compose`, `curl`, and at least one LLM provider key (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, or `GEMINI_API_KEY`) in your env.
2. Writes `dev/docker-compose/.env` with the provider keys and `LITELLM_MAX_BUDGET=$BUDGET` (default `3`).
3. Builds and starts every service in `dev/docker-compose/compose.yaml` (redis, dind, litellm, task-server, task-downloader, scheduler, program-model, build-bot, fuzzer-bot, coverage-bot, tracer-bot, seed-gen, patcher, buttercup-ui).
4. POSTs the canned libpng `trigger_task` payload to `http://localhost:31323/webhook/trigger_task`.
5. Waits, in order, for these scheduler/seed-gen log markers (timeout configurable per phase):
   - `Processing build output for type FUZZER` — fuzzer build done
   - `POV submission response: pov_id=` — vulnerability found and POV submitted
   - `Updated POV status. New status PASSED` — POV accepted by competition API
   - `Copied N files to corpus` — seed-gen produced seeds
   - `Appending patch for task` — patch generated
   - approves the patch via `POST /v1/task/<task_id>/patch/<patch_id>/approve`
   - `Patch passed` — patch accepted
   - `Bundle submission response: bundle_id=` — bundle submitted
6. With `--sarif`, also sends a SARIF broadcast and waits for `Matching SARIF submission response`.
7. Prints a colored summary and tears the stack down with `docker compose down -v` (unless `--keep-up`).

## Run it

The driver is `scripts/e2e.sh`. The `Makefile` exposes `make e2e`.

```bash
# Plain run with the $3 budget default
make e2e

# Pass flags through the Makefile
make e2e E2E_ARGS="--budget 5 --keep-up"

# Or call the script directly
./scripts/e2e.sh --budget 3 --task-duration 1800
./scripts/e2e.sh --skip-wait --keep-up   # just bring the stack up + submit task
./scripts/e2e.sh --sarif                 # also exercise the SARIF flow
```

The script writes/overwrites `dev/docker-compose/.env` on each run.

## Monitoring while it's running

The script already streams milestone progress to its own stdout. For finer-grained visibility while it runs:

```bash
# All services, follow
cd dev/docker-compose && docker compose logs -f

# Just the scheduler (most milestones live here)
cd dev/docker-compose && docker compose logs -f scheduler

# Patcher, seed-gen, fuzzer-bot, program-model
cd dev/docker-compose && docker compose logs -f patcher seed-gen fuzzer-bot program-model

# LiteLLM spend tracking
cd dev/docker-compose && docker compose logs -f litellm | grep -i 'spend\|budget'
```

The web UI is at `http://localhost:31323` (no port-forward needed — it's published on the host).

## Tearing down

```bash
cd dev/docker-compose && docker compose down -v --remove-orphans
```

`scripts/e2e.sh` does this automatically on exit unless you pass `--keep-up`.

## When you invoke /e2e

When the user runs `/e2e`, default behavior:

1. Run `./scripts/e2e.sh $ARGUMENTS` (forwarding any flags the user passed).
2. While it runs, surface key transitions to the user. The script's own output already prints `[e2e] Reached: …` for each milestone — relay those as they arrive.
3. If the run fails on a milestone, fetch the last ~50 lines of the relevant service:
   - `cd dev/docker-compose && docker compose logs --tail=50 <service>`
4. If the user asks to keep digging, expand the watch with `docker compose logs -f <service>` until the user is satisfied.
5. On success, summarize the milestones reached and remind the user the stack is already torn down (or still up, if `--keep-up`).
