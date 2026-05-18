---
name: buttercup-langfuse
description: Buttercup-specific Langfuse wiring. Use when adding LLM tracing to a new LangChain/LangGraph entry point in this repo, attaching tags/metadata to existing chains, troubleshooting "no traces in Langfuse" against this codebase, or touching the Helm/values surface (`global.langfuse.*`, `langfuse-secret.yaml`, `common-env.yaml`). For platform-level Langfuse usage (CLI, instrumentation patterns generally, prompt migration, SDK upgrades), use the `langfuse` skill instead.
---

# Langfuse wiring in Buttercup

How *this repo* integrates Langfuse. For general Langfuse platform/CLI/instrumentation guidance, defer to the `langfuse` skill — this skill only covers Buttercup-local conventions.

Tracing is always optional at runtime: if the env vars are unset or the host is unreachable, callbacks resolve to an empty list and code paths are unaffected. Follow the existing pattern — do not introduce a parallel integration.

## The one helper to use

`buttercup.common.llm.get_langfuse_callbacks() -> list[BaseCallbackHandler]`

- Defined in `common/src/buttercup/common/llm.py`
- `@functools.cache`d — cheap to call repeatedly, but the auth/connectivity probe runs only once per process
- Returns `[]` when Langfuse is disabled, misconfigured, or unreachable
- Internally: runs `is_langfuse_available()` (checks `LANGFUSE_HOST`, then HTTP-probes `/api/public/ingestion`), constructs `langfuse.langchain.CallbackHandler()`, then verifies credentials via `langfuse_auth_check()`

Do **not** instantiate `CallbackHandler` directly or read the env vars yourself. Always go through `get_langfuse_callbacks()`.

## Standard wiring pattern

Attach the callbacks via `RunnableConfig` on the compiled chain/graph. Canonical examples in the repo:

- `patcher/src/buttercup/patcher/agents/leader.py` — LangGraph with tags + metadata
- `seed-gen/src/buttercup/seed_gen/seed_explore.py` — minimal LangGraph
- `seed-gen/src/buttercup/seed_gen/task.py`, `vuln_base_task.py`, `seed_init.py` — variants

Minimal form:

```python
from langchain_core.runnables import RunnableConfig
from buttercup.common.llm import get_langfuse_callbacks

llm_callbacks = get_langfuse_callbacks()
chain = workflow.compile().with_config(
    RunnableConfig(tags=["<short-task-name>"], callbacks=llm_callbacks),
)
chain.invoke(state)
```

Rich form (patcher-style) — `tags` for filtering, `metadata` for searchable fields in the Langfuse UI:

```python
chain = patch_team.compile().with_config(
    RunnableConfig(
        callbacks=llm_callbacks,
        tags=["patch_team", challenge.name, task_id, internal_patch_id],
        metadata={
            "task_id": task_id,
            "internal_patch_id": internal_patch_id,
            "challenge_project_name": challenge.name,
        },
        recursion_limit=RECURSION_LIMIT,
        configurable={...},
    ),
)
```

Conventions:
- First tag is the workflow/team name (`"patch_team"`, `"seed-explore"`, …). Identifies the *kind* of run in the Langfuse UI.
- Subsequent tags are high-cardinality identifiers (task_id, challenge name, patch id) for drill-down.
- `metadata` mirrors the identifier tags as structured fields — tags are best for filtering, metadata for inspection.
- Don't reach for `langfuse.observe()` decorators or other SDK entry points — this codebase routes everything through the LangChain callback handler.

## When you're adding a NEW LangChain/LangGraph entry point

1. Import `get_langfuse_callbacks` from `buttercup.common.llm`.
2. Call it once near where you compile the chain/graph.
3. Pass through `RunnableConfig(callbacks=..., tags=[...], metadata={...})`.
4. Pick a workflow tag that doesn't collide with existing ones (`patch_team`, `seed-explore`, `seed-init`, `vuln-discovery`, …).
5. If the component runs in k8s, confirm its Deployment template pulls in the Langfuse env block (see below). Most existing components already do.

## Deployment / config surface

Env vars (consumed by `get_langfuse_callbacks()`):
- `LANGFUSE_HOST` — base URL, e.g. `https://cloud.langfuse.com`
- `LANGFUSE_PUBLIC_KEY` (`pk-lf-...`)
- `LANGFUSE_SECRET_KEY` (`sk-lf-...`)

Where they're set:
- Local docker-compose: `dev/docker-compose/env.template`
- Local make-based deploy: `deployment/env.template` (gated by `LANGFUSE_ENABLED`)
- Kubernetes: `deployment/k8s/values.yaml` under `global.langfuse.{enabled,host,publicKey,secretKey}`
  - Rendered into the `<release>-langfuse-secrets` Secret by `deployment/k8s/templates/langfuse-secret.yaml`
  - Injected into pods via the `buttercup.env.langfuse` helper in `deployment/k8s/templates/common-env.yaml`
  - A new component's Deployment template must include that helper to get traces

Python dependency: `langfuse ~=4.0.1`, declared under `[project.optional-dependencies] full` in `common/pyproject.toml`. Provided via the `[full]` extra of `common`. Components that emit traces depend on `common[full]` (as patcher and seed-gen already do). Don't pin `langfuse` independently — re-use the extra.

## Debugging "I don't see traces"

Walk the chain top-to-bottom; the first failing step short-circuits everything downstream:

1. **`LANGFUSE_HOST` unset.** Logs: `"LangFuse not configured"`. Set the env var.
2. **Host unreachable / not Langfuse.** `is_langfuse_available()` POSTs to `/api/public/ingestion` and expects HTTP 401 (unauthenticated). Anything else → `False`. Check network reachability from the pod and that the URL is correct.
3. **Bad keys.** Logs: `"LangFuse authentication failed"`. `langfuse_auth_check()` POSTs the same endpoint with basic auth and expects HTTP 400 (authenticated but bad payload). 401 means wrong keys. Rotate the secret and re-apply.
4. **Callbacks not attached.** `get_langfuse_callbacks()` returned a handler, but the runnable was invoked without `RunnableConfig(callbacks=...)`. Grep the call site — easy to miss when refactoring.
5. **Wrong runnable.** Only LangChain/LangGraph runnables route through callbacks. Direct HTTP calls to OpenAI/LiteLLM bypass Langfuse entirely. If the new code path uses `httpx.post(...)` or similar, it won't trace — that's expected.
6. **Cache staleness.** All three helpers are `@functools.cache`d per process. If env vars change at runtime, the process must restart. In k8s this means rolling the pod after a secret change.

## What NOT to do

- Don't add a new `langfuse` direct dependency in a sibling component's `pyproject.toml` — depend on `common[full]` instead (as patcher and seed-gen do) to pull it in via the extra.
- Don't gate code paths on `is_langfuse_available()` — the empty-callback-list pattern already makes Langfuse a no-op when disabled.
- Don't pass the callback list into individual `llm.invoke()` calls when there's a parent chain — attach at the highest reasonable scope (the compiled workflow) so child runs nest correctly in the Langfuse UI.
- Don't conflate Langfuse with OpenTelemetry. They coexist: Langfuse for LLM trace nesting/prompt inspection, OTel (`buttercup.common.telemetry`) for system-level spans. `seed_explore.py` shows both wrapped around the same `chain.invoke(...)`.
