# ADR 0002: Defer Langfuse; manifest is the Week 1 tracing story

## Status
Accepted (2026-07-17)

## Context
plan.md §6 specifies Langfuse (self-hosted or cloud free tier) for per-call tracing, and §7 lists
it in `docker-compose.yml` alongside Postgres. Self-hosted Langfuse is a multi-container stack
(Postgres, ClickHouse, Redis, MinIO, the Langfuse server) — heavy for a Week 1 skeleton that has
no LLM calls to trace yet (extraction, the first stage that calls a model, starts Week 2).

## Decision
Ship Week 1 with `docker-compose.yml` running only `db` (Postgres+pgvector). The
`Supervisor`/`Manifest` (`dissonance/supervisor/`) is the run-level observability story for now:
every run writes `runs/<run_id>/manifest.json` with stage costs, counts, and timing. Add Langfuse
in Week 2 when extraction starts making real model calls that need per-call traces (prompt
version, tokens, latency) rather than just per-stage totals.

## Rationale
- Nothing to trace yet at the call level — adding the stack now is pure setup cost against no
  payoff until Week 2.
- The manifest already satisfies plan.md §4's "every run writes a manifest" invariant.
- Replay (plan.md Week 5) depends on Langfuse traces + local cache; that's explicitly a Week 5
  concern, not Week 1.

## Consequences
- `docker-compose.yml` will grow a `langfuse` service (+ its dependencies) in Week 2 — tracked
  here so it isn't a surprise.
- Until then, cost/latency per *LLM call* isn't visible, only per *stage* (via the manifest). Fine
  for scouts (no LLM calls); revisit before extraction ships.
