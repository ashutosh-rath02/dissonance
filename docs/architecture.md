# Architecture

Full design rationale lives in [plan.md](../plan.md) (the original design doc — kept at repo root
on purpose so it stays the source of truth). This file tracks what's actually built vs. planned.

## Component map

```
Research question
      │
      ▼
┌─────────────┐
│ Query        │  decomposes question into search facets           [Week 4+]
│ Planner      │  (topics, synonyms, method filters, date ranges)
└─────┬───────┘
      ▼
┌──────────────────────────────┐
│ Scout Swarm (parallel)        │  arXiv API │ OpenAlex │ Semantic Scholar   [arXiv: DONE]
│ + Screener (cheap model)      │  dedupe by DOI/arXiv ID, relevance filter [screener: Week 1+]
└─────┬────────────────────────┘
      ▼
┌──────────────────────────────┐
│ Extraction Swarm (parallel)   │  PDF/HTML → typed claims (schema below)  [Week 2]
│ ↻ schema-invalid → retry      │  each claim stores its exact source span
└─────┬────────────────────────┘
      ▼
┌─────────────┐
│ Claim Graph  │  Postgres + pgvector; entity resolution, dedup,   [schema: DONE, entity res: Week 2]
│ (persistent) │  claim ↔ paper ↔ method ↔ population links
└─────┬───────┘
      ▼
┌──────────────────────────────┐
│ Contradiction Hunter          │  candidate pairs via embedding blocking   [Week 4]
│                               │  + cheap classifier → suspected conflicts
└─────┬────────────────────────┘
      ▼
┌──────────────────────────────┐
│ Adjudicator Loop              │  pulls full-text context for both claims, [Week 4]
│ ↻ escalating model tiers      │  rules: genuine / scope-difference /
│ ↻ extraction-error → re-extract│  extraction-error, with typed verdict
└─────┬────────────────────────┘
      ▼
┌─────────────┐
│ Synthesis    │  living review page: consensus map, contradiction  [Week 5]
│ Agent        │  table, per-claim confidence, full provenance
└─────────────┘
      ▲
      └── ↻ new-paper watcher triggers incremental re-run             [Week 5]

Supervisor (cross-cutting): per-stage budgets, loop caps, kill-switch,
run manifest, tracing. Nothing runs outside the supervisor.           [DONE — dissonance/supervisor/]
```

## What's built (Week 1)

- `dissonance/supervisor/` — `RunConfig` (loads `configs/run.yaml`), `BudgetTracker` (per-stage
  spend + run-level halt at `warn_at_fraction`), `Supervisor` (stage timing, wall-clock cap,
  manifest assembly), `Manifest` (writes `runs/<run_id>/manifest.json`, prints a table).
- `dissonance/graph/` — `schema.sql` (papers, claims, conflicts tables + pgvector extension),
  `db.py` (connection), `migrate.py`, `models.py` (Pydantic mirrors of plan.md §3.2/§3.3),
  `repository.py` (`PaperRepository.upsert_many` — idempotent, reports new-vs-touched).
- `dissonance/scouts/arxiv.py` — arXiv Atom API client, parses entries into `Paper` records.
  `full_text_status` is `"unknown"` at scout time (Week 2's extraction stage verifies HTML
  availability by actually fetching `arxiv.org/html/{id}` — see plan.md §2's "flagged, not
  silently degraded" rule).
- `dissonance/scouts/run.py` — `python -m dissonance.scouts.run --query "..." --limit N`: the
  Week 1 exit test. One command, one manifest.

## Repo layout

```
dissonance/
├── README.md                  # positioning table, honest numbers (once evals land)
├── docker-compose.yml         # postgres+pgvector (langfuse deferred, see ADR 0002)
├── configs/
│   ├── run.yaml               # budgets, caps, model tiers per stage
│   └── prompts/               # versioned prompt files (populated Week 2)
├── dissonance/
│   ├── settings.py            # env-based settings (.env)
│   ├── supervisor/            # budgets, loop caps, manifests, kill-switch
│   ├── planner/                # Week 4+
│   ├── scouts/                # arxiv.py (done); openalex.py, semanticscholar.py later
│   ├── screener/               # Week 1+
│   ├── extraction/            # Week 2
│   ├── graph/                  # schema, db, models, repository
│   ├── hunter/                 # Week 4
│   ├── adjudicator/            # Week 4
│   ├── synthesis/              # Week 5
│   └── watcher/                # Week 5
├── evals/
│   ├── golden/                 # labeled papers, claims, conflict pairs (Week 3)
│   ├── suites/                 # Invarium test suites
│   └── report.py               # honest-numbers table (Week 3)
├── web/                        # living review UI (Week 5)
├── tests/                      # unit tests, no live LLM/network calls
└── docs/
    ├── architecture.md         # this file
    ├── decisions/               # ADRs
    └── benchmark.md             # Week 6
```
