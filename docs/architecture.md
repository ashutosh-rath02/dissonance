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
│ Extraction Swarm (parallel)   │  PDF/HTML → typed claims (schema below)  [DONE, sequential not parallel yet]
│ ↻ schema-invalid → retry      │  each claim stores its exact source span
└─────┬────────────────────────┘
      ▼
┌─────────────┐
│ Claim Graph  │  Postgres + pgvector; entity resolution, dedup,   [schema + entity res v1: DONE, dedup: TODO]
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

## What's built (Week 2)

- `dissonance/extraction/fetch.py` — fetches arXiv's auto-generated HTML, strips boilerplate and
  LaTeXML's hidden TeX-source `<annotation>` duplicates (see CLAUDE.md for why that matters),
  falls back to abstract-only.
- `dissonance/extraction/schema.py` — `ExtractedClaim`/`ExtractionResult` (what the model returns;
  `quote` instead of `char_start`/`char_end` since offsets are computed, not trusted from the
  model).
- `dissonance/extraction/extractor.py` — OpenAI Responses API structured-output call
  (`responses.parse`), cost computed from `configs/run.yaml`'s per-tier pricing.
- `dissonance/extraction/validator.py` — resolves `quote` to a verified `char_start`/`char_end` +
  `verbatim_hash` span in the source text; raises `SpanNotFoundError` if it doesn't appear.
- `dissonance/extraction/pipeline.py` — the retry/escalation loop (plan.md §4): validates claims
  independently within a batch (one bad quote doesn't discard the rest), escalates to the strong
  tier on sustained low confidence, quarantines a paper after `max_retries`, and trips
  `IdenticalFailureBreakerTripped` if the same failure signature repeats.
- `dissonance/graph/entity_resolution.py` — static normalization table for benchmark/method names
  (v1, per plan.md §9 — log unresolved rather than chase perfect resolution).
- `dissonance/graph/repository.py` — `ClaimRepository`, plus `extraction_status` tracking
  (`pending`/`done`/`quarantined`) on `papers` so re-runs don't reprocess finished work.
- `dissonance/extraction/run.py` — `python -m dissonance.extraction.run --limit N`: the Week 2
  exit test. Verified end-to-end against live papers (see CLAUDE.md "Current status").

## What's built (Week 3)

- `web/` — the golden-set labeling UI (plan.md §5.1). FastAPI + Jinja2, no JS framework. Browse
  papers, review each claim next to its source quote (re-fetched and sliced live from
  `char_start`/`char_end`, with a `HASH OK` / `HASH MISMATCH` check against `verbatim_hash` -- the
  citation-faithfulness mechanism plan.md §5.2 describes, made visible instead of only running in
  CI). Labels persist to `claim_labels`; `[ EXPORT GOLDEN SET ]` writes `correct`-labeled claims to
  `evals/golden/claims.json` in production's exact Claim schema. See `web/README.md`.
- `evals/llm_judge.py` -- a second, disclosed review pass distinct from the human one: an LLM
  judge (`gpt-4.1`) labels each claim against its source quote the same way the UI does, tagged
  `reviewer='llm_judge:<model>'` in `claim_labels` so it's never conflated with `reviewer='human'`
  anywhere downstream. Not a substitute for human review -- plan.md §5.1 explicitly defines the
  golden set as independent human judgment.
- `evals/report.py` (`python -m evals.report` / `make eval`) -- the honest-numbers table, reporting
  human and LLM-judge precision as separate rows, plus mechanical citation faithfulness (no labels
  needed) and cost/loops aggregated from `runs/*/manifest.json`.
- Full corpus extracted: 49/50 papers, 203 claims, $0.51 total. Current numbers: 100% citation
  faithfulness, 62% LLM-judge precision (not the v1 metric), human precision still N/A. See
  README's Honesty rule table.
- Still open for Week 3 proper: the actual human labeling pass (only a human can do this -- see
  CLAUDE.md), conflict-pair labels (needs the hunter/adjudicator schema, Week 4), and Invarium
  integration (`evals/suites/`, plan.md §5.3).

## Repo layout

```
dissonance/
├── README.md                  # positioning table, honest numbers (once evals land)
├── docker-compose.yml         # postgres+pgvector (langfuse deferred, see ADR 0002)
├── configs/
│   ├── run.yaml               # budgets, caps, model tiers per stage
│   └── prompts/               # versioned prompt files (extraction_v1.md: DONE)
├── dissonance/
│   ├── settings.py            # env-based settings (.env)
│   ├── supervisor/            # budgets, loop caps, manifests, kill-switch
│   ├── planner/                # Week 4+
│   ├── scouts/                # arxiv.py (done); openalex.py, semanticscholar.py later
│   ├── screener/               # Week 1+ (not yet built -- scout dedupe is basic upsert for now)
│   ├── extraction/            # DONE -- fetch, extractor, validator, pipeline, run.py
│   ├── graph/                  # schema, db, models, repository, entity_resolution
│   ├── hunter/                 # Week 4
│   ├── adjudicator/            # Week 4
│   ├── synthesis/              # Week 5
│   └── watcher/                # Week 5
├── evals/
│   ├── golden/                 # labeled papers, claims, conflict pairs -- app.py, DONE; report.py, TODO
│   ├── suites/                 # Invarium test suites
│   └── report.py               # honest-numbers table (Week 3)
├── web/                        # claim review/labeling UI: DONE (app.py, templates/, static/)
│                                # living review UI (contradiction table) is still Week 5
├── tests/                      # unit tests, no live LLM/network calls
└── docs/
    ├── architecture.md         # this file
    ├── decisions/               # ADRs
    └── benchmark.md             # Week 6
```
