# ADR-001: Use independent `codex exec` processes

**Status:** Accepted

## Context

Native custom-agent routing can inherit stale or parent configuration and may not expose enough runtime metadata consistently. The control plane needs exact model, effort, sandbox, output schema, and process evidence.

## Decision

Use a separate `codex exec` process for every planner, worker, reviewer, and canary invocation. Pass the requested model and effort explicitly, capture JSONL, and attest runtime metadata when exposed.

## Consequences

- Clear process and artifact boundaries.
- No automatic parent context inheritance; task packets must be complete.
- More deterministic routing and easier testing.
- Small orchestration overhead, offset by cheaper worker routing and bounded context.
