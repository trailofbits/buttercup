#!/usr/bin/env bash
# scripts/e2e.sh — Run the full Buttercup pipeline against example-libpng using
# the dev docker-compose stack (no Kubernetes required).
#
# Uses the prebuilt component images published to GHCR (via the
# compose.prebuilt.yaml overlay) instead of building them locally, so a run
# does not depend on a working local image build.
#
# This mirrors the milestones checked by .github/workflows/system-integration.yml
# but reads docker-compose logs instead of `kubectl logs`.

set -u
set -o pipefail

###############################################################################
# Config & defaults
###############################################################################

# Resolve repo root from this script's location.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
COMPOSE_DIR="${REPO_ROOT}/dev/docker-compose"
ENV_FILE="${COMPOSE_DIR}/.env"

# Defaults — overridable via flags or environment.
#
# BUDGET: a full run through patch generation costs ~$10 of LLM spend; $3 is
# exhausted during/just after POV, so anything past seed-gen would always time
# out. Default to 10 so the whole pipeline (incl. patch+bundle) is reachable.
#
# TASK_DURATION: the CRS discards a task's work once its deadline passes. On
# normal hardware build->POV->seed-gen->patch exceeds 30 min, so an 1800s task
# expires mid-patch ("task expired/cancelled? Will discard") and never reaches
# patch/bundle. Default to 7200 (2h) so the task outlives the pipeline.
BUDGET="${LITELLM_MAX_BUDGET:-10}"
TASK_DURATION="${E2E_TASK_DURATION:-7200}"

# Prebuilt GHCR images instead of local builds (compose.prebuilt.yaml overlay).
IMAGE_TAG="${BUTTERCUP_IMAGE_TAG:-main}"

DO_PULL=1

# Internal milestone timeouts (seconds). Bundle submission is quick; the rest
# (build, vuln, seed-gen, patch) can each take a while on a low-budget run.
MILESTONE_TIMEOUT=1800
BUNDLE_TIMEOUT=300

# Temp file for the trigger_task HTTP response; cleaned up on exit.
TASK_RESP=""

###############################################################################
# Logging
###############################################################################

if [[ -t 1 ]]; then
    C_RST=$'\033[0m'; C_RED=$'\033[1;31m'; C_GRN=$'\033[1;32m'
    C_YLW=$'\033[1;33m'; C_BLU=$'\033[1;36m'; C_DIM=$'\033[2m'
else
    C_RST=""; C_RED=""; C_GRN=""; C_YLW=""; C_BLU=""; C_DIM=""
fi

log()    { printf '%s[e2e]%s %s\n' "$C_BLU" "$C_RST" "$*"; }
ok()     { printf '%s[e2e]%s %s\n' "$C_GRN" "$C_RST" "$*"; }
warn()   { printf '%s[e2e]%s %s\n' "$C_YLW" "$C_RST" "$*" >&2; }
err()    { printf '%s[e2e]%s %s\n' "$C_RED" "$C_RST" "$*" >&2; }
dim()    { printf '%s[e2e]%s %s%s%s\n' "$C_BLU" "$C_RST" "$C_DIM" "$*" "$C_RST"; }

###############################################################################
# Usage
###############################################################################

usage() {
    cat <<EOF
Usage: scripts/e2e.sh [options]

Runs an end-to-end smoke test of Buttercup against example-libpng using
docker-compose (no Kubernetes). Monitors scheduler/seed-gen logs for the
milestones tracked by .github/workflows/system-integration.yml.

Options:
  --budget DOLLARS          LiteLLM per-user max budget (default: $BUDGET)
  --task-duration SECONDS   How long the CRS should fuzz (default: $TASK_DURATION)
  --image-tag TAG           Prebuilt GHCR image tag to run (default: $IMAGE_TAG)
  --no-pull                 Skip 'docker compose pull' (use already-pulled images)
  -h, --help                Print this help

Required environment (at least one provider key):
  ANTHROPIC_API_KEY   and/or   OPENAI_API_KEY   and/or   GEMINI_API_KEY

Optional:
  BUTTERCUP_IMAGE_TAG  Prebuilt GHCR image tag (default: main; same as --image-tag)
  LANGFUSE_HOST, LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY

The script writes ${ENV_FILE} from the values above each run.
EOF
}

###############################################################################
# Argument parsing
###############################################################################

while [[ $# -gt 0 ]]; do
    case "$1" in
        --budget)            BUDGET="$2"; shift 2 ;;
        --task-duration)     TASK_DURATION="$2"; shift 2 ;;
        --image-tag)         IMAGE_TAG="$2"; shift 2 ;;
        --no-pull)           DO_PULL=0; shift ;;
        -h|--help)           usage; exit 0 ;;
        *) err "Unknown argument: $1"; usage; exit 2 ;;
    esac
done

###############################################################################
# Pre-flight checks
###############################################################################

if ! command -v docker >/dev/null 2>&1; then
    err "docker is required but not installed."
    exit 1
fi
if ! docker compose version >/dev/null 2>&1; then
    err "'docker compose' v2 is required (not 'docker-compose')."
    exit 1
fi
if ! command -v curl >/dev/null 2>&1; then
    err "curl is required but not installed."
    exit 1
fi

# Read a value already present in the existing .env. Used so that variables
# not provided via the environment (e.g. LANGFUSE_*) are preserved across runs
# instead of being clobbered, since this script regenerates .env from scratch
# on every run.
prev_env() {
    [[ -f "$ENV_FILE" ]] || return 0
    sed -n "s/^$1=//p" "$ENV_FILE" | head -n1
}

# 1) Prefer the environment; 2) fall back to whatever is already in .env.
: "${ANTHROPIC_API_KEY:=$(prev_env ANTHROPIC_API_KEY)}"
: "${OPENAI_API_KEY:=$(prev_env OPENAI_API_KEY)}"
: "${GEMINI_API_KEY:=$(prev_env GEMINI_API_KEY)}"
: "${AZURE_API_BASE:=$(prev_env AZURE_API_BASE)}"
: "${AZURE_API_KEY:=$(prev_env AZURE_API_KEY)}"
: "${LANGFUSE_HOST:=$(prev_env LANGFUSE_HOST)}"
: "${LANGFUSE_PUBLIC_KEY:=$(prev_env LANGFUSE_PUBLIC_KEY)}"
: "${LANGFUSE_SECRET_KEY:=$(prev_env LANGFUSE_SECRET_KEY)}"

# Require at least one usable provider key. Checked *after* the .env fallback
# above so a key saved to .env on a prior run still counts.
provider_keys_set=0
for v in ANTHROPIC_API_KEY OPENAI_API_KEY GEMINI_API_KEY; do
    val="${!v:-}"
    if [[ -n "$val" && "$val" != "<INSERT_KEY>" ]]; then
        provider_keys_set=1
    fi
done
if [[ "$provider_keys_set" -eq 0 ]]; then
    err "No LLM provider key found. Set ANTHROPIC_API_KEY, OPENAI_API_KEY, or GEMINI_API_KEY."
    err "Tip: 'export ANTHROPIC_API_KEY=...; scripts/e2e.sh' or add it to ${ENV_FILE} first."
    exit 1
fi

# 3) Final placeholders if still unset after both env and .env. Keys left at
# the placeholder so litellm still loads its config (some models will fail at
# request time, others will succeed). LANGFUSE_* are intentionally left unset
# here: empty lines are NOT written to .env below, so a run without them set
# never clobbers LANGFUSE_* the user previously had in .env.
: "${ANTHROPIC_API_KEY:=<INSERT_KEY>}"
: "${OPENAI_API_KEY:=<INSERT_KEY>}"
: "${GEMINI_API_KEY:=<INSERT_KEY>}"
: "${AZURE_API_BASE:=<INSERT_HOST>}"
: "${AZURE_API_KEY:=<INSERT_KEY>}"
: "${LANGFUSE_HOST:=}"
: "${LANGFUSE_PUBLIC_KEY:=}"
: "${LANGFUSE_SECRET_KEY:=}"

###############################################################################
# .env generation
###############################################################################

log "Writing ${ENV_FILE} (LITELLM_MAX_BUDGET=\$${BUDGET})"
{
    echo "# Generated by scripts/e2e.sh on $(date -Is)"
    # litellm master key — internal to the local stack, not user-facing.
    echo "BUTTERCUP_LITELLM_KEY=sk-1234"
    echo "ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}"
    echo "OPENAI_API_KEY=${OPENAI_API_KEY}"
    echo "GEMINI_API_KEY=${GEMINI_API_KEY}"
    echo "AZURE_API_BASE=${AZURE_API_BASE}"
    echo "AZURE_API_KEY=${AZURE_API_KEY}"
    echo "LITELLM_MAX_BUDGET=${BUDGET}"
    # Only emit LANGFUSE_* when we actually have a value, so a run without
    # them set leaves no empty LANGFUSE_HOST= behind to disable telemetry.
    [[ -n "$LANGFUSE_HOST" ]]       && echo "LANGFUSE_HOST=${LANGFUSE_HOST}"
    [[ -n "$LANGFUSE_PUBLIC_KEY" ]] && echo "LANGFUSE_PUBLIC_KEY=${LANGFUSE_PUBLIC_KEY}"
    [[ -n "$LANGFUSE_SECRET_KEY" ]] && echo "LANGFUSE_SECRET_KEY=${LANGFUSE_SECRET_KEY}"
    true
} > "$ENV_FILE"

###############################################################################
# docker compose helpers
###############################################################################

# Always run compose from the compose dir so relative includes resolve.
# The compose.prebuilt.yaml overlay swaps every locally-built service for its
# prebuilt GHCR image, so nothing is built locally.
dc() {
    (cd "$COMPOSE_DIR" \
        && BUTTERCUP_IMAGE_TAG="$IMAGE_TAG" \
           docker compose -f compose.yaml -f compose.prebuilt.yaml "$@")
}

on_exit() {
    rc=$?
    [[ -n "$TASK_RESP" ]] && rm -f "$TASK_RESP"
    log "Tearing the stack down (docker compose down -v)"
    dc down -v --remove-orphans || true
    if [[ $rc -ne 0 ]]; then
        err "e2e run finished with exit code $rc"
    fi
    exit $rc
}
trap on_exit EXIT INT TERM

###############################################################################
# Bring the stack up
###############################################################################

if [[ "$DO_PULL" -eq 1 ]]; then
    log "Pulling prebuilt component images from GHCR (tag: ${IMAGE_TAG})"
    if ! dc pull; then
        err "docker compose pull failed for tag '${IMAGE_TAG}'."
        err "Check that the tag exists at ghcr.io/trailofbits/buttercup/* and that"
        err "you can reach GHCR (private images need 'docker login ghcr.io')."
        err "Override with --image-tag <branch-or-tag> or BUTTERCUP_IMAGE_TAG=..."
        exit 1
    fi
fi

log "Starting services"
if ! dc up -d; then
    err "docker compose up failed. Check 'docker compose ps' / logs."
    exit 1
fi

# Wait for the buttercup-ui task webhook to be reachable.
log "Waiting for buttercup-ui to accept connections on http://localhost:31323"
ui_up=0
for _ in $(seq 1 120); do
    if curl -sf -o /dev/null -m 2 http://localhost:31323/v1/ping/ 2>/dev/null \
        || curl -sf -o /dev/null -m 2 http://localhost:31323/ 2>/dev/null; then
        ui_up=1; break
    fi
    sleep 2
done
if [[ "$ui_up" -ne 1 ]]; then
    err "buttercup-ui did not come up on port 31323. Check 'docker compose logs buttercup-ui'."
    exit 1
fi
ok "buttercup-ui is up."

###############################################################################
# Submit the task
###############################################################################

TASK_JSON=$(cat <<EOF
{
    "challenge_repo_url": "https://github.com/tob-challenges/example-libpng",
    "challenge_repo_base_ref": "5bf8da2d7953974e5dfbd778429c3affd461f51a",
    "challenge_repo_head_ref": "challenges/lp-delta-01",
    "fuzz_tooling_url": "https://github.com/trail-of-forks/oss-fuzz",
    "fuzz_tooling_ref": "fix-libpng",
    "fuzz_tooling_project_name": "libpng",
    "duration": ${TASK_DURATION}
}
EOF
)

log "Submitting task to buttercup-ui /webhook/trigger_task"
TASK_RESP="$(mktemp)"
http_code=$(curl -s -o "$TASK_RESP" -w '%{http_code}' \
    -X POST 'http://127.0.0.1:31323/webhook/trigger_task' \
    -H 'Content-Type: application/json' \
    -d "$TASK_JSON")
resp_body=$(cat "$TASK_RESP" || true)
if [[ "$http_code" != "200" && "$http_code" != "201" ]]; then
    err "trigger_task returned HTTP $http_code: $resp_body"
    exit 1
fi
ok "Task accepted (HTTP $http_code). ${C_DIM}${resp_body}${C_RST}"

###############################################################################
# Milestone waiters
###############################################################################

# wait_for SERVICE PATTERN TIMEOUT_SEC LABEL
#
# Tails `docker compose logs <SERVICE>` until a line matching PATTERN appears
# or TIMEOUT_SEC elapses. Returns 0 on success, non-zero on timeout.
wait_for() {
    local service="$1" pattern="$2" timeout="$3" label="$4"
    local deadline=$(( $(date +%s) + timeout ))
    log "Waiting for milestone: ${label}  ${C_DIM}(service=${service}, timeout=${timeout}s)${C_RST}"

    while [[ $(date +%s) -lt $deadline ]]; do
        # --no-color so the grep matches plain text; --tail=all replays history.
        # NOTE: capture into a var with `|| true` instead of `if cmd | grep`.
        # Under `set -o pipefail`, `grep -m1` exits on the first match and the
        # upstream `docker compose logs` then dies with SIGPIPE (rc 141), which
        # would make the whole pipeline "fail" and the milestone never register
        # for high-volume services whose match is early in the stream.
        local match
        match="$(dc logs --no-color --no-log-prefix --tail=all "$service" 2>/dev/null \
            | grep -m1 -E "$pattern" || true)"
        if [[ -n "$match" ]]; then
            ok "Reached: ${label}"
            return 0
        fi
        sleep 15
    done

    err "Timed out after ${timeout}s waiting for: ${label}"
    err "Recent logs from ${service}:"
    dc logs --no-color --tail=50 "$service" >&2 || true
    return 1
}

# Capture a single matching log line (returns it on stdout, empty on miss).
capture_line() {
    local service="$1" pattern="$2"
    dc logs --no-color --no-log-prefix --tail=all "$service" 2>/dev/null \
        | grep -E "$pattern" | head -n1 || true
}

# wait_capture SERVICE PATTERN TIMEOUT_SEC LABEL
#
# Like capture_line, but polls until the pattern appears or TIMEOUT_SEC
# elapses, echoing the first matching line on stdout (empty on timeout).
# Progress goes to stderr so stdout stays just the captured line.
#
# Needed because `competition_patch_id=` is logged by the scheduler only
# *after* it builds, verifies and submits the patch — minutes after the
# "Appending patch for task" milestone. A one-shot capture right after that
# milestone always races and loses, so approval would always be skipped.
wait_capture() {
    local service="$1" pattern="$2" timeout="$3" label="$4"
    local deadline=$(( $(date +%s) + timeout ))
    log "Waiting to capture: ${label}  ${C_DIM}(service=${service}, timeout=${timeout}s)${C_RST}" >&2
    while [[ $(date +%s) -lt $deadline ]]; do
        local match
        match="$(dc logs --no-color --no-log-prefix --tail=all "$service" 2>/dev/null \
            | grep -m1 -E "$pattern" || true)"
        if [[ -n "$match" ]]; then
            printf '%s\n' "$match"
            return 0
        fi
        sleep 15
    done
    return 1
}

###############################################################################
# Walk through the pipeline
###############################################################################

declare -a SUMMARY=()
record() { SUMMARY+=("$1"); }

if wait_for scheduler \
    "Processing build output for type FUZZER" \
    "$MILESTONE_TIMEOUT" "fuzzer build processed"; then
    record "fuzzer-build: ok"
else
    record "fuzzer-build: TIMEOUT"
fi

# NOTE: match the structured summary line (`[i:task] pov_id=<id> ...`,
# logger.info), NOT the "POV submission response:" debug line whose payload is
# an API object repr that never contains a literal `pov_id=`.
if wait_for scheduler \
    "pov_id=" \
    "$MILESTONE_TIMEOUT" "vulnerability (POV) submitted"; then
    record "pov-submit: ok"
else
    record "pov-submit: TIMEOUT"
fi

if wait_for scheduler \
    "Updated POV status. New status PASSED" \
    "$MILESTONE_TIMEOUT" "POV accepted by competition API"; then
    record "pov-passed: ok"
else
    record "pov-passed: TIMEOUT"
fi

if wait_for seed-gen \
    "Copied [1-9][0-9]* files to corpus" \
    "$MILESTONE_TIMEOUT" "seed-gen produced seeds"; then
    record "seed-gen: ok"
else
    record "seed-gen: TIMEOUT"
fi

if wait_for scheduler \
    "Appending patch for task" \
    "$MILESTONE_TIMEOUT" "patch generated"; then
    record "patch-generated: ok"
else
    record "patch-generated: TIMEOUT"
fi

# Approve the patch (the local UI requires explicit approval, unlike scored
# rounds where it is automatic). competition_patch_id= only appears once the
# scheduler has built+verified+submitted the patch, well after the patch was
# generated, so poll for it rather than capturing once (which always races).
PATCH_LINE="$(wait_capture scheduler 'competition_patch_id=[0-9a-fA-F-]' \
    "$MILESTONE_TIMEOUT" "competition_patch_id (for approval)" || true)"
if [[ -n "$PATCH_LINE" ]]; then
    PATCH_ID=$(printf '%s' "$PATCH_LINE" | sed -n 's/.*competition_patch_id=\([^ ]*\).*/\1/p')
    # Task id is inside the first [...] block, after the last ':'.
    TASK_ID=$(printf '%s' "$PATCH_LINE" | sed -n 's/.*\[\([^]]*\)\].*/\1/p' | sed 's/^[^:]*://')
    if [[ -n "$PATCH_ID" && -n "$TASK_ID" ]]; then
        log "Approving patch ${C_DIM}task=${TASK_ID} patch=${PATCH_ID}${C_RST}"
        if curl -fsS -X POST \
            "http://127.0.0.1:31323/v1/task/${TASK_ID}/patch/${PATCH_ID}/approve" \
            >/dev/null; then
            record "patch-approve: ok"
        else
            record "patch-approve: HTTP fail"
        fi
    else
        warn "Could not extract patch/task ids from: $PATCH_LINE"
        record "patch-approve: skipped (parse fail)"
    fi
else
    warn "No competition_patch_id= line seen; skipping approval"
    record "patch-approve: skipped (no patch line)"
fi

if wait_for scheduler \
    "Patch passed" \
    "$MILESTONE_TIMEOUT" "patch accepted by competition API"; then
    record "patch-passed: ok"
else
    record "patch-passed: TIMEOUT"
fi

# NOTE: same as POV above — match the structured summary `bundle_id=<id>`
# (logger.info), not the "Bundle submission response:" debug object repr.
if wait_for scheduler \
    "bundle_id=" \
    "$BUNDLE_TIMEOUT" "bundle submitted"; then
    record "bundle-submit: ok"
else
    record "bundle-submit: TIMEOUT"
fi

###############################################################################
# Summary
###############################################################################

printf '\n%s===================== e2e summary =====================%s\n' "$C_BLU" "$C_RST"
for line in "${SUMMARY[@]}"; do
    if [[ "$line" == *": ok" ]]; then
        printf '  %s✓%s %s\n' "$C_GRN" "$C_RST" "$line"
    elif [[ "$line" == *": TIMEOUT" || "$line" == *"fail"* ]]; then
        printf '  %s✗%s %s\n' "$C_RED" "$C_RST" "$line"
    else
        printf '  %s•%s %s\n' "$C_YLW" "$C_RST" "$line"
    fi
done
printf '%s=======================================================%s\n' "$C_BLU" "$C_RST"

# Exit non-zero if any milestone failed.
for line in "${SUMMARY[@]}"; do
    if [[ "$line" == *": TIMEOUT" || "$line" == *"fail"* ]]; then
        exit 1
    fi
done
