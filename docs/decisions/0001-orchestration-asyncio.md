# ADR 0001: Plain asyncio, no orchestration framework

## Status
Accepted (2026-07-17)

## Context
plan.md §6 asks for orchestration to be picked and defended: LangGraph, or plain asyncio "if you
want to flex 'no framework'". The pipeline stages (planner → scouts → extraction → hunter →
adjudicator → synthesis) are a mix of embarrassingly-parallel fan-out (scouts, extraction) and
sequential stages with internal retry loops (extraction validation, adjudication escalation).

## Decision
Build orchestration on plain `asyncio` (`asyncio.gather`/`TaskGroup` for fan-out, plain control
flow for retries) instead of LangGraph or another graph framework.

## Rationale
- The loop patterns in plan.md §4 (retry-with-validator-feedback, tiered escalation, circuit
  breakers) are ordinary control flow, not graph traversal — a framework's DAG/state-machine
  abstraction adds a layer to debug through without buying much here.
- The Supervisor (`dissonance/supervisor/`) already owns budgets, caps, and manifests
  cross-cuttingly; a framework would either duplicate that or fight it.
- Every loop and retry boundary stays visible in application code, which is the point when the
  loop engineering itself is the thing being demonstrated (plan.md §10).
- Fallback if this becomes unwieldy past Week 4 (adjudicator tiering, watcher scheduling):
  reconsider LangGraph for the adjudicator's multi-tier escalation specifically, not the whole
  pipeline.

## Consequences
- We write our own fan-out/merge, retry, and rate-limiting helpers instead of getting them from a
  framework. Kept small and stage-local on purpose.
- No framework-specific tracing integration; tracing goes through Langfuse directly (see
  [0002-tracing-deferred.md](0002-tracing-deferred.md)).
