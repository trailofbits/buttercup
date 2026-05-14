---
name: langfuse-error-analysis
description: Deep-dive error analysis of an LLM pipeline or AI application using Langfuse traces.
  Use this skill whenever the user wants to understand why their AI system is producing
  bad outputs, where their pipeline is failing, how to categorise or label failures,
  what to prioritise fixing, or how to set up evaluators. Also trigger for "review my
  traces", "my outputs look wrong", "help me debug my LLM app", "I want to analyse
  errors", "build a failure taxonomy", "what's going wrong with my pipeline", or any
  request to systematically inspect, annotate, or score Langfuse traces. If the user
  is trying to understand or improve the quality of an AI system's outputs, use this skill.
---

# Error Analysis

## Primary Guide

**1. Fetch the guide in this blogpost**

https://langfuse.com/guides/cookbook/error-analysis-llm-applications.md

If fetch is not available query for langfuse.com error analysis guide

Read it in full. It defines the authoritative 5-step process (sample selection → open coding → clustering → labelling → deciding what to fix).

**2. Guide the user through this step by step**

You as a coding agent and the user go through this together to perform a full error analysis with their data in langfuse. Do everything you can achieve via CLI (look up traces, create annotation queues, ...) for the user. Provide them with direct links to UI wherever their action is required. Be proactive and narrate what is going on for the user. 

## Rules CRITICAL
Use Langfuse CLI wherever possible
Use charts where possible to display data

---

## Langfuse Implementation Notes

The guide describes the process. These notes cover the Langfuse-specific API and CLI mechanics required to execute it.

### Credentials

```bash
echo $LANGFUSE_PUBLIC_KEY   # pk-lf-...
echo $LANGFUSE_SECRET_KEY   # sk-lf-...
echo $LANGFUSE_HOST         # https://cloud.langfuse.com (EU), https://us.cloud.langfuse.com (US), https://jp.cloud.langfuse.com (JP) or self-hosted
```

If not set, check `.env` in the project root: `export $(grep -v '^#' .env | xargs)`. If `LANGFUSE_BASE_URL` is used instead of `LANGFUSE_HOST`, run `export LANGFUSE_HOST="$LANGFUSE_BASE_URL"`.

```bash
AUTH=$(echo -n "${LANGFUSE_PUBLIC_KEY}:${LANGFUSE_SECRET_KEY}" | base64)

# Verify before proceeding
STATUS=$(curl -s -o /dev/null -w "%{http_code}" \
  -H "Authorization: Basic $AUTH" \
  "${LANGFUSE_HOST}/api/public/projects")
echo "Auth check: $STATUS"
```

If status is not `200`, stop and ask the user to check their credentials and host before continuing.

### Annotation target: OBSERVATION versus TRACE

> **CRITICAL:** In OpenTelemetry-instrumented apps, trace-level `input`/`output` can be null — content often lives in a GENERATION observation. Always consider if the right objectType to add is `objectType: OBSERVATION` pointing to the GENERATION observation ID to annotation queues. 

### Annotation queues

> **CRITICAL:** Queues cannot be updated or deleted after creation. Create score configs first, then the queue with all config IDs. To add new configs later, create a new queue.


**Always give the user a direct link immediately after creating a queue:**

| Host | URL pattern |
|------|-------------|
| EU cloud | `https://cloud.langfuse.com/project/<projectId>/annotation-queues/<queueId>` |
| US cloud | `https://us.cloud.langfuse.com/project/<projectId>/annotation-queues/<queueId>` |
| Self-hosted | `<LANGFUSE_HOST>/project/<projectId>/annotation-queues/<queueId>` |

Instruction to give: *"Please open code the first ~50 examples. For each trace, write what you observe in the `open_coding` field (describe behaviour, don't diagnose root causes), then set `pass_fail_assessment` to Pass or Fail."*


### Prompt fixes

When a category warrants a prompt fix, always offer the user two options:
1. Create it as a versioned prompt in Langfuse (tracked, usable via the prompt API)
2. Draft the specific text change for them to review and apply

### Setup evaluators

When a category warrants an evaluator setup, propose the type of evaluator and offer to set it up for user via CLI


### Common gotchas

| Mistake | Fix |
|---------|-----|
| `objectType: TRACE` in queue | Use `objectType: OBSERVATION` with GENERATION obs ID |
| Creating score config without checking existing | `GET /api/public/score-configs` first; can't delete |
| Queue created before score configs | Create configs → collect IDs → create queue |
| `--limit` > 100 on traces list | API hard cap; paginate with `--page` |
| No rate limiting on queue item creation | `sleep 0.4` between calls to avoid 429 |
