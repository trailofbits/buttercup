#!/bin/bash
#
# Trigger a Buttercup task against an arbitrary OSS-Fuzz project.
#
# By default this points the fuzzing tooling at upstream
# https://github.com/google/oss-fuzz @ master, so you only need to pass the
# project name (the directory under projects/ in oss-fuzz). Optionally provide
# the challenge source repo/refs; supplying a base ref switches the task to
# "delta" mode (analyze the diff between base and head).
#
# Examples:
#   # Full mode against an upstream oss-fuzz project
#   ./task_oss_fuzz.sh -p libpng -r https://github.com/pnggroup/libpng -b libpng16
#
#   # Minimal (project only; relies on oss-fuzz Dockerfile to fetch source)
#   ./task_oss_fuzz.sh -p libucl
#
#   # Delta mode (analyze base..head) with a custom oss-fuzz fork
#   ./task_oss_fuzz.sh -p libxml2 \
#       -r https://github.com/tob-challenges/afc-libxml2 \
#       -B <base_sha> -b <head_sha> \
#       -t https://github.com/tob-challenges/oss-fuzz-aixcc -f <tooling_ref>
#
#   # Inspect the payload without sending it
#   ./task_oss_fuzz.sh -p libpng -r https://github.com/pnggroup/libpng -b libpng16 --dry-run

set -euo pipefail

# --- defaults -----------------------------------------------------------------
API_URL="${BUTTERCUP_API_URL:-http://127.0.0.1:31323}"
TOOLING_URL="https://github.com/google/oss-fuzz"
TOOLING_REF="master"
DURATION=1800

PROJECT=""
REPO_URL=""
HEAD_REF=""
BASE_REF=""
NAME=""
DRY_RUN=0

usage() {
    cat <<'EOF'
Trigger a Buttercup task against an arbitrary OSS-Fuzz project.

Defaults point the fuzzing tooling at upstream google/oss-fuzz @ master, so
the only required argument is the project name. Supplying a base ref switches
the task into "delta" mode (analyze base..head).

Usage: task_oss_fuzz.sh -p PROJECT [options]

Options:
  -p, --project NAME        OSS-Fuzz project name (dir under projects/)   [required]
  -r, --repo-url URL        Challenge source repo URL
  -b, --head-ref REF        Source branch/tag/commit to analyze
  -B, --base-ref REF        "Clean" base ref -> enables delta mode
  -t, --tooling-url URL     oss-fuzz (fork) URL   [default: google/oss-fuzz]
  -f, --tooling-ref REF     oss-fuzz git ref      [default: master]
  -d, --duration SECONDS    Analysis time limit   [default: 1800]
  -n, --name NAME           Friendly task name (optional)
  -u, --api-url URL         CRS webhook base URL  [default: $BUTTERCUP_API_URL or
                            http://127.0.0.1:31323]
      --dry-run             Print the JSON payload and exit
  -h, --help                Show this help

Examples:
  task_oss_fuzz.sh -p libpng -r https://github.com/pnggroup/libpng -b libpng16
  task_oss_fuzz.sh -p libucl
  task_oss_fuzz.sh -p libpng -r https://github.com/pnggroup/libpng -b libpng16 --dry-run
EOF
    exit "${1:-0}"
}

# --- arg parsing --------------------------------------------------------------
while [[ $# -gt 0 ]]; do
    case "$1" in
        -p|--project)     PROJECT="$2"; shift 2 ;;
        -r|--repo-url)    REPO_URL="$2"; shift 2 ;;
        -b|--head-ref)    HEAD_REF="$2"; shift 2 ;;
        -B|--base-ref)    BASE_REF="$2"; shift 2 ;;
        -t|--tooling-url) TOOLING_URL="$2"; shift 2 ;;
        -f|--tooling-ref) TOOLING_REF="$2"; shift 2 ;;
        -d|--duration)    DURATION="$2"; shift 2 ;;
        -n|--name)        NAME="$2"; shift 2 ;;
        -u|--api-url)     API_URL="$2"; shift 2 ;;
        --dry-run)        DRY_RUN=1; shift ;;
        -h|--help)        usage 0 ;;
        *) echo "Unknown argument: $1" >&2; usage 1 ;;
    esac
done

if [[ -z "$PROJECT" ]]; then
    echo "Error: --project is required" >&2
    usage 1
fi
if [[ -n "$BASE_REF" && ( -z "$REPO_URL" || -z "$HEAD_REF" ) ]]; then
    echo "Error: delta mode (--base-ref) requires --repo-url and --head-ref" >&2
    exit 1
fi

# --- build JSON payload -------------------------------------------------------
# Prefer jq for safe escaping; fall back to manual assembly if jq is absent.
if command -v jq >/dev/null 2>&1; then
    PAYLOAD=$(jq -n \
        --arg name "$NAME" \
        --arg repo "$REPO_URL" \
        --arg head "$HEAD_REF" \
        --arg base "$BASE_REF" \
        --arg turl "$TOOLING_URL" \
        --arg tref "$TOOLING_REF" \
        --arg proj "$PROJECT" \
        --argjson dur "$DURATION" \
        '{
            fuzz_tooling_url: $turl,
            fuzz_tooling_ref: $tref,
            fuzz_tooling_project_name: $proj,
            duration: $dur
        }
        + (if $name != "" then {name: $name} else {} end)
        + (if $repo != "" then {challenge_repo_url: $repo} else {} end)
        + (if $head != "" then {challenge_repo_head_ref: $head} else {} end)
        + (if $base != "" then {challenge_repo_base_ref: $base} else {} end)')
else
    fields="\"fuzz_tooling_url\": \"$TOOLING_URL\""
    fields+=", \"fuzz_tooling_ref\": \"$TOOLING_REF\""
    fields+=", \"fuzz_tooling_project_name\": \"$PROJECT\""
    fields+=", \"duration\": $DURATION"
    [[ -n "$NAME"     ]] && fields+=", \"name\": \"$NAME\""
    [[ -n "$REPO_URL" ]] && fields+=", \"challenge_repo_url\": \"$REPO_URL\""
    [[ -n "$HEAD_REF" ]] && fields+=", \"challenge_repo_head_ref\": \"$HEAD_REF\""
    [[ -n "$BASE_REF" ]] && fields+=", \"challenge_repo_base_ref\": \"$BASE_REF\""
    PAYLOAD="{ $fields }"
fi

if [[ "$DRY_RUN" -eq 1 ]]; then
    echo "$PAYLOAD"
    exit 0
fi

echo "Submitting task to ${API_URL}/webhook/trigger_task ..." >&2
curl -fsS -X POST "${API_URL}/webhook/trigger_task" \
    -H 'Content-Type: application/json' \
    -d "$PAYLOAD"
echo
